import re
import smtplib
import socket

from . import config

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
EMAIL_SQL_RE = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

BLOCK_WORDS = ("spamhaus", "blocked", "blacklist", "block list", "denied", "banned",
               "reputation", "rbl", "not allowed", "poor reputation")

PROVIDERS = (
    ("protection.outlook", "microsoft"), ("outlook", "microsoft"), ("hotmail", "microsoft"),
    ("google", "google"), ("yahoo", "yahoo"), ("zoho", "zoho"),
    ("mimecast", "mimecast"), ("pphosted", "proofpoint"),
    ("secureserver", "godaddy"), ("barracuda", "barracuda"),
)


class ProbeError(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind  # "timeout" | "connect"


def dnsbl_name(ip, zone):
    return ".".join(reversed(ip.split("."))) + "." + zone


def provider_of(mx_hosts):
    h = " ".join(mx_hosts or []).lower()
    for needle, name in PROVIDERS:
        if needle in h:
            return name
    return "other"


def resolve_mx(domain):
    """Returns (mx_list, error). error in None|nxdomain|no_mx|dns_error."""
    import dns.resolver
    try:
        ans = dns.resolver.resolve(domain, "MX", lifetime=10)
        hosts = [str(r.exchange).rstrip(".") for r in sorted(ans, key=lambda r: r.preference)]
        hosts = [h for h in hosts if h]  # null MX ("."): no mail accepted
        return (hosts, None) if hosts else ([], "no_mx")
    except dns.resolver.NXDOMAIN:
        return [], "nxdomain"
    except dns.resolver.NoAnswer:
        try:
            dns.resolver.resolve(domain, "A", lifetime=10)
            return [domain], None  # implicit MX
        except Exception:
            return [], "no_mx"
    except Exception:
        return [], "dns_error"


def _text(msg):
    return msg.decode(errors="ignore") if isinstance(msg, bytes) else str(msg)


def rcpt_probe(address, mx_host, source_ip, port=25):
    """Ask the MX whether it would accept `address`. No mail is ever sent."""
    s = smtplib.SMTP(local_hostname=config.HELO_HOST, timeout=config.SMTP_TIMEOUT,
                     source_address=(source_ip, 0))
    try:
        code, msg = s.connect(mx_host, port)
        if code != 220:
            # Refused at the greeting: that is about our IP, not about the address.
            return code, ("5.7.1 connection rejected: " if code >= 500 else "") + _text(msg)
        s.ehlo()
        code, msg = s.mail(config.MAIL_FROM)
        if code >= 500:
            # Our sender address was refused: also not a verdict on the recipient.
            return code, "5.7.1 sender rejected: " + _text(msg)
        if code >= 400:
            return code, _text(msg)
        code, msg = s.rcpt(address)
        return code, _text(msg)
    except (socket.timeout, TimeoutError) as e:
        raise ProbeError("timeout") from e
    except (smtplib.SMTPException, OSError) as e:
        raise ProbeError("connect") from e
    finally:
        try:
            s.quit()
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass


def classify(code, msg):
    """Returns (verdict, reason, outcome). outcome feeds the block-rate monitor."""
    low = msg.lower()
    if code in (250, 251):
        return "valid", "", "ok"
    if any(w in low for w in BLOCK_WORDS) or "5.7." in low:
        return "unknown", "blocked", "blocked"
    if 400 <= code < 500:
        return "unknown", "temporary_or_greylisted", "temp"
    if code == 552:
        return "unknown", "mailbox_full", "ok"
    if code in (550, 551, 553):
        return "invalid", "mailbox_rejected", "ok"
    return "unknown", f"smtp_{code}", "ok"
