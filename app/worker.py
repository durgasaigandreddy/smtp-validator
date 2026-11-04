"""One worker process per source IP. Env: SOURCE_IP."""
import logging
import os
import random
import signal
import socket
import time
from datetime import datetime, timedelta, timezone

import psycopg

from . import config, smtpcheck, warmup
from .db import init_db, q

log = logging.getLogger("worker")
IP = os.environ.get("SOURCE_IP", "")
DEFINITIVE = ("valid", "invalid", "catch_all")
RETRIABLE = ("temporary_failure", "timeout", "connection_failed", "dns_error", "probe_blocked")
running = True
_last_beat = 0.0
_lock_conn = None  # held open for the life of the process


def stop(*_):
    global running
    running = False


def beat():
    global _last_beat
    if time.time() - _last_beat > 30:
        q("UPDATE ip_state SET last_seen = now() WHERE ip = %s", (IP,))
        _last_beat = time.time()


def nap(seconds):
    end = time.time() + seconds
    while running and time.time() < end:
        time.sleep(min(1, end - time.time()))
        beat()


def used_today():
    r = q("SELECT count FROM usage_daily WHERE day = current_date AND ip = %s AND domain = '*'",
          (IP,), one=True)
    return r["count"] if r else 0


def used_domain(domain):
    r = q("SELECT count FROM usage_daily WHERE day = current_date AND ip = %s AND domain = %s",
          (IP, domain), one=True)
    return r["count"] if r else 0


def bump(domain):
    q("""INSERT INTO usage_daily(day, ip, domain, count)
         VALUES (current_date, %s, %s, 1), (current_date, %s, '*', 1)
         ON CONFLICT (day, ip, domain) DO UPDATE SET count = usage_daily.count + 1""",
      (IP, domain, IP))


def log_probe(domain, outcome):
    q("INSERT INTO probe_log(ip, domain, outcome) VALUES (%s, %s, %s)", (IP, domain, outcome))


def claim():
    return q("""UPDATE job_items SET status = 'running', claimed_at = now(), attempts = attempts + 1
                WHERE id = (SELECT id FROM job_items
                            WHERE status = 'queued' AND not_before <= now()
                            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING *""", one=True)


INFO_KEYS = ("mx_host", "smtp_status", "smtp_message", "catch_all", "checked_at")


def finish(item, verdict, reason, provider, code, store=True, info=None):
    """Mark an item done. info carries the details shown in the results CSV."""
    info = info or {}
    q("""UPDATE job_items SET status = 'done', verdict = %s, reason = %s, provider = %s,
         mx_host = %s, smtp_status = %s, smtp_message = %s, catch_all = %s,
         checked_at = coalesce(%s, now()), finished_at = now() WHERE id = %s""",
      (verdict, reason, provider, info.get("mx_host"), info.get("smtp_status"), info.get("smtp_message"),
       info.get("catch_all"), info.get("checked_at"), item["id"]))
    if store and verdict in DEFINITIVE:
        q("""INSERT INTO results(email, domain, verdict, reason, provider, smtp_code, mx_host, smtp_status,
                                 smtp_message, catch_all, checked_at, checked_by_ip)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
             ON CONFLICT (email) DO UPDATE SET verdict = EXCLUDED.verdict, reason = EXCLUDED.reason,
               provider = EXCLUDED.provider, smtp_code = EXCLUDED.smtp_code, mx_host = EXCLUDED.mx_host,
               smtp_status = EXCLUDED.smtp_status, smtp_message = EXCLUDED.smtp_message,
               catch_all = EXCLUDED.catch_all, checked_at = now(), checked_by_ip = EXCLUDED.checked_by_ip""",
          (item["email"], item["domain"], verdict, reason, provider, code, info.get("mx_host"),
           info.get("smtp_status"), info.get("smtp_message"), info.get("catch_all"), IP))


def requeue(item, minutes, count_attempt=True):
    q("""UPDATE job_items SET status = 'queued', claimed_at = NULL,
         not_before = now() + make_interval(mins => %s::int),
         attempts = attempts - %s WHERE id = %s""",
      (minutes, 0 if count_attempt else 1, item["id"]))


def retry_or_finish(item, reason, provider, info=None):
    if reason in RETRIABLE and item["attempts"] < config.MAX_ATTEMPTS:
        requeue(item, config.RETRY_DELAY_MIN * item["attempts"])
    else:
        finish(item, "unknown", reason, provider, None, store=False, info=info)


def get_domain(domain):
    now = datetime.now(timezone.utc)
    row = q("SELECT * FROM domains WHERE domain = %s", (domain,), one=True)
    if row and row["mx_checked_at"] and row["mx_checked_at"] > now - timedelta(days=config.MX_REFRESH_DAYS):
        return row
    mx, err = smtpcheck.resolve_mx(domain)
    if err == "dns_error":
        return row if row and row["mx"] else {"mx": [], "error": "dns_error", "provider": "other",
                                              "catch_all": None, "catch_all_checked_at": None}
    provider = smtpcheck.provider_of(mx)
    q("""INSERT INTO domains(domain, mx, provider, mx_checked_at) VALUES (%s, %s, %s, now())
         ON CONFLICT (domain) DO UPDATE SET mx = EXCLUDED.mx, provider = EXCLUDED.provider,
           mx_checked_at = now()""", (domain, mx, provider))
    return q("SELECT * FROM domains WHERE domain = %s", (domain,), one=True)


def catch_all_fresh(dom):
    ts = dom.get("catch_all_checked_at")
    return (dom.get("catch_all") is not None and ts is not None and
            ts > datetime.now(timezone.utc) - timedelta(days=config.CATCHALL_REFRESH_DAYS))


def detect_catch_all(domain, mx):
    """True / False when the answer is clear, None when it could not be decided (not cached)."""
    fake = f"zz-{random.getrandbits(48):012x}@{domain}"
    bump(domain)
    try:
        code, msg = smtpcheck.rcpt_probe(fake, mx, IP)
    except smtpcheck.ProbeError:
        return None
    verdict, _reason, outcome = smtpcheck.classify(code, msg)
    log_probe(domain, outcome)
    if verdict == "valid":
        result = True               # a made-up address was accepted: the domain accepts everything
    elif verdict == "invalid":
        result = False              # a made-up address was refused: it checks mailboxes
    else:
        return None                 # blocked, temporary or unclear: says nothing about the domain
    q("UPDATE domains SET catch_all = %s, catch_all_checked_at = now() WHERE domain = %s", (result, domain))
    return result


def handle(item):
    """Process one item. Returns True if at least one SMTP probe was made."""
    email, domain = item["email"], item["domain"]
    cached = q("""SELECT verdict, reason, provider, mx_host, smtp_status, smtp_message, catch_all, checked_at
                  FROM results WHERE email = %s
                  AND checked_at > now() - make_interval(days => %s::int)""",
               (email, config.REFRESH_DAYS), one=True)
    if cached:
        finish(item, cached["verdict"], cached["reason"], cached["provider"], None, store=False,
               info={k: cached[k] for k in INFO_KEYS})
        return False

    if used_domain(domain) >= config.PER_DOMAIN_IP_DAILY:
        requeue(item, 30, count_attempt=False)  # another IP, or tomorrow
        return False

    dom = get_domain(domain)
    provider = dom.get("provider") or "other"
    if dom.get("error") == "dns_error":
        retry_or_finish(item, "dns_error", provider)
        return False
    if not dom["mx"]:
        finish(item, "invalid", "no_mail_server", provider, None)
        return False
    if catch_all_fresh(dom) and dom["catch_all"]:
        finish(item, "catch_all", "catch_all", provider, None, info={
            "mx_host": dom["mx"][0], "smtp_status": "250", "catch_all": True,
            "smtp_message": "Domain accepts mail for any address (known from an earlier check)"})
        return False

    result, info, used_mx = None, None, None
    for mx in dom["mx"][:2]:
        bump(domain)
        try:
            code, msg = smtpcheck.rcpt_probe(email, mx, IP)
        except smtpcheck.ProbeError as e:
            log_probe(domain, e.kind)
            timed_out = e.kind == "timeout"
            result = ("unknown", "timeout" if timed_out else "connection_failed", None)
            info = {"mx_host": mx, "smtp_status": "", "smtp_message":
                    "Connection timed out" if timed_out else "Could not connect to the mail server"}
            continue
        verdict, reason, outcome = smtpcheck.classify(code, msg)
        log_probe(domain, outcome)
        status, text = smtpcheck.parse_reply(code, msg)
        result, used_mx = (verdict, reason, code), mx
        info = {"mx_host": mx, "smtp_status": status, "smtp_message": text}
        break

    verdict, reason, code = result
    if verdict == "valid":
        is_ca = bool(dom["catch_all"]) if catch_all_fresh(dom) else detect_catch_all(domain, used_mx)
        info["catch_all"] = is_ca          # True, False, or None when it could not be decided
        if is_ca:
            verdict, reason = "catch_all", "catch_all"
    if verdict == "unknown":
        retry_or_finish(item, reason, provider, info)
    else:
        finish(item, verdict, reason, provider, code, info=info)
    return True


def main():
    global _lock_conn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not IP:
        raise SystemExit("SOURCE_IP is required (the worker never guesses the machine's own address)")
    try:
        with socket.socket() as probe:
            probe.bind((IP, 0))
    except OSError as e:
        raise SystemExit(f"{IP} is not an address of this machine ({e}). Add it to the network adapter first.")
    init_db()
    # Only one worker may run per IP. The lock lives as long as this connection; if the
    # process dies the database releases it, so nothing can get stuck.
    _lock_conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    if not _lock_conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))",
                              ("worker:" + IP,)).fetchone()[0]:
        raise SystemExit(f"Another worker is already running for {IP}; exiting")
    q("""INSERT INTO ip_state(ip, last_seen) VALUES (%s, now())
         ON CONFLICT (ip) DO UPDATE SET last_seen = now()""", (IP,))
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker started for %s", IP)

    while running:
        try:
            beat()
            state = q("SELECT * FROM ip_state WHERE ip = %s", (IP,), one=True)
            if state is None:  # row removed by an admin: register again
                q("INSERT INTO ip_state(ip, last_seen) VALUES (%s, now()) ON CONFLICT (ip) DO NOTHING", (IP,))
                continue
            if state["status"] != "active":
                nap(30)
                continue
            if used_today() >= warmup.daily_limit(state["added_at"]):
                nap(60)
                continue
            item = claim()
            if not item:
                nap(5)
                continue
            probed = handle(item)
            if probed:
                nap(random.uniform(config.PACE_MIN, config.PACE_MAX))
        except Exception:
            log.exception("worker loop error")
            nap(10)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
