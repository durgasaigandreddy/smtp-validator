# Email Validation System (on-premise)

SMTP-based email validation for up to 500,000 checks a month. It asks each recipient's mail server whether it would accept
an address (`RCPT TO`); **no email is ever sent**. Results are `valid`, `invalid`, `catch_all` or `unknown` (with a reason),
tagged by mail provider.

**Highlights:** one worker per public IP, per-IP and per-domain daily limits with slow pacing, automatic IP warm-up,
blacklist and block-rate monitoring with automatic pausing, per-client API keys with an audit log, signed webhooks,
HTTPS with Caddy, daily backups, CSV results.

> **Status:** the pieces that can run without a database or real mail servers are unit-tested (SMTP logic against a fake server,
> warm-up, webhook signing, schema file). The full stack has **not** yet been run end to end. Do a pilot with 20 to 50 addresses
> from a machine where outbound port 25 is open before any large list.

## How it fits together

```
 client app / Postman / curl
          | HTTPS :443
      [ Caddy ]  --  /admin/* and /bootstrap only from LAN/VPN
          | 127.0.0.1:8000
      [ API (FastAPI) ] -- keys, jobs, results, admin, dashboard
          |
      [ Postgres ]  <-- queue, results, limits, audit log
        ^   ^   ^
        |   |   +---- [ monitor ]  block-rate pause, alerts, purge, blacklist + webhook threads
        |   +-------- [ worker_203_0_113_10 ]  one process per public IP (database lock)
        +------------ [ worker_203_0_113_11 ]  ...  --> port 25 --> recipients' mail servers
```

## Project layout

| Path | What |
|---|---|
| `app/` | `api.py` endpoints, `worker.py`, `monitor.py`, `smtpcheck.py` (probe and classify), `warmup.py`, `webhook.py`, `auth.py`, `alerts.py`, `db.py`, `config.py`, `cli.py` |
| `sql/` | `schema.sql` (used by the app), `create_database.sql`, `grants.sql`, `admin_key_and_checks.sql` for pgAdmin |
| `deploy/` | `Caddyfile.internal`, `.public`, `.custom`; `certs/` |
| `scripts/` | `deploy.sh`, `setup_server.sh`, `gen_workers.py`, `preflight.py`, `backup.sh`, `make_cert.sh`, `export_caddy_root.sh`; `windows/*.ps1` for development |
| `examples/` | `webhook_receiver.py` |
| `postman/` | Postman collection |
| `docs/` | `RUNBOOK.md`, `AUTH_AND_KEYS.md`, `WEBHOOKS.md`, `RESULTS_FORMAT.md`, `Handover-Guide.docx` |
| `tests/` | unit tests |

## Quick start: production (Linux server, Docker)

```bash
cp .env.example .env                 # set passwords, HELO_HOST, MAIL_FROM, SITE_ADDRESS, TLS_MODE, BOOTSTRAP_TOKEN
nano config/ips.txt                  # one public IP per line
sudo MGMT_CIDR=192.168.1.0/24 API_ALLOW_CIDR=192.168.1.0/24 ./scripts/setup_server.sh   # once
./scripts/deploy.sh
docker compose run --rm api python scripts/preflight.py      # port 25 and IP test: all rows must PASS
curl -X POST https://HOST/bootstrap -H "X-Setup-Token: $BOOTSTRAP_TOKEN" \
     -H "Content-Type: application/json" -d '{"name":"First admin"}'     # first admin key, shown once
# then delete BOOTSTRAP_TOKEN from .env
```
Full steps, DNS records, VPN, alerts and backups: `docs/RUNBOOK.md`.

## Quick start: development on Windows (PowerShell)

Needs Python 3.10+ and Docker Desktop (for Postgres). Run from the project folder.

```powershell
.\scripts\windows\setup.ps1                              # venv, packages, creates .env
docker compose -f docker-compose.dev.yml up -d           # Postgres on localhost:5432
# edit .env: BOOTSTRAP_TOKEN=<16+ chars>
.\scripts\windows\run-api.ps1                            # http://127.0.0.1:8000/docs  (leave running)
.\scripts\windows\bootstrap.ps1                          # prints the first admin key; then delete BOOTSTRAP_TOKEN
.\scripts\windows\new-key.ps1 -AdminKey ev_... -Name "Client app"
.\scripts\windows\run-worker.ps1 -Ip 192.168.1.50        # second window; your PC's own IP
.\scripts\windows\submit-csv.ps1 -Key ev_client... -File .\sample.csv
.\scripts\windows\job-status.ps1 -Key ev_client... -JobId 1
```
Most home and office networks block outbound port 25: check with
`Test-NetConnection gmail-smtp-in.l.google.com -Port 25`. If it fails, checks end as `unknown` (`connection_failed`/`timeout`).

## Sending IPs: how they get into `ip_state`

The application never picks the machine's own address. An IP exists in `ip_state` only after a **worker for that IP starts**:
the worker is given `SOURCE_IP`, checks that the address really belongs to this machine, binds every check to it, and registers
itself (`INSERT ... ip_state`). One worker per IP, so several IPs means several workers.

| Where | How to list several IPs |
|---|---|
| Production | One IP per line in `config/ips.txt`, then `./scripts/deploy.sh` (it creates one worker container per line) |
| Windows development | `.\scripts\windows\run-workers.ps1` (one window per line of `config\ips.txt`), or `run-worker.ps1 -Ip <ip>` per IP |
| See them | `GET /admin/status`, the admin dashboard, or `SELECT ip, status, last_seen FROM ip_state ORDER BY ip;` |
| Remove one | stop its worker, delete the line from `config/ips.txt`, then `DELETE FROM ip_state WHERE ip = '<ip>';` |

The IPs must be real addresses on the server's network adapter (secondary addresses are fine). Check them with `ip -4 addr`
(Linux) or `Get-NetIPAddress -AddressFamily IPv4` (Windows). Behind NAT, the outside world sees the router's public address
instead of the one you bind, so reputation and reverse DNS apply to that public address.

## HTTPS with Caddy (`TLS_MODE` in `.env`)

| Mode | Use when |
|---|---|
| `internal` (default) | LAN host name or IP. Caddy issues its own certificate; install its root with `./scripts/export_caddy_root.sh`. |
| `public` | Real domain pointing at the server, ports 80 and 443 open. Free Let's Encrypt certificate, renewed automatically. |
| `custom` | The client's own `deploy/certs/server.crt` and `server.key`. |

Caddy removes `X-Api-Key` and `X-Setup-Token` from its access log and refuses `/admin/*` and `/bootstrap` from non-private addresses.

## API

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /healthz` | none | liveness and database check |
| `POST /bootstrap` | `X-Setup-Token` | create the first admin key (once) |
| `GET /v1/me` | key | who the key belongs to: `{id, name, is_admin, key_hint}`; the sign-in page uses `is_admin` to pick the screen |
| `GET /v1/jobs` | key | your jobs, newest first (`?limit=20&offset=0`); admins may add `?all=1` for everyone's |
| `POST /v1/jobs` | key | submit `{"emails":[...],"name":"...","webhook_url":"..."}` |
| `POST /v1/jobs/upload` | key | submit a CSV file (`email` column); optional form field `webhook_url` |
| `GET /v1/jobs/{id}` | key | progress, verdict counts, counts by provider, webhook state |
| `GET /v1/jobs/{id}/results.csv` | key | results CSV in the client's 13-column format; `?format=extended` adds `provider`, `?format=simple` gives 5 columns (see `docs/RESULTS_FORMAT.md`) |
| `GET /v1/result?email=` | key | stored result for one address, same fields as the CSV |
| `GET /admin/status` | admin | queue, IPs, limits, block rates |
| `GET /admin/dashboard` | admin key typed into the page | live status page |
| `POST /admin/ips/{ip}/pause` and `/resume` | admin | stop or resume an IP |
| `POST /admin/keys`, `GET /admin/keys`, `DELETE /admin/keys/{id}` | admin | create, list, revoke keys |
| `GET /admin/audit` | admin | audit log with the key's name and last 4 characters (`key_name`, `key_hint`) |

Send the key as `X-API-Key: ev_...`. Interactive docs at `/docs`. Import `postman/EmailValidation.postman_collection.json`.

**Keys and the setup token:** `docs/AUTH_AND_KEYS.md`. **Webhooks (signing, retries, receiver code):** `docs/WEBHOOKS.md`.

## Configuration (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `HELO_HOST`, `MAIL_FROM` | | identity used in SMTP; HELO must match the IPs' reverse DNS |
| `WARMUP_START`, `IP_DAILY_MAX`, `WARMUP_DAYS` | 50, 1500, 60 | warm-up ramp per IP |
| `PER_DOMAIN_IP_DAILY` | 150 | max checks per recipient domain per IP per day |
| `PACE_MIN`, `PACE_MAX` | 2, 6 | seconds between checks on one IP |
| `REFRESH_DAYS` | 30 | stored results younger than this are reused |
| `BLOCK_RATE_PAUSE`, `PAUSE_HOURS` | 0.30, 6 | auto-pause when this share of the last hour was blocked |
| `DNSBLS` | 4 lists | blacklists checked every 30 minutes |
| `SITE_ADDRESS`, `TLS_MODE`, `API_PORT` | | Caddy and API |
| `BOOTSTRAP_TOKEN` | empty | one-time first-admin setup; remove after use |
| `WEBHOOK_SECRET`, `WEBHOOK_ALLOWED_HOSTS` | empty | enable and restrict webhooks |
| `ALERT_*` | | email alerts (use the client's relay, not the validation IPs) |
| `JOB_RETENTION_DAYS` etc. | 90 / 365 / 730 | data retention |

Capacity: 500,000 a month is about 16,700 a day. At 1,500 per IP per day that needs about 12 IPs, so a /28 block fits.

## Tests

```bash
pip install -r requirements.txt
PYTHONPATH=. pytest tests          # Windows: $env:PYTHONPATH="."; pytest tests
```
Covers SMTP classification against a fake mail server, warm-up, webhook signing and delivery to the example receiver, URL safety, and the schema file.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not import module "main"` | The app is `app.api:app`: `python -m uvicorn app.api:app --port 8000` |
| `database unavailable` at start | Postgres not running or `DATABASE_URL` wrong (special characters in the password must be URL-encoded) |
| `Schema file not found` | The `sql/` folder was not copied or deployed |
| 401 on every call | Missing or wrong `X-API-Key`; keys are shown only once |
| 403 on `/admin/...` through HTTPS | Caller is outside the private network; use the LAN or VPN |
| `Another worker is already running for <ip>` | Two workers for one IP; stop the extra one |
| Every result `unknown` with `connection_failed`/`timeout` | Outbound port 25 blocked by the network or ISP |
| Many `blocked` | IP is blacklisted or too fast; see the dashboard and `docs/RUNBOOK.md` |
| Webhook 400 or never arrives | see the table in `docs/WEBHOOKS.md` |

## Known limitations

- The full stack has not been run end to end; first runs may reveal small errors.
- No rate limit on the API, and failed logins are only audited.
- A worker loses its IP lock silently if the database restarts; restart the workers.
- Validation accuracy depends on what mail servers say; catch-all and unknown results are normal.
- A removed IP keeps its row (and its alerts) until deleted by hand.
- Delivery of webhooks is at least once; receivers should ignore duplicates.
