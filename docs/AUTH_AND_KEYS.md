# API keys and the setup token: how they work

Three different secrets exist. They are easy to confuse, so here they are side by side.

| Secret | Header / setting | Who holds it | Purpose | Lifetime |
|---|---|---|---|---|
| **API key** | `X-API-Key` header | Client applications and administrators | Authenticates every API call | Until revoked |
| **Setup token** | `BOOTSTRAP_TOKEN` in `.env`, sent as `X-Setup-Token` | Whoever installs the server | Creates the **first** admin key, once | Remove it after use |
| **Webhook secret** | `WEBHOOK_SECRET` in `.env` | Server and the client's receiver | Signs webhook calls (see `WEBHOOKS.md`) | Until rotated |

## 1. How an API key works

- A key looks like `ev_` followed by 43 random characters. The server generates it with Python's `secrets` module.
- The key is **shown once**, when it is created. The database stores only its SHA-256 hash (`api_keys.key_hash`), so a copy of the database does not reveal any key.
- Every request goes through `require_key` (`app/auth.py`): it reads `X-API-Key`, hashes it, and looks for an **active** row with that hash. No match gives **401**.
- A key is either a **client key** (can create and read its own jobs) or an **admin key** (`is_admin = true`; can also use `/admin/*`). An admin route called with a client key gives **403**.
- Every call is written to `audit_log` (key id, action, caller address). Failed logins are logged too.

- The last 4 characters of a key are kept as `key_hint`, so screens can say "key ending a91f". That reveals nothing useful (4 of 43 random characters). Keys created before this was added have no hint.
- `GET /v1/me` returns `{id, name, is_admin, key_hint}` for the key you send. A sign-in page calls it to check the key and to decide between the user and admin screen; a successful call is audited as `sign_in`.

## 2. The chicken-and-egg problem and the setup token

Creating keys needs an admin key, but a fresh server has none. The setup token solves this exactly once.

```
 .env: BOOTSTRAP_TOKEN=<16+ random characters>
          |
          v
 POST /bootstrap   header  X-Setup-Token: <the same value>
          |
          |  server checks, in order:
          |   1. BOOTSTRAP_TOKEN is set          (else 404: the route "does not exist")
          |   2. it is at least 16 characters    (else 503)
          |   3. the header matches it           (constant-time compare; else 401, and it is audited)
          |   4. no active admin key exists yet  (else 409)  <- checked inside a database lock,
          v                                                     so two calls cannot both succeed
 201  { "api_key": "ev_..." }   <- the first admin key, shown once
```

Steps:

1. Generate a token, for example in PowerShell: `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | % {[char]$_})`
   or on Linux: `openssl rand -hex 24`.
2. Put it in `.env` as `BOOTSTRAP_TOKEN=...` and restart the API (`docker compose up -d api`).
3. Call the endpoint (from the LAN or VPN; Caddy refuses `/bootstrap` from the internet):
   ```
   curl -X POST https://HOST/bootstrap -H "X-Setup-Token: <token>" \
        -H "Content-Type: application/json" -d '{"name":"First admin"}'
   ```
   PowerShell on a development PC: `.\scripts\windows\bootstrap.ps1`
4. Store the returned `api_key` safely (password manager).
5. **Delete `BOOTSTRAP_TOKEN` from `.env`** and restart the API. The route then returns 404 again.

If every admin key is lost, create a new one on the server with
`docker compose run --rm api python -m app.cli create-key "Admin" --admin`, or with the SQL in
`sql/admin_key_and_checks.sql`. Both need access to the server or database, which is the point.

## 3. Day-to-day key management (admin key required)

| Task | Request |
|---|---|
| Create a client key | `POST /admin/keys` with `{"name":"Client app","admin":false}` |
| Create another admin | `POST /admin/keys` with `{"name":"Second admin","admin":true}` |
| List keys (never shows the keys themselves) | `GET /admin/keys` |
| Revoke a key | `DELETE /admin/keys/{id}` (you cannot revoke the key you are using) |
| Review activity | `GET /admin/audit?limit=100` |

```
curl -X POST https://HOST/admin/keys -H "X-API-Key: $ADMIN_KEY" \
     -H "Content-Type: application/json" -d '{"name":"Client app","admin":false}'
```

**Rotating a client key:** create a new key, give it to the client, wait until they switch, then revoke the old one by id.

## 4. Where this lives in the code

| Piece | File |
|---|---|
| Key generation, hashing, `require_key`, `require_admin`, audit | `app/auth.py` |
| `/bootstrap`, `/admin/keys` (create, list, revoke), `/admin/audit` | `app/api.py` |
| Command-line alternative | `app/cli.py` (`create-key`, `list-keys`, `revoke-key`) |
| Setup token setting and minimum length | `app/config.py` |
| Table | `api_keys` in `sql/schema.sql` |

## 5. Security notes

- The key travels in a header, never in a URL, so it stays out of browser history and server logs. Caddy is configured to
  **remove `X-Api-Key` and `X-Setup-Token` from its access log** (it only hides `Authorization` and `Cookie` by default).
- `/admin/*` and `/bootstrap` are refused by Caddy for any caller outside the private network ranges (LAN, VPN).
- Use HTTPS only. Anyone who sees a key in transit can use it.
- There is no rate limiting on failed logins yet. Keep the API on the LAN or VPN.
