from datetime import datetime, timedelta, timezone

from app import config, smtpcheck, warmup


def test_warmup_start_and_end():
    now = datetime.now(timezone.utc)
    assert warmup.daily_limit(now, now) == config.WARMUP_START
    assert warmup.daily_limit(now - timedelta(days=config.WARMUP_DAYS), now) == config.IP_DAILY_MAX


def test_warmup_monotonic():
    now = datetime.now(timezone.utc)
    vals = [warmup.daily_limit(now - timedelta(days=d), now) for d in range(0, 70)]
    assert vals == sorted(vals)


def test_classify():
    assert smtpcheck.classify(250, "2.1.5 OK")[0] == "valid"
    assert smtpcheck.classify(550, "5.1.1 user unknown")[:2] == ("invalid", "mailbox_not_found")
    assert smtpcheck.classify(550, "5.7.1 blocked using Spamhaus")[1:] == ("probe_blocked", "blocked")
    assert smtpcheck.classify(451, "try later")[1:] == ("temporary_failure", "temp")
    assert smtpcheck.classify(552, "mailbox full")[1] == "mailbox_full"


def test_provider():
    assert smtpcheck.provider_of(["aspmx.l.google.com"]) == "google"
    assert smtpcheck.provider_of(["x.mail.protection.outlook.com"]) == "microsoft"
    assert smtpcheck.provider_of(["mail.example.in"]) == "other"


def test_syntax():
    assert smtpcheck.EMAIL_RE.match("a.b+c@example.co.in")
    assert not smtpcheck.EMAIL_RE.match("no-at-sign.com")
    assert not smtpcheck.EMAIL_RE.match("a@b")


def test_dnsbl_name():
    assert smtpcheck.dnsbl_name("1.2.3.4", "zen.spamhaus.org") == "4.3.2.1.zen.spamhaus.org"


def test_webhook_signature_and_validation(monkeypatch):
    import pytest
    from app import webhook
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cret")
    a = webhook.sign(b'{"a":1}', "1700000000")
    assert a == webhook.sign(b'{"a":1}', "1700000000") and a.startswith("sha256=")
    assert a != webhook.sign(b'{"a":2}', "1700000000")
    for bad in ("ftp://example.com/x", "http://127.0.0.1/x", "http://169.254.169.254/x", "notaurl"):
        with pytest.raises(webhook.WebhookError):
            webhook.validate_url(bad)
    assert webhook.validate_url("http://192.168.1.20:9000/hook")  # LAN is allowed
    monkeypatch.setattr(config, "WEBHOOK_ALLOWED_HOSTS", ["app.client.in"])
    with pytest.raises(webhook.WebhookError):
        webhook.validate_url("http://192.168.1.20/hook")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    with pytest.raises(webhook.WebhookError):
        webhook.validate_url("http://192.168.1.20/hook")
