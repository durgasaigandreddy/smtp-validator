#!/usr/bin/env python3
"""Minimal webhook receiver for the Email Validation API (standard library only).

Run it on the machine that should be called back:
    WEBHOOK_SECRET=<same secret as the server> python examples/webhook_receiver.py 9000
Then create a job with  "webhook_url": "http://<this machine's LAN IP>:9000/hook"

It checks the signature and the timestamp, and answers 200 only for genuine calls.
"""
import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

MAX_AGE_SECONDS = 300


def verify(secret, timestamp, body, signature):
    """True only if `signature` matches HMAC-SHA256(secret, timestamp + "." + body) and is fresh."""
    try:
        if abs(time.time() - int(timestamp)) > MAX_AGE_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature or "")


def make_handler(secret, on_event=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if not verify(secret, self.headers.get("X-Timestamp", ""), body,
                          self.headers.get("X-Signature", "")):
                self.send_response(401)
                self.end_headers()
                return
            event = json.loads(body)
            if on_event:
                on_event(event)
            else:
                print(f"job {event['job_id']} finished: {event['verdicts']}")
                print(f"download: {event['results_url']}  (send your X-API-Key header)")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    return Handler


if __name__ == "__main__":
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        sys.exit("Set WEBHOOK_SECRET to the same value as on the server")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    print(f"Listening on 0.0.0.0:{port} ...")
    HTTPServer(("0.0.0.0", port), make_handler(secret)).serve_forever()
