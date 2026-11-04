# Runbook: Email Validation System (production, on-premise Linux server)

For development on a Windows PC see the README. Webhooks: `WEBHOOKS.md`. Keys and the setup token: `AUTH_AND_KEYS.md`.

## 1. Architecture
- `db` Postgres: results, queue, limits, audit log. Listens on 127.0.0.1 only.
- `api` FastAPI: jobs, results CSV, API keys, webhooks, admin and dashboard. Listens on 127.0.0.1 only.
- `caddy` HTTPS on ports 80 and 443 in front of the API. It is the only inbound service. Admin routes are refused from outside the LAN/VPN.
- `worker_<ip>` one process per public IP; a database lock prevents two workers using the same IP.
- `monitor` block-rate pausing, stuck-item recovery, alerts, retention purge; background threads for blacklist checks (every 30 min) and webhook delivery (every 30 s).
- All containers use host networking so each worker can bind its own public IP.

## 2. Install (about 3 working days once the server and line are ready)
1. Install Ubuntu Server 24.04 LTS. Copy this folder to `/opt/emailval`.
2. Add the public IPs to the server (netplan), for example `/etc/netplan/01-ips.yaml`:
   ```yaml
   network:
     version: 2
     ethernets:
       eno1:
         addresses: [203.0.113.10/28, 203.0.113.11/28, 203.0.113.12/28]
         routes: [{to: default, via: 203.0.113.1}]
   ```
   Apply with `netplan apply`; confirm with `ip -4 addr`.
3. Harden: `MGMT_CIDR=<office/vpn subnet> API_ALLOW_CIDR=<subnet> sudo ./scripts/setup_server.sh`
   (add `PUBLIC_HTTPS=1` only for `TLS_MODE=public`). The script refuses to run if it would lock your SSH session out.
4. DNS (client's DNS provider), for each IP: `A` record for the HELO host; `PTR` (asked of the ISP) equal to the HELO host;
   SPF on the MAIL_FROM domain `v=spf1 ip4:<block> -all`.
5. `cp .env.example .env`; set passwords, `HELO_HOST`, `MAIL_FROM`, `SITE_ADDRESS`, `TLS_MODE`, alert SMTP. List the IPs in `config/ips.txt`.
6. HTTPS mode (`TLS_MODE` in `.env`):
   | Mode | Use when | Needed |
   |---|---|---|
   | `internal` | LAN name or IP | nothing; then run `./scripts/export_caddy_root.sh` and install `deploy/caddy-root.crt` on client machines |
   | `public` | real domain on the internet | DNS to this server, ports 80 and 443 reachable |
   | `custom` | client supplies a certificate | `deploy/certs/server.crt` (full chain) and `server.key` |
7. `./scripts/deploy.sh` (builds the image, generates one worker per IP, starts everything).
8. Go-live gate, the port 25 and IP test: `docker compose run --rm api python scripts/preflight.py`.
   Every row must PASS. The report is saved to `reports/preflight_report.md` and goes to the client.
9. First admin key: set `BOOTSTRAP_TOKEN` (16+ characters) in `.env`, `docker compose up -d api`, call `POST /bootstrap`
   (details in `AUTH_AND_KEYS.md`), store the key, then **remove the token**. Create the client key with `POST /admin/keys`.
   Fallback: `docker compose run --rm api python -m app.cli create-key "Admin" --admin`.
10. Dashboard: `https://<SITE_ADDRESS>/admin/dashboard` (asks for the admin key).

## 3. VPN (WireGuard, for remote support)
Generate keys with `wg genkey | tee priv | wg pubkey > pub`, write `/etc/wireguard/wg0.conf`
(`[Interface] Address=10.8.0.1/24, ListenPort=51820, PrivateKey=...` plus one `[Peer]` for Milarch Tech),
then `systemctl enable --now wg-quick@wg0`. Include `10.8.0.0/24` in `MGMT_CIDR` and `API_ALLOW_CIDR`.
VPN addresses count as private, so Caddy allows `/admin/*` from them.

## 4. Using the API
```
curl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"emails":["a@x.com","b@y.com"],"name":"test"}' https://HOST/v1/jobs
curl -H "X-API-Key: $KEY" https://HOST/v1/jobs/1
curl -H "X-API-Key: $KEY" -o out.csv https://HOST/v1/jobs/1/results.csv
curl -H "X-API-Key: $KEY" -F file=@list.csv https://HOST/v1/jobs/upload
```
With `TLS_MODE=internal` add `--cacert deploy/caddy-root.crt`. Verdicts: `valid`, `invalid`, `catch_all`, `unknown`
(the reason says why: probe_blocked, timeout, temporary_failure, mailbox_full ...; full list in `RESULTS_FORMAT.md`). Interactive docs: `/docs`.
A Postman collection is in `postman/`.

## 5. IP warm-up (first 2 months)
Each IP starts at `WARMUP_START` checks a day and rises geometrically to `IP_DAILY_MAX` over `WARMUP_DAYS`.
Adding an IP later: add it to `config/ips.txt`, run `./scripts/deploy.sh`; its warm-up starts then.
Weekly: send the client the dashboard figures (volume, block rate, blacklists).

## 6. Daily checks
Dashboard: every IP `active` and `alive`, block rate under 30%, queue draining. Alerts arrive by email (6-hour cooldown per type).
Certificate: Caddy renews `internal` and `public` certificates by itself; for `custom` check expiry yearly
(`openssl x509 -in deploy/certs/server.crt -noout -enddate`).

## 7. When an alert fires
| Alert | Action |
|---|---|
| IP blacklisted | IP auto-pauses. Request delisting on the list's site, fix the cause. It resumes by itself when clean. |
| High block rate | IP auto-pauses for 6 h. Find which provider blocks; lower `PER_DOMAIN_IP_DAILY` or `IP_DAILY_MAX`. |
| Worker not running | `docker compose -f docker-compose.yml -f docker-compose.workers.yml logs worker_<ip>`, then `up -d`. |
| "Another worker is already running" in a log | Two workers were started for one IP. Stop the extra one. |
| No active IP | Resume manually: `POST /admin/ips/<ip>/resume`, after finding the cause. |
| Webhook failed | Fix the receiving application; the CSV is still downloadable. |
Manual pause or resume: `POST /admin/ips/<ip>/pause` and `/resume` with an admin key.
A removed IP keeps its row and keeps alerting: `DELETE FROM ip_state WHERE ip = '<ip>';` in `psql`.

## 8. Backup and restore
Daily at 02:00 to `/var/backups/emailval` (14 days). Set `BACKUP_REMOTE` in `.env` to also copy off the server.
Monthly restore test:
```
gunzip -c db-YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER -d postgres -c "CREATE DATABASE restore_test"
gunzip -c db-YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER -d restore_test
```

## 9. Updates
OS security updates are automatic. New software version: copy the files, `./scripts/deploy.sh`. The schema (`sql/schema.sql`) is idempotent and re-applied at start.

## 10. Data and privacy (DPDP Act)
Retention is enforced nightly (`JOB_RETENTION_DAYS`, `RESULT_RETENTION_DAYS`, `AUDIT_RETENTION_DAYS`); agree values in the DPA.
Caddy's access log (`docker compose logs caddy`) contains URLs, including `/v1/result?email=...`; it has no API keys.

## 11. Handover checklist
- [ ] preflight report all PASS
- [ ] DNS A, PTR and SPF verified
- [ ] HTTPS works from the client's application (root certificate installed for `internal`)
- [ ] first admin key created, `BOOTSTRAP_TOKEN` removed, client key issued
- [ ] alert email test received (stop a worker for 6 minutes)
- [ ] backup restored successfully once
- [ ] webhook tested with the client's receiver (if used)
- [ ] client has this runbook
