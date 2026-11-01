#!/usr/bin/env bash
# Daily database backup. Restore test: see docs/RUNBOOK.md
set -euo pipefail
cd "$(dirname "$0")/.."
getenv() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
POSTGRES_USER="$(getenv POSTGRES_USER)"; POSTGRES_DB="$(getenv POSTGRES_DB)"
BACKUP_DIR="${BACKUP_DIR:-$(getenv BACKUP_DIR)}"; BACKUP_REMOTE="${BACKUP_REMOTE:-$(getenv BACKUP_REMOTE)}"
DEST="${BACKUP_DIR:-/var/backups/emailval}"
mkdir -p "$DEST"
FILE="$DEST/db-$(date +%F).sql.gz"
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILE"
[ -s "$FILE" ] || { echo "Backup is empty: $FILE" >&2; exit 1; }
find "$DEST" -name 'db-*.sql.gz' -mtime +14 -delete
[ -z "${BACKUP_REMOTE:-}" ] || rsync -a "$DEST/" "$BACKUP_REMOTE"
echo "Backup ok: $FILE"
