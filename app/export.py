"""Results in the client's CSV format (13 columns), plus the compact and extended variants.

full      (default) email, verdict, reason, description, domain, mx_host, smtp_code, smtp_message,
          catch_all, role, free_provider, disposable, checked_at
extended  the same columns plus provider (mail provider group)
simple    email, verdict, reason, provider, checked_at
"""
import csv
import io
from datetime import timezone

from . import lists

COLUMNS = ["email", "verdict", "reason", "description", "domain", "mx_host", "smtp_code", "smtp_message",
           "catch_all", "role", "free_provider", "disposable", "checked_at"]
FORMATS = {"full": COLUMNS, "extended": COLUMNS + ["provider"],
           "simple": ["email", "verdict", "reason", "provider", "checked_at"]}

# The first six are exactly the client's wording. The rest follow the same style (not in the client's sample).
DESCRIPTIONS = {
    "mailbox_exists": "The mail server confirmed this mailbox exists.",
    "probe_blocked": "The mail server refused our check (anti-spam or policy), so the mailbox cannot be confirmed.",
    "catch_all": "The domain accepts mail for any address, so this mailbox cannot be confirmed.",
    "mailbox_not_found": "The mail server says this mailbox doesn't exist.",
    "dns_error": "The DNS lookup failed or timed out. Try again later.",
    "syntax_too_long": "The address is longer than email allows.",
    "syntax_invalid": "The address is not written in a valid email format.",
    "no_mail_server": "The domain has no mail server, so it cannot receive email.",
    "timeout": "The mail server did not answer in time. Try again later.",
    "connection_failed": "We could not connect to the mail server. Try again later.",
    "temporary_failure": "The mail server asked us to try again later, for example because of greylisting.",
    "mailbox_full": "The mailbox exists but is full, so mail would bounce for now.",
    "smtp_error": "The mail server gave an unexpected answer, so the mailbox cannot be confirmed.",
}
SYNTAX_REASONS = ("syntax_invalid", "syntax_too_long")


def fmt_ts(dt):
    """2026-10-19T17:35:28.792Z (UTC, milliseconds, trailing Z)."""
    if not dt:
        return ""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _safe(v):
    """Stop spreadsheet formula injection: remote servers control smtp_message."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def _yn(flag):
    return "yes" if flag else "no"


def record(r):
    """One result as a dict of strings. r is a job_items-like row (a dict)."""
    done = r.get("status", "done") == "done" and bool(r.get("verdict"))
    email = r.get("email_input") or r.get("email") or ""
    reason = (r.get("reason") or "") if done else ""
    domain = "" if reason in SYNTAX_REASONS else (r.get("domain") or "")
    ca = r.get("catch_all")
    return {
        "email": _safe(email),
        "verdict": r["verdict"] if done else "pending",
        "reason": reason,
        "description": DESCRIPTIONS.get(reason, "") if done else "Not checked yet.",
        "domain": domain,
        "mx_host": r.get("mx_host") or "",
        "smtp_code": r.get("smtp_status") or "",
        "smtp_message": _safe(r.get("smtp_message")),
        "catch_all": "" if ca is None else _yn(ca),
        "role": _yn(lists.is_role(email)),
        "free_provider": _yn(lists.is_free(domain)),
        "disposable": _yn(lists.is_disposable(domain)),
        "checked_at": fmt_ts(r.get("checked_at") or r.get("finished_at")) if done else "",
        "provider": r.get("provider") or "",
    }


def render_csv(rows, fmt="full"):
    cols = FORMATS[fmt]
    buf = io.StringIO()
    w = csv.writer(buf)  # default CRLF line endings, like the client's file
    w.writerow(cols)
    for r in rows:
        rec = record(r)
        w.writerow([rec[c] for c in cols])
    return buf.getvalue()
