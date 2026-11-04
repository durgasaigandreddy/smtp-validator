"""Runs rcpt_probe + classify against a tiny fake SMTP server (no network, no database)."""
import socketserver
import threading

from app import smtpcheck


def serve(banner="220 fake ESMTP", mail="250 2.1.0 OK", rcpt=None):
    rcpt = rcpt or {}

    class H(socketserver.StreamRequestHandler):
        def handle(self):
            w = lambda s: self.wfile.write((s + "\r\n").encode())
            w(banner)
            if not banner.startswith("220"):
                return
            for raw in self.rfile:
                cmd = raw.decode().strip()
                up = cmd.upper()
                if up.startswith(("EHLO", "HELO")):
                    w("250 hello")
                elif up.startswith("MAIL"):
                    w(mail)
                elif up.startswith("RCPT"):
                    addr = cmd.split("<", 1)[1].split(">", 1)[0]
                    w(rcpt.get(addr, "550 5.1.1 User unknown"))
                elif up.startswith("QUIT"):
                    w("221 bye")
                    return
                else:
                    w("250 OK")

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def check(srv, address):
    try:
        code, msg = smtpcheck.rcpt_probe(address, "127.0.0.1", "127.0.0.1", port=srv.server_address[1])
    finally:
        srv.shutdown()
    return smtpcheck.classify(code, msg)


def test_existing_and_missing_mailbox():
    s = serve(rcpt={"good@x.in": "250 2.1.5 OK"})
    assert check(s, "good@x.in")[0] == "valid"
    s = serve(rcpt={"good@x.in": "250 2.1.5 OK"})
    assert check(s, "nobody@x.in")[:2] == ("invalid", "mailbox_not_found")


def test_sender_rejection_is_not_an_invalid_mailbox():
    s = serve(mail="550 5.1.7 Bad sender address", rcpt={"good@x.in": "250 OK"})
    verdict, reason, outcome = check(s, "good@x.in")
    assert verdict == "unknown" and outcome == "blocked"


def test_greeting_rejection_counts_as_blocked():
    s = serve(banner="554 No SMTP service here")
    verdict, reason, outcome = check(s, "good@x.in")
    assert verdict == "unknown" and outcome == "blocked"


def test_greeting_busy_is_temporary():
    s = serve(banner="421 Too many connections, try later")
    assert check(s, "good@x.in")[1:] == ("temporary_failure", "temp")


def test_greylisting_is_temporary():
    s = serve(rcpt={"g@x.in": "451 4.7.1 Greylisted, try again later"})
    assert check(s, "g@x.in")[1:] == ("temporary_failure", "temp")


def test_policy_block_on_rcpt():
    s = serve(rcpt={"g@x.in": "550 5.7.1 Client host blocked using Spamhaus"})
    assert check(s, "g@x.in")[1:] == ("probe_blocked", "blocked")
