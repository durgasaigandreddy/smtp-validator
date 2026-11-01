"""Signed job-finished webhooks.

Request headers:  X-Timestamp: <unix seconds>
                  X-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>" with WEBHOOK_SECRET>
The receiver should recompute the signature and reject old timestamps (e.g. > 5 minutes).
"""
import hashlib
import hmac
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import config


class WebhookError(ValueError):
    pass


def validate_url(url):
    if not config.WEBHOOK_SECRET:
        raise WebhookError("webhooks are not enabled on this server")
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise WebhookError("webhook_url must be an http(s) URL with a host")
    host = u.hostname.lower()
    if config.WEBHOOK_ALLOWED_HOSTS and host not in config.WEBHOOK_ALLOWED_HOSTS:
        raise WebhookError("webhook host is not in the allow-list")
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise WebhookError("webhook host does not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # LAN addresses are allowed (the client's app is usually on the LAN);
        # this server itself and link-local/metadata addresses are not.
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise WebhookError("webhook address is not allowed")
        if ip.is_loopback and not config.WEBHOOK_ALLOW_LOOPBACK:
            raise WebhookError("webhook address is not allowed")
    return url


def sign(body: bytes, timestamp: str) -> str:
    mac = hmac.new(config.WEBHOOK_SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def deliver(url, payload):
    """POST payload as JSON. Returns (ok, info)."""
    try:
        validate_url(url)
        body = json.dumps(payload, default=str).encode()
        ts = str(int(time.time()))
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", "X-Timestamp": ts,
            "X-Signature": sign(body, ts), "User-Agent": "emailval-webhook/1"})
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=8) as r:
            return 200 <= r.status < 300, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:200]
