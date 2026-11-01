import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config
from .db import q

log = logging.getLogger("alerts")


def send(subject, body):
    if not (config.ALERT_TO and config.ALERT_SMTP_HOST):
        log.warning("ALERT (no SMTP configured): %s | %s", subject, body)
        return
    msg = EmailMessage()
    msg["From"] = config.ALERT_FROM or config.MAIL_FROM
    msg["To"] = config.ALERT_TO
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=20) as s:
            if config.ALERT_STARTTLS:
                s.starttls(context=ssl.create_default_context())
            if config.ALERT_SMTP_USER:
                s.login(config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS)
            s.send_message(msg)
    except Exception:
        log.exception("alert email failed")


def alert_once(key, subject, body):
    """Send at most one alert per key per cooldown window."""
    row = q("""INSERT INTO alerts_sent(key, at) VALUES (%s, now())
               ON CONFLICT (key) DO UPDATE SET at = now()
               WHERE alerts_sent.at < now() - make_interval(hours => %s::int)
               RETURNING key""", (key, config.ALERT_COOLDOWN_HOURS), one=True)
    if row:
        send(subject, body)
