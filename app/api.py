import csv
import hmac
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import config, warmup, webhook
from .auth import audit, create_key, generate_raw_key, hash_key, require_admin, require_key
from .db import init_db, pool, q
from .smtpcheck import EMAIL_SQL_RE


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Email Validation API", version="1.0.0", lifespan=lifespan)


class JobIn(BaseModel):
    emails: list[str] = Field(..., min_length=1)
    name: str | None = None
    webhook_url: str | None = None


def check_webhook(url):
    if not url:
        return None
    try:
        return webhook.validate_url(url)
    except webhook.WebhookError as e:
        raise HTTPException(400, str(e))


def enqueue(key_id, name, emails, webhook_url=None):
    emails = list(dict.fromkeys(e.strip().lower() for e in emails if e and e.strip()))
    if not emails:
        raise HTTPException(400, "No email addresses supplied")
    if len(emails) > config.MAX_BATCH:
        raise HTTPException(413, f"Maximum {config.MAX_BATCH} addresses per job")
    rows = [(e, e.rsplit("@", 1)[-1] if "@" in e else "") for e in emails]
    with pool().connection() as conn, conn.transaction():
        job_id = conn.execute("INSERT INTO jobs(key_id, name, total, webhook_url) VALUES (%s, %s, %s, %s) RETURNING id",
                              (key_id, name, len(emails), webhook_url)).fetchone()["id"]
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO job_items(job_id, email, domain) VALUES (%s, %s, %s)",
                            [(job_id, e, d) for e, d in rows])
        # bad syntax: finish immediately
        conn.execute("""UPDATE job_items SET status = 'done', verdict = 'invalid', reason = 'bad_syntax',
                        provider = 'other', finished_at = now()
                        WHERE job_id = %s AND email !~ %s""", (job_id, EMAIL_SQL_RE))
        # fresh stored results: reuse without probing (lazy refresh)
        conn.execute("""UPDATE job_items ji SET status = 'done', verdict = r.verdict, reason = r.reason,
                        provider = r.provider, finished_at = now()
                        FROM results r
                        WHERE ji.job_id = %s AND ji.status = 'queued' AND ji.email = r.email
                          AND r.checked_at > now() - make_interval(days => %s::int)""",
                     (job_id, config.REFRESH_DAYS))
    return job_id, len(emails)


def own_job(job_id, key):
    job = q("SELECT * FROM jobs WHERE id = %s", (job_id,), one=True)
    if not job or (job["key_id"] != key["id"] and not key["is_admin"]):
        raise HTTPException(404, "Job not found")
    return job


def safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


@app.get("/healthz")
def healthz():
    q("SELECT 1")
    return {"ok": True}


@app.post("/v1/jobs", status_code=202)
def create_job(body: JobIn, request: Request, key=Depends(require_key)):
    job_id, total = enqueue(key["id"], body.name, body.emails, check_webhook(body.webhook_url))
    audit(key["id"], "job_create", f"job={job_id} total={total}", request)
    return {"job_id": job_id, "total": total}


@app.post("/v1/jobs/upload", status_code=202)
def upload_job(request: Request, file: UploadFile = File(...),
               webhook_url: str | None = Form(default=None), key=Depends(require_key)):
    webhook_url = check_webhook(webhook_url)
    text = file.file.read().decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise HTTPException(400, "Empty file")
    header = [h.strip().lower() for h in rows[0]]
    if "email" in header:
        idx, data = header.index("email"), rows[1:]
    else:
        idx, data = 0, rows
    emails = [r[idx] for r in data if len(r) > idx]
    job_id, total = enqueue(key["id"], file.filename, emails, webhook_url)
    audit(key["id"], "job_upload", f"job={job_id} file={file.filename} total={total}", request)
    return {"job_id": job_id, "total": total}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: int, request: Request, key=Depends(require_key)):
    job = own_job(job_id, key)
    status = {r["status"]: r["n"] for r in q(
        "SELECT status, count(*) n FROM job_items WHERE job_id = %s GROUP BY status", (job_id,))}
    verdicts = {r["verdict"]: r["n"] for r in q(
        "SELECT verdict, count(*) n FROM job_items WHERE job_id = %s AND status = 'done' GROUP BY verdict",
        (job_id,))}
    by_provider = q("""SELECT provider, verdict, count(*) n FROM job_items
                       WHERE job_id = %s AND status = 'done' GROUP BY 1, 2 ORDER BY 1, 2""", (job_id,))
    pending = status.get("queued", 0) + status.get("running", 0)
    return {"job_id": job_id, "name": job["name"], "created_at": job["created_at"],
            "total": job["total"], "done": status.get("done", 0), "pending": pending,
            "finished": pending == 0, "verdicts": verdicts, "by_provider": by_provider,
            "webhook": {"url": job["webhook_url"], "delivered_at": job["webhook_sent_at"],
                        "attempts": job["webhook_attempts"]} if job["webhook_url"] else None}


@app.get("/v1/jobs/{job_id}/results.csv")
def job_csv(job_id: int, request: Request, key=Depends(require_key)):
    own_job(job_id, key)
    rows = q("""SELECT email, verdict, reason, provider, finished_at FROM job_items
                WHERE job_id = %s ORDER BY id""", (job_id,))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "verdict", "reason", "provider", "checked_at"])
    for r in rows:
        w.writerow([safe(r["email"]), r["verdict"] or "pending", r["reason"] or "",
                    r["provider"] or "", r["finished_at"].isoformat() if r["finished_at"] else ""])
    audit(key["id"], "job_download", f"job={job_id}", request)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="job-{job_id}.csv"'})


@app.get("/v1/result")
def stored_result(email: str, request: Request, key=Depends(require_key)):
    row = q("""SELECT email, verdict, reason, provider, checked_at FROM results
               WHERE email = %s""", (email.strip().lower(),), one=True)
    audit(key["id"], "result_lookup", "", request)
    if not row:
        raise HTTPException(404, "No stored result; submit it as a job")
    return row


# ------------------------------ first admin key ------------------------------

class BootstrapIn(BaseModel):
    name: str = "First admin"


@app.post("/bootstrap", status_code=201)
def bootstrap(body: BootstrapIn, request: Request, x_setup_token: str | None = Header(default=None)):
    """Create the very first admin key. Works only while no active admin key exists and only
    with the one-time BOOTSTRAP_TOKEN from the server's .env (header X-Setup-Token)."""
    if not config.BOOTSTRAP_TOKEN:
        raise HTTPException(404, "Not found")  # disabled: behaves as if the route does not exist
    if len(config.BOOTSTRAP_TOKEN) < config.BOOTSTRAP_TOKEN_MIN_LENGTH:
        raise HTTPException(503, f"BOOTSTRAP_TOKEN must be at least {config.BOOTSTRAP_TOKEN_MIN_LENGTH} characters")
    if not x_setup_token or not hmac.compare_digest(x_setup_token, config.BOOTSTRAP_TOKEN):
        audit(None, "bootstrap_failed", "bad setup token", request)
        raise HTTPException(401, "Invalid setup token")
    raw = generate_raw_key()
    with pool().connection() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(728)")  # two simultaneous calls cannot both win
        if conn.execute("SELECT 1 FROM api_keys WHERE is_admin AND active LIMIT 1").fetchone():
            raise HTTPException(409, "An admin key already exists. Use POST /admin/keys")
        conn.execute("INSERT INTO api_keys(name, key_hash, is_admin) VALUES (%s, %s, true)",
                     (body.name, hash_key(raw)))
    audit(None, "bootstrap", f"first admin key created: {body.name}", request)
    return {"api_key": raw, "note": "Shown once. Store it safely, then remove BOOTSTRAP_TOKEN from .env."}


# ------------------------------ admin ------------------------------

@app.get("/admin/status")
def admin_status(key=Depends(require_admin)):
    queue = {r["status"]: r["n"] for r in q(
        "SELECT status, count(*) n FROM job_items WHERE status IN ('queued','running') GROUP BY status")}
    ips = q("""SELECT s.*, coalesce(u.count, 0) AS used_today,
                      coalesce(p.n, 0) AS probes_60m, coalesce(p.b, 0) AS blocked_60m
               FROM ip_state s
               LEFT JOIN usage_daily u ON u.ip = s.ip AND u.day = current_date AND u.domain = '*'
               LEFT JOIN (SELECT ip, count(*) n, count(*) FILTER (WHERE outcome = 'blocked') b
                          FROM probe_log WHERE at > now() - interval '60 minutes' GROUP BY ip) p
                      ON p.ip = s.ip
               ORDER BY s.ip""")
    now = datetime.now(timezone.utc)
    for r in ips:
        r["daily_limit"] = warmup.daily_limit(r["added_at"])
        r["block_rate_60m"] = round(r["blocked_60m"] / r["probes_60m"], 3) if r["probes_60m"] else 0
        r["worker_alive"] = bool(r["last_seen"] and (now - r["last_seen"]).total_seconds() < 300)
    verdicts = {r["verdict"]: r["n"] for r in q(
        "SELECT verdict, count(*) n FROM job_items WHERE finished_at >= current_date GROUP BY verdict")}
    return {"queue": queue, "verdicts_today": verdicts, "ips": ips}


@app.post("/admin/ips/{ip}/pause")
def pause_ip(ip: str, request: Request, key=Depends(require_admin)):
    q("""UPDATE ip_state SET status = 'paused', pause_reason = 'manual', paused_until = NULL
         WHERE ip = %s""", (ip,))
    audit(key["id"], "ip_pause", ip, request)
    return {"ip": ip, "status": "paused"}


@app.post("/admin/ips/{ip}/resume")
def resume_ip(ip: str, request: Request, key=Depends(require_admin)):
    q("""UPDATE ip_state SET status = 'active', pause_reason = NULL, paused_until = NULL
         WHERE ip = %s""", (ip,))
    audit(key["id"], "ip_resume", ip, request)
    return {"ip": ip, "status": "active"}


class KeyIn(BaseModel):
    name: str
    admin: bool = False


@app.post("/admin/keys")
def new_key(body: KeyIn, request: Request, key=Depends(require_admin)):
    raw = create_key(body.name, body.admin)
    audit(key["id"], "key_create", f"name={body.name} admin={body.admin}", request)
    return {"api_key": raw, "note": "Shown once. Store it safely."}


@app.get("/admin/keys")
def list_keys(key=Depends(require_admin)):
    return q("SELECT id, name, is_admin, active, created_at FROM api_keys ORDER BY id")


@app.delete("/admin/keys/{key_id}")
def revoke_key(key_id: int, request: Request, key=Depends(require_admin)):
    if key_id == key["id"]:
        raise HTTPException(400, "You cannot revoke the key you are using")
    row = q("UPDATE api_keys SET active = false WHERE id = %s RETURNING id", (key_id,), one=True)
    if not row:
        raise HTTPException(404, "Key not found")
    audit(key["id"], "key_revoke", f"id={key_id}", request)
    return {"revoked": key_id}


@app.get("/admin/audit")
def audit_log(limit: int = 100, key=Depends(require_admin)):
    return q("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 1000),))


DASHBOARD = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Email validation status</title>
<style>body{font:14px system-ui,sans-serif;margin:20px}table{border-collapse:collapse;margin:10px 0}
td,th{border:1px solid #8886;padding:4px 8px;text-align:left}.bad{color:#c62828;font-weight:600}
.ok{color:#2e7d32}</style>
<h2>Email validation status</h2><div id="sum"></div><table id="t"></table>
<script>
const key = prompt("Admin API key");
const el = (t, txt, cls) => { const e = document.createElement(t); e.textContent = txt; if (cls) e.className = cls; return e; };
async function load() {
  const r = await fetch("/admin/status", {headers: {"X-API-Key": key}});
  const sum = document.getElementById("sum");
  if (!r.ok) { sum.textContent = "Auth failed (" + r.status + ")"; return; }
  const d = await r.json();
  sum.textContent = "Queued: " + (d.queue.queued || 0) + " | Running: " + (d.queue.running || 0) +
    " | Today: " + JSON.stringify(d.verdicts_today);
  const t = document.getElementById("t"); t.replaceChildren();
  const head = document.createElement("tr");
  ["IP","Status","Reason","Used / limit","Block rate 60m","Blacklists","Worker"].forEach(h => head.append(el("th", h)));
  t.append(head);
  d.ips.forEach(i => {
    const tr = document.createElement("tr");
    tr.append(el("td", i.ip), el("td", i.status, i.status === "active" ? "ok" : "bad"),
      el("td", i.pause_reason || ""), el("td", i.used_today + " / " + i.daily_limit),
      el("td", (i.block_rate_60m * 100).toFixed(1) + "% (" + i.probes_60m + ")"),
      el("td", i.blacklisted.length ? i.blacklisted.join(", ") : "clean", i.blacklisted.length ? "bad" : "ok"),
      el("td", i.worker_alive ? "alive" : "DOWN", i.worker_alive ? "ok" : "bad"));
    t.append(tr);
  });
}
load(); setInterval(load, 10000);
</script>"""


@app.get("/admin/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD
