"""One worker process per source IP. Env: SOURCE_IP."""
import logging
import os
import random
import signal
import time
from datetime import datetime, timedelta, timezone

import psycopg

from . import config, smtpcheck, warmup
from .db import init_db, q

log = logging.getLogger("worker")
IP = os.environ.get("SOURCE_IP", "")
DEFINITIVE = ("valid", "invalid", "catch_all")
RETRIABLE = ("temporary_or_greylisted", "timeout", "connect_error", "dns_error", "blocked")
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


def finish(item, verdict, reason, provider, code, store=True):
    q("""UPDATE job_items SET status = 'done', verdict = %s, reason = %s, provider = %s,
         finished_at = now() WHERE id = %s""", (verdict, reason, provider, item["id"]))
    if store and verdict in DEFINITIVE:
        q("""INSERT INTO results(email, domain, verdict, reason, provider, smtp_code, checked_at, checked_by_ip)
             VALUES (%s, %s, %s, %s, %s, %s, now(), %s)
             ON CONFLICT (email) DO UPDATE SET verdict = EXCLUDED.verdict, reason = EXCLUDED.reason,
               provider = EXCLUDED.provider, smtp_code = EXCLUDED.smtp_code,
               checked_at = now(), checked_by_ip = EXCLUDED.checked_by_ip""",
          (item["email"], item["domain"], verdict, reason, provider, code, IP))


def requeue(item, minutes, count_attempt=True):
    q("""UPDATE job_items SET status = 'queued', claimed_at = NULL,
         not_before = now() + make_interval(mins => %s::int),
         attempts = attempts - %s WHERE id = %s""",
      (minutes, 0 if count_attempt else 1, item["id"]))


def retry_or_finish(item, reason, provider):
    if reason in RETRIABLE and item["attempts"] < config.MAX_ATTEMPTS:
        requeue(item, config.RETRY_DELAY_MIN * item["attempts"])
    else:
        finish(item, "unknown", reason, provider, None, store=False)


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
    fake = f"zz-{random.getrandbits(48):012x}@{domain}"
    bump(domain)
    try:
        code, msg = smtpcheck.rcpt_probe(fake, mx, IP)
    except smtpcheck.ProbeError:
        return False
    log_probe(domain, smtpcheck.classify(code, msg)[2])
    if code in (250, 251):
        result = True
    elif 500 <= code < 600:
        result = False
    else:
        return False  # inconclusive: do not cache
    q("UPDATE domains SET catch_all = %s, catch_all_checked_at = now() WHERE domain = %s",
      (result, domain))
    return result


def handle(item):
    """Process one item. Returns True if at least one SMTP probe was made."""
    email, domain = item["email"], item["domain"]
    cached = q("""SELECT verdict, reason, provider FROM results WHERE email = %s
                  AND checked_at > now() - make_interval(days => %s::int)""",
               (email, config.REFRESH_DAYS), one=True)
    if cached:
        finish(item, cached["verdict"], cached["reason"], cached["provider"], None, store=False)
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
        finish(item, "invalid", "no_mx", provider, None)
        return False
    if catch_all_fresh(dom) and dom["catch_all"]:
        finish(item, "catch_all", "domain_accepts_everything", provider, None)
        return False

    result, used_mx = None, None
    for mx in dom["mx"][:2]:
        bump(domain)
        try:
            code, msg = smtpcheck.rcpt_probe(email, mx, IP)
        except smtpcheck.ProbeError as e:
            log_probe(domain, e.kind)
            result = ("unknown", "timeout" if e.kind == "timeout" else "connect_error", None)
            continue
        verdict, reason, outcome = smtpcheck.classify(code, msg)
        log_probe(domain, outcome)
        result, used_mx = (verdict, reason, code), mx
        break

    verdict, reason, code = result
    if verdict == "valid":
        if not catch_all_fresh(dom):
            is_ca = detect_catch_all(domain, used_mx)
        else:
            is_ca = bool(dom["catch_all"])
        if is_ca:
            verdict, reason = "catch_all", "domain_accepts_everything"
    if verdict == "unknown":
        retry_or_finish(item, reason, provider)
    else:
        finish(item, verdict, reason, provider, code)
    return True


def main():
    global _lock_conn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not IP:
        raise SystemExit("SOURCE_IP is required")
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
