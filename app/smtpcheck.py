import re
import smtplib
import socket

from . import config

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
EMAIL_SQL_RE = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"

BLOCK_WORDS = ("spamhaus", "blocked", "blacklist", "block list", "denied", "banned", "reputation",
               "rbl", "not allowed", "reverse dns", "rdns", "no smtp service", "not authorized", "not authorised")
PTR_RE = re.compile(r"\bptr\b")
# Phrases that mean "this mailbox does not exist", even when the code is a 5.7.x policy code
INVALID_PHRASES = ("user unknown", "unknown user", "no such user", "no such recipient", "does not exist",
                   "doesn't exist", "doesn\u2019t exist", "invalid recipient", "recipient not found", "marked as invalid",
                   "mailbox not found", "mailbox unavailable", "unknown recipient", "recipient unknown",
                   "user not found", "no mailbox")
# Added by rcpt_probe when the refusal happened before the RCPT step (so it says nothing about the mailbox)
STAGE_MARKS = ("sender rejected:", "connection rejected:")
ENHANCED_RE = re.compile(r"^\s*([245]\.\d{1,3}\.\d{1,3})\s*")

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


def parse_reply(code, msg):
    """Split a server reply into ("250 2.1.5", "OK ...") like the results CSV: the SMTP code plus the
    enhanced status code, and the remaining text on one line."""
    first, parts = "", []
    for line in (msg or "").replace("\r", "").split("\n"):
        if not line.strip():
            continue
        m = ENHANCED_RE.match(line)
        if m:
            first = first or m.group(1)
            line = line[m.end():]
        parts.append(line.strip())
    text = " ".join(" ".join(parts).split())[:500]
    return (f"{code} {first}".strip() if code else ""), text


def classify(code, msg):
    """Returns (verdict, reason, outcome). Reasons use the client's vocabulary. outcome feeds the
    block-rate monitor."""
    low = msg.lower()
    if code in (250, 251):
        return "valid", "mailbox_exists", "ok"
    stage = any(m in low for m in STAGE_MARKS)
    if not stage and 500 <= code < 600 and any(p in low for p in INVALID_PHRASES):
        return "invalid", "mailbox_not_found", "ok"
    if stage or any(w in low for w in BLOCK_WORDS) or PTR_RE.search(low) or "5.7." in low:
        return "unknown", "probe_blocked", "blocked"
    if 400 <= code < 500:
        return "unknown", "temporary_failure", "temp"
    if code == 552:
        return "unknown", "mailbox_full", "ok"
    if code in (550, 551, 553):
        return "invalid", "mailbox_not_found", "ok"
    return "unknown", "smtp_error", "ok"
