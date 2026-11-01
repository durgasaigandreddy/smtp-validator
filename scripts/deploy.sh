#!/usr/bin/env bash
# Build and (re)start everything. Run from the project root or anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Create .env from .env.example first"; exit 1; }
TLS_MODE="$(grep -E '^TLS_MODE=' .env | head -n1 | cut -d= -f2- | tr -d '"' || true)"
if [ "${TLS_MODE:-internal}" = "custom" ] && [ ! -f deploy/certs/server.crt ]; then
  echo "TLS_MODE=custom needs deploy/certs/server.crt and server.key (see scripts/make_cert.sh)"; exit 1
fi
python3 scripts/gen_workers.py
F="-f docker-compose.yml -f docker-compose.workers.yml"
docker compose $F build
docker compose $F up -d --remove-orphans
docker compose $F ps
