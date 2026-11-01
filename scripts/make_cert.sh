#!/usr/bin/env bash
# Self-signed certificate for TLS_MODE=custom (tests, or when no CA is available).
#   ./scripts/make_cert.sh emailval.client.local 192.168.1.50
# For a real certificate, copy the client's server.crt (full chain) and server.key into deploy/certs/.
# With TLS_MODE=internal you do not need this script at all.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${1:?usage: make_cert.sh <hostname> [ip]}"
SAN="DNS:${HOST}"
[ -z "${2:-}" ] || SAN="${SAN},IP:${2}"
mkdir -p deploy/certs
openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
  -keyout deploy/certs/server.key -out deploy/certs/server.crt \
  -subj "/CN=${HOST}" -addext "subjectAltName=${SAN}"
chmod 600 deploy/certs/server.key
echo "Certificate written to deploy/certs/ (valid 825 days). Give server.crt to clients that need to trust it."
