"""Results CSV in the client's format. Uses made-up addresses only (never commit real client data)."""
import csv
import io
from datetime import datetime, timezone

from app import export, smtpcheck

CLIENT_HEADER = ("email,verdict,reason,description,domain,mx_host,smtp_code,smtp_message,"
                 "catch_all,role,free_provider,disposable,checked_at")
T = datetime(2026, 10, 19, 17, 35, 28, 792000, tzinfo=timezone.utc)


def row(**kw):
    base = dict(email="a@example.org", email_input="a@example.org", domain="example.org", status="done",
                verdict="valid", reason="mailbox_exists", provider="other", mx_host="mx.example.org",
                smtp_status="250 2.1.5", smtp_message="OK", catch_all=False, checked_at=T)
    base.update(kw)
    return base


def test_header_and_line_endings_match_client_file():
    text = export.render_csv([row()], "full")
    assert text.split("\r\n")[0] == CLIENT_HEADER
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")


def test_valid_gmail_row():
    rec = export.record(row(email="x@gmail.com", email_input="x@gmail.com", domain="gmail.com"))
    assert rec["free_provider"] == "yes" and rec["role"] == "no" and rec["disposable"] == "no"
    assert rec["catch_all"] == "no" and rec["checked_at"] == "2026-10-19T17:35:28.792Z"
    assert rec["description"] == "The mail server confirmed this mailbox exists."


def test_blank_fields_like_the_client_file():
    dns = export.record(row(verdict="unknown", reason="dns_error", mx_host=None, smtp_status=None,
                            smtp_message=None, catch_all=None))
    assert dns["mx_host"] == dns["smtp_code"] == dns["smtp_message"] == dns["catch_all"] == ""
    long_ = export.record(row(email_input="a@x.org   b@x.org", reason="syntax_too_long", verdict="invalid",
                              domain="x.org   b@x.org"))
    assert long_["domain"] == "" and long_["role"] == long_["free_provider"] == "no"


def test_role_and_disposable_flags():
    assert export.record(row(email_input="Info@Example.org"))["role"] == "yes"
    assert export.record(row(email_input="sales.kumar415@example.org"))["role"] == "no"
    assert export.record(row(domain="mailinator.com"))["disposable"] == "yes"


def test_original_case_is_kept():
    assert export.record(row(email="nag@leaditgroup.com", email_input="nag@Leaditgroup.com"))["email"] == "nag@Leaditgroup.com"


def test_pending_item():
    rec = export.record(row(status="queued", verdict=None, reason=None, checked_at=None))
    assert rec["verdict"] == "pending" and rec["checked_at"] == "" and rec["reason"] == ""


def test_formula_injection_is_neutralised():
    rec = export.record(row(smtp_message="=HYPERLINK(\"http://evil\")"))
    assert rec["smtp_message"].startswith("'=")


def test_formats():
    assert export.render_csv([row()], "simple").split("\r\n")[0] == "email,verdict,reason,provider,checked_at"
    assert export.render_csv([row()], "extended").split("\r\n")[0] == CLIENT_HEADER + ",provider"


def test_parse_reply_like_the_client_file():
    assert smtpcheck.parse_reply(250, "2.1.5 OK 5a47-abc - gsmtp") == ("250 2.1.5", "OK 5a47-abc - gsmtp")
    gmail = "5.1.1 The email account does not exist. For more information, go to\n5.1.1  https://support.google.com/mail/?p=NoSuchUser x - gsmtp"
    assert smtpcheck.parse_reply(550, gmail) == (
        "550 5.1.1", "The email account does not exist. For more information, go to https://support.google.com/mail/?p=NoSuchUser x - gsmtp")
    assert smtpcheck.parse_reply(554, "This server requires PTR for unauthenticated connections.") == (
        "554", "This server requires PTR for unauthenticated connections.")
    assert smtpcheck.parse_reply(None, "") == ("", "")


def test_classify_cases_seen_in_the_client_file():
    c = smtpcheck.classify
    assert c(554, "This server requires PTR for unauthenticated connections.")[1] == "probe_blocked"
    assert c(550, "5.7.25 Forward-confirmed reverse DNS failed")[1] == "probe_blocked"
    assert c(550, "5.7.1 Service unavailable, Client host [x] blocked using Spamhaus.")[1] == "probe_blocked"
    assert c(550, "5.7.1 <a@b.com>: Recipient address rejected: User email address is marked as invalid.")[1] == "mailbox_not_found"
    assert c(550, "5.1.1 The email account that you tried to reach does not exist.")[1] == "mailbox_not_found"
    # a refusal at the sender or greeting step must never be read as "mailbox does not exist"
    assert c(550, "5.7.1 sender rejected: domain does not exist")[1] == "probe_blocked"
    assert c(554, "5.7.1 connection rejected: user unknown")[1] == "probe_blocked"
