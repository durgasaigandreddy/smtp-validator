"""Webhook end to end without a database: server-side deliver() -> example receiver verify()."""
import threading
import time
from http.server import HTTPServer

from app import config, webhook
from examples import webhook_receiver as rx


def _run_receiver(secret, sink):
    srv = HTTPServer(("127.0.0.1", 0), rx.make_handler(secret, on_event=sink.append))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_signed_delivery_is_accepted_by_receiver():
    config.WEBHOOK_SECRET, config.WEBHOOK_ALLOW_LOOPBACK = "s3cret-value", True
    got = []
    srv = _run_receiver("s3cret-value", got)
    try:
        ok, info = webhook.deliver(f"http://127.0.0.1:{srv.server_address[1]}/hook",
                                   {"event": "job.finished", "job_id": 7, "verdicts": {"valid": 1}})
    finally:
        srv.shutdown()
        config.WEBHOOK_ALLOW_LOOPBACK = False
    assert ok and info == "HTTP 200" and got[0]["job_id"] == 7


def test_wrong_secret_is_rejected_by_receiver():
    config.WEBHOOK_SECRET, config.WEBHOOK_ALLOW_LOOPBACK = "server-secret", True
    got = []
    srv = _run_receiver("a-different-secret", got)
    try:
        ok, info = webhook.deliver(f"http://127.0.0.1:{srv.server_address[1]}/hook", {"job_id": 1})
    finally:
        srv.shutdown()
        config.WEBHOOK_ALLOW_LOOPBACK = False
    assert not ok and info == "HTTP 401" and got == []


def test_receiver_rejects_tampered_and_stale_calls():
    config.WEBHOOK_SECRET = "k" * 20
    body, ts = b'{"job_id":1}', str(int(time.time()))
    sig = webhook.sign(body, ts)
    assert rx.verify("k" * 20, ts, body, sig)
    assert not rx.verify("k" * 20, ts, b'{"job_id":2}', sig)                       # tampered body
    old = str(int(time.time()) - 3600)
    assert not rx.verify("k" * 20, old, body, webhook.sign(body, old))             # replayed / stale
    assert not rx.verify("k" * 20, "not-a-number", body, sig)
    assert not rx.verify("k" * 20, ts, body, "")


def test_loopback_refused_by_default_but_lan_allowed():
    config.WEBHOOK_SECRET, config.WEBHOOK_ALLOW_LOOPBACK = "x" * 20, False
    config.WEBHOOK_ALLOWED_HOSTS = []
    for bad in ("http://127.0.0.1:9000/h", "http://169.254.169.254/h", "ftp://x/h"):
        try:
            webhook.validate_url(bad)
            raise AssertionError(f"{bad} should have been refused")
        except webhook.WebhookError:
            pass
    assert webhook.validate_url("http://192.168.1.20:9000/h")
