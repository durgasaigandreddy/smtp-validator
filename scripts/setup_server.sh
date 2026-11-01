#!/usr/bin/env bash
# One-time hardening of the client's on-prem server (Ubuntu 22.04/24.04). Run as root.
#   MGMT_CIDR=192.168.1.0/24 API_ALLOW_CIDR=192.168.1.0/24 ./scripts/setup_server.sh
#   Add PUBLIC_HTTPS=1 when TLS_MODE=public (internet-facing HTTPS).
set -euo pipefail
: "${MGMT_CIDR:?set MGMT_CIDR (who may SSH in, e.g. the office LAN or VPN subnet)}"
: "${API_ALLOW_CIDR:?set API_ALLOW_CIDR (who may call the API)}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Safety: the firewall reset below would cut off an SSH session from outside MGMT_CIDR.
if [ -n "${SSH_CLIENT:-}" ] && [ "${FORCE:-0}" != "1" ]; then
  python3 - "$MGMT_CIDR" "${SSH_CLIENT%% *}" <<'PY' || { echo "Your SSH address ${SSH_CLIENT%% *} is outside MGMT_CIDR=$MGMT_CIDR; you would be locked out. Fix MGMT_CIDR (or set FORCE=1)." >&2; exit 1; }
import ipaddress, sys
sys.exit(0 if ipaddress.ip_address(sys.argv[2]) in ipaddress.ip_network(sys.argv[1], strict=False) else 1)
PY
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker.io ufw fail2ban unattended-upgrades wireguard unbound rsync
# The Compose plugin has a different package name depending on the Ubuntu release.
docker compose version >/dev/null 2>&1 || apt-get install -y docker-compose-v2 \
  || apt-get install -y docker-compose-plugin || true
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is missing. Install it (see docs.docker.com/compose/install/linux) and re-run." >&2; exit 1; }
systemctl enable --now docker fail2ban unbound

# Local recursive resolver: DNSBLs such as Spamhaus refuse big public resolvers.
mkdir -p /etc/systemd/resolved.conf.d
printf '[Resolve]\nDNS=127.0.0.1\nFallbackDNS=\nDomains=~.\n' > /etc/systemd/resolved.conf.d/local.conf
systemctl restart systemd-resolved

# Firewall: inbound closed except SSH (mgmt), API (allowed LAN/VPN) and WireGuard.
# Outbound stays open: workers need port 25 out.
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$MGMT_CIDR" to any port 22 proto tcp
if [ "${PUBLIC_HTTPS:-0}" = "1" ]; then       # TLS_MODE=public: the internet must reach Caddy
  ufw allow 80/tcp
  ufw allow 443/tcp
else
  ufw allow from "$API_ALLOW_CIDR" to any port 80 proto tcp
  ufw allow from "$API_ALLOW_CIDR" to any port 443 proto tcp
fi
ufw allow 51820/udp
ufw --force enable

# Automatic security updates
dpkg-reconfigure -f noninteractive unattended-upgrades

# Daily backup at 02:00
echo "0 2 * * * root $APP_DIR/scripts/backup.sh >> /var/log/emailval-backup.log 2>&1" > /etc/cron.d/emailval-backup

echo "Done. Next: configure the public IPs (netplan), WireGuard (docs/RUNBOOK.md), edit .env (SITE_ADDRESS, TLS_MODE) and run scripts/deploy.sh"
