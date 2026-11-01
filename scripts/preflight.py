#!/usr/bin/env python3
"""Port 25 and IP test report. Run on the server before go-live:
   docker compose run --rm api python scripts/preflight.py
"""
import datetime
import pathlib
import socket
import sys

import dns.resolver
import dns.reversename

from app import config
from app.monitor import check_ip

TEST_HOSTS = ["gmail-smtp-in.l.google.com", "outlook-com.olc.protection.outlook.com"]


def port25(ip, host):
    try:
        s = socket.socket()
        s.settimeout(15)
        s.bind((ip, 0))
        s.connect((host, 25))
        banner = s.recv(200).decode(errors="ignore").strip()
        s.close()
        return banner.startswith("220"), banner[:50]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:50]


def ptr(ip):
    try:
        name = str(dns.resolver.resolve(dns.reversename.from_address(ip), "PTR")[0]).rstrip(".")
    except Exception:
        return None, False
    try:
        fwd = [r.to_text() for r in dns.resolver.resolve(name, "A")]
    except Exception:
        fwd = []
    return name, ip in fwd


def main():
    ips = [l.strip() for l in pathlib.Path("config/ips.txt").read_text().splitlines()
           if l.strip() and not l.startswith("#")]
    lines = [f"# Port 25 and IP test report", f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}",
             f"HELO host: {config.HELO_HOST}", "",
             "| IP | Port 25 (Google) | Port 25 (Outlook) | PTR | PTR=HELO | Blacklists |",
             "|---|---|---|---|---|---|"]
    failed = False
    for ip in ips:
        ok1, _ = port25(ip, TEST_HOSTS[0])
        ok2, _ = port25(ip, TEST_HOSTS[1])
        name, fcrdns = ptr(ip)
        listed = check_ip(ip)
        match = bool(name) and name.lower() == config.HELO_HOST.lower() and fcrdns
        row_ok = ok1 and ok2 and match and not listed
        failed |= not row_ok
        lines.append(f"| {ip} | {'PASS' if ok1 else 'FAIL'} | {'PASS' if ok2 else 'FAIL'} | "
                     f"{name or 'none'} | {'PASS' if match else 'FAIL'} | {', '.join(listed) or 'clean'} |")
    report = "\n".join(lines) + "\n"
    print(report)
    pathlib.Path("reports").mkdir(exist_ok=True)
    pathlib.Path("reports/preflight_report.md").write_text(report)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
