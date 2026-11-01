import os


def _s(k, d=""):
    return os.environ.get(k, d)


def _i(k, d):
    return int(os.environ.get(k, d))


def _f(k, d):
    return float(os.environ.get(k, d))


DATABASE_URL = _s("DATABASE_URL", "postgresql://validator:change-me@127.0.0.1:5432/validator")

HELO_HOST = _s("HELO_HOST", "mail.example.com")
MAIL_FROM = _s("MAIL_FROM", "probe@example.com")
SMTP_TIMEOUT = _i("SMTP_TIMEOUT", 20)
PACE_MIN = _f("PACE_MIN", 2.0)
PACE_MAX = _f("PACE_MAX", 6.0)

REFRESH_DAYS = _i("REFRESH_DAYS", 30)
MX_REFRESH_DAYS = _i("MX_REFRESH_DAYS", 7)
CATCHALL_REFRESH_DAYS = _i("CATCHALL_REFRESH_DAYS", 30)

PER_DOMAIN_IP_DAILY = _i("PER_DOMAIN_IP_DAILY", 150)
WARMUP_DAYS = _i("WARMUP_DAYS", 60)
WARMUP_START = _i("WARMUP_START", 50)
IP_DAILY_MAX = _i("IP_DAILY_MAX", 1500)

MAX_ATTEMPTS = _i("MAX_ATTEMPTS", 3)
RETRY_DELAY_MIN = _i("RETRY_DELAY_MIN", 30)
MAX_BATCH = _i("MAX_BATCH", 100000)

BLOCK_RATE_PAUSE = _f("BLOCK_RATE_PAUSE", 0.30)
BLOCK_MIN_SAMPLE = _i("BLOCK_MIN_SAMPLE", 20)
PAUSE_HOURS = _i("PAUSE_HOURS", 6)
BLACKLIST_INTERVAL_MIN = _i("BLACKLIST_INTERVAL_MIN", 30)
DNSBLS = [z.strip() for z in _s(
    "DNSBLS", "zen.spamhaus.org,b.barracudacentral.org,bl.spamcop.net,psbl.surriel.com"
).split(",") if z.strip()]
QUEUE_ALERT = _i("QUEUE_ALERT", 200000)

JOB_RETENTION_DAYS = _i("JOB_RETENTION_DAYS", 90)
RESULT_RETENTION_DAYS = _i("RESULT_RETENTION_DAYS", 365)
AUDIT_RETENTION_DAYS = _i("AUDIT_RETENTION_DAYS", 730)

ALERT_TO = _s("ALERT_TO")
ALERT_FROM = _s("ALERT_FROM")
ALERT_SMTP_HOST = _s("ALERT_SMTP_HOST")
ALERT_SMTP_PORT = _i("ALERT_SMTP_PORT", 587)
ALERT_SMTP_USER = _s("ALERT_SMTP_USER")
ALERT_SMTP_PASS = _s("ALERT_SMTP_PASS")
ALERT_STARTTLS = _s("ALERT_STARTTLS", "1") == "1"
ALERT_COOLDOWN_HOURS = _i("ALERT_COOLDOWN_HOURS", 6)

# Webhooks (job-finished callback). Leave WEBHOOK_SECRET empty to disable.
WEBHOOK_SECRET = _s("WEBHOOK_SECRET")
WEBHOOK_ALLOWED_HOSTS = [h.strip().lower() for h in _s("WEBHOOK_ALLOWED_HOSTS").split(",") if h.strip()]
WEBHOOK_MAX_ATTEMPTS = _i("WEBHOOK_MAX_ATTEMPTS", 6)
WEBHOOK_ALLOW_LOOPBACK = _s("WEBHOOK_ALLOW_LOOPBACK", "0") == "1"  # development only
BOOTSTRAP_TOKEN_MIN_LENGTH = 16
BOOTSTRAP_TOKEN = _s("BOOTSTRAP_TOKEN")  # one-time setup token for POST /bootstrap; empty = disabled
PUBLIC_BASE_URL = _s("PUBLIC_BASE_URL")  # e.g. https://emailval.client.local
