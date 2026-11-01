"""Health monitor: blacklists, block rates, stuck items, queue, alerts, retention."""
import logging
import threading
import time
from datetime import date, datetime

from . import config, webhook
from .alerts import alert_once, send
from .db import init_db, q
from .smtpcheck import dnsbl_name

log = logging.getLogger("monitor")


def check_ip(ip):
    import dns.resolver
    listed = []
    for zone in config.DNSBLS:
        try:
            ans = dns.resolver.resolve(dnsbl_name(ip, zone), "A", lifetime=5)
            if any(r.to_text().startswith("127.255.255.") for r in ans):
                continue  # resolver refused by the list; not a listing
            listed.append(zone)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            pass
        except Exception as e:
            log.warning("DNSBL %s lookup failed for %s: %s", zone, ip, e)
    return listed


def check_blacklists():
    for row in q("SELECT * FROM ip_state"):
        ip = row["ip"]
        listed = check_ip(ip)
        q("UPDATE ip_state SET blacklisted = %s::text[], last_blacklist_check = now() WHERE ip = %s",
          (listed, ip))
        if listed and row["status"] == "active":
            q("""UPDATE ip_state SET status = 'paused', pause_reason = 'blacklisted',
                 paused_until = NULL WHERE ip = %s""", (ip,))
            alert_once(f"bl:{ip}", f"[EmailVal] IP {ip} is blacklisted",
                       f"Listed on: {', '.join(listed)}.\nThe IP has been paused. Request delisting; "
                       "it resumes automatically once it is clean.")
        elif not listed and row["status"] == "paused" and row["pause_reason"] == "blacklisted":
            q("""UPDATE ip_state SET status = 'active', pause_reason = NULL WHERE ip = %s""", (ip,))
            send(f"[EmailVal] IP {ip} is clean again", "Blacklist entries cleared. IP resumed.")


def check_block_rates():
    rows = q("""SELECT ip, count(*) n, count(*) FILTER (WHERE outcome = 'blocked') b
                FROM probe_log WHERE at > now() - interval '60 minutes' GROUP BY ip""")
    for r in rows:
        if r["n"] >= config.BLOCK_MIN_SAMPLE and r["b"] / r["n"] >= config.BLOCK_RATE_PAUSE:
            hit = q("""UPDATE ip_state SET status = 'paused', pause_reason = 'block_rate',
                       paused_until = now() + make_interval(hours => %s::int)
                       WHERE ip = %s AND status = 'active' RETURNING ip""",
                    (config.PAUSE_HOURS, r["ip"]), one=True)
            if hit:
                alert_once(f"br:{r['ip']}", f"[EmailVal] IP {r['ip']} paused: high block rate",
                           f"{r['b']} of {r['n']} probes were blocked in the last hour. "
                           f"Paused for {config.PAUSE_HOURS}h.")


def resume_expired():
    q("""UPDATE ip_state SET status = 'active', pause_reason = NULL, paused_until = NULL
         WHERE status = 'paused' AND paused_until IS NOT NULL AND paused_until <= now()""")


def requeue_stuck():
    q("""UPDATE job_items SET status = 'queued', claimed_at = NULL
         WHERE status = 'running' AND claimed_at < now() - interval '10 minutes'""")


def check_workers_and_queue():
    dead = q("""SELECT ip FROM ip_state WHERE status = 'active'
                AND (last_seen IS NULL OR last_seen < now() - interval '5 minutes')""")
    for r in dead:
        alert_once(f"down:{r['ip']}", f"[EmailVal] Worker for {r['ip']} is not running",
                   "No heartbeat for 5 minutes. Check: docker compose ps / logs.")
    queued = q("SELECT count(*) n FROM job_items WHERE status = 'queued'", one=True)["n"]
    alive = q("""SELECT count(*) n FROM ip_state WHERE status = 'active'
                 AND last_seen > now() - interval '5 minutes'""", one=True)["n"]
    if queued > 0 and alive == 0:
        alert_once("no_active_ips", "[EmailVal] Queue is waiting but no IP is active",
                   f"{queued} items queued; every IP is paused or down.")
    if queued > config.QUEUE_ALERT:
        alert_once("queue_big", "[EmailVal] Queue is very large",
                   f"{queued} items queued (threshold {config.QUEUE_ALERT}).")


def send_webhooks():
    jobs = q("""SELECT j.* FROM jobs j
                WHERE j.webhook_url IS NOT NULL AND j.webhook_sent_at IS NULL
                  AND j.webhook_attempts < %s AND coalesce(j.webhook_next_at, now()) <= now()
                  AND NOT EXISTS (SELECT 1 FROM job_items i WHERE i.job_id = j.id
                                  AND i.status IN ('queued', 'running'))
                ORDER BY j.id LIMIT 20""", (config.WEBHOOK_MAX_ATTEMPTS,))
    for j in jobs:
        verdicts = {r["verdict"]: r["n"] for r in q(
            "SELECT verdict, count(*) n FROM job_items WHERE job_id = %s GROUP BY verdict", (j["id"],))}
        path = f"/v1/jobs/{j['id']}/results.csv"
        payload = {"event": "job.finished", "job_id": j["id"], "name": j["name"],
                   "total": j["total"], "verdicts": verdicts,
                   "results_url": (config.PUBLIC_BASE_URL.rstrip("/") + path) if config.PUBLIC_BASE_URL else path}
        ok, info = webhook.deliver(j["webhook_url"], payload)
        attempts = j["webhook_attempts"] + 1
        if ok:
            q("UPDATE jobs SET webhook_sent_at = now(), webhook_attempts = %s WHERE id = %s",
              (attempts, j["id"]))
        else:
            q("""UPDATE jobs SET webhook_attempts = %s,
                 webhook_next_at = now() + make_interval(mins => %s::int) WHERE id = %s""",
              (attempts, 2 ** attempts, j["id"]))
            log.warning("webhook for job %s failed (%s), attempt %s", j["id"], info, attempts)
            if attempts >= config.WEBHOOK_MAX_ATTEMPTS:
                alert_once(f"webhook:{j['id']}", f"[EmailVal] Webhook for job {j['id']} failed",
                           f"Gave up after {attempts} attempts. Last error: {info}")


def purge():
    d = (config.JOB_RETENTION_DAYS, config.RESULT_RETENTION_DAYS, config.AUDIT_RETENTION_DAYS)
    q("DELETE FROM jobs WHERE created_at < now() - make_interval(days => %s::int)", (d[0],))
    q("DELETE FROM results WHERE checked_at < now() - make_interval(days => %s::int)", (d[1],))
    q("DELETE FROM audit_log WHERE at < now() - make_interval(days => %s::int)", (d[2],))
    q("DELETE FROM probe_log WHERE at < now() - interval '14 days'")
    q("DELETE FROM usage_daily WHERE day < current_date - 14")
    q("DELETE FROM alerts_sent WHERE at < now() - interval '30 days'")
    log.info("retention purge done")


def webhook_loop():
    while True:
        try:
            send_webhooks()
        except Exception:
            log.exception("webhook loop failed")
        time.sleep(30)


def blacklist_loop():
    while True:
        try:
            check_blacklists()
        except Exception:
            log.exception("blacklist loop failed")
        time.sleep(config.BLACKLIST_INTERVAL_MIN * 60)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_db()
    # Slow, network-bound work runs in its own threads so that a slow webhook receiver or a
    # slow DNS blacklist can never delay block-rate pausing and the other fast checks below.
    for target in (webhook_loop, blacklist_loop):
        threading.Thread(target=target, daemon=True, name=target.__name__).start()
    last_purge = None
    while True:
        try:
            requeue_stuck()
            log.info("checking heartBeat1{}")
            resume_expired()
            log.info("checking heartBeat2{}")
            check_block_rates()
            log.info("checking heartBeat3{}")
            check_workers_and_queue()
            log.info("checking heartBeat4{}")
            if date.today() != last_purge and datetime.now().hour >= 3:
                purge()
                last_purge = date.today()
        except Exception:
            log.exception("monitor cycle failed")
        time.sleep(60)


if __name__ == "__main__":
    main()
