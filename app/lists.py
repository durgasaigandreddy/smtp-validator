"""Small built-in lists for the role / free_provider / disposable columns.

Extend the disposable list without code changes: one domain per line in config/disposable_domains.txt
(set DISPOSABLE_FILE to use another path). Open-source lists with thousands of domains work well.
"""
import os
from pathlib import Path

ROLE_LOCALPARTS = frozenset("""
abuse accounts accounting admin administrator billing bookings careers contact customerservice deliveries
dev devops enquiries enquiry feedback finance helpdesk hello help hr info it jobs legal mail mailer-daemon
marketing media noreply no-reply nobody office orders payments postmaster press privacy recruitment
registrar root sales security service services spam staff support team tech webmaster
""".split())

FREE_PROVIDERS = frozenset("""
gmail.com googlemail.com yahoo.com yahoo.co.in yahoo.co.uk yahoo.in ymail.com rocketmail.com outlook.com
hotmail.com hotmail.co.uk live.com live.in msn.com aol.com icloud.com me.com mac.com proton.me protonmail.com
pm.me zoho.com zohomail.in gmx.com gmx.net mail.com yandex.com yandex.ru rediffmail.com
""".split())

_BUILTIN_DISPOSABLE = frozenset("""
mailinator.com guerrillamail.com guerrillamail.net sharklasers.com grr.la 10minutemail.com 10minutemail.net
tempmail.com temp-mail.org temp-mail.io tempail.com yopmail.com yopmail.fr trashmail.com trashmail.net
getnada.com nada.email dispostable.com maildrop.cc throwawaymail.com fakeinbox.com mintemail.com
mohmal.com emailondeck.com mailnesia.com spamgourmet.com tempinbox.com moakt.com burnermail.io
""".split())


def _load_extra():
    path = Path(os.environ.get("DISPOSABLE_FILE", "config/disposable_domains.txt"))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(l.strip().lower() for l in lines if l.strip() and not l.lstrip().startswith("#"))


DISPOSABLE = _BUILTIN_DISPOSABLE | _load_extra()


def is_role(email):
    local = email.split("@", 1)[0].strip().lower().split("+", 1)[0]
    return local in ROLE_LOCALPARTS


def is_free(domain):
    return (domain or "").strip().lower() in FREE_PROVIDERS


def is_disposable(domain):
    return (domain or "").strip().lower() in DISPOSABLE
