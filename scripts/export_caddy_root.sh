#!/usr/bin/env bash
# TLS_MODE=internal only: export Caddy's private root certificate so client machines and
# applications can trust https://<SITE_ADDRESS>. Install deploy/caddy-root.crt as a trusted root.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt deploy/caddy-root.crt
echo "Wrote deploy/caddy-root.crt"
echo "  Windows: double-click > Install Certificate > Local Machine > Trusted Root Certification Authorities"
echo "  Linux:   sudo cp deploy/caddy-root.crt /usr/local/share/ca-certificates/emailval.crt && sudo update-ca-certificates"
echo "  curl:    curl --cacert deploy/caddy-root.crt https://<SITE_ADDRESS>/healthz"
