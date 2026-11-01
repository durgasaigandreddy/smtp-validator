# Webhooks: how a finished job calls you back

Without a webhook a client must poll `GET /v1/jobs/{id}` until `finished` is true. With a webhook the server calls
the client's application once, when the last address of the job is done.

## 1. Turn it on (server)

In `.env` set a long random secret and restart the API and monitor:

```
WEBHOOK_SECRET=<32+ random characters>
WEBHOOK_ALLOWED_HOSTS=        # optional: comma-separated host names the server may call; empty = any non-blocked host
```

Without `WEBHOOK_SECRET`, webhooks are disabled and a request containing `webhook_url` gets **400**.

## 2. Ask for it (client)

Add `webhook_url` to the job request. It works for both ways of creating a job:

```
POST /v1/jobs          {"emails":[...], "name":"march list", "webhook_url":"http://192.168.1.20:9000/hook"}
POST /v1/jobs/upload   form fields:  file=@list.csv   webhook_url=http://192.168.1.20:9000/hook
```

## 3. What happens, step by step

| # | Where | What |
|---|---|---|
| 1 | API, `check_webhook` | Refuses the request with 400 if webhooks are off, the scheme is not http/https, the host is not in the allow-list, or the host resolves to a link-local address or to the server itself (loopback). LAN addresses are allowed. |
| 2 | API, `enqueue` | Saves the URL on the job (`jobs.webhook_url`) together with the addresses. The API returns `202` and is done. |
| 3 | Workers | Check the addresses. Each finished item is marked `done`. |
| 4 | Monitor, `webhook_loop` | Every 30 seconds it looks for jobs that have a URL, have not been delivered, and have **no** item still `queued` or `running`. |
| 5 | `webhook.deliver` | Validates the URL again, builds the JSON body, signs it, and sends a POST (8-second timeout, redirects are **not** followed). |
| 6a | Success (HTTP 2xx) | `jobs.webhook_sent_at` is set. Nothing more is sent. |
| 6b | Failure | `webhook_attempts` increases and the next try is scheduled. After the 6th failed try the server gives up and sends an alert email. The results stay downloadable. |

So the callback arrives up to about 30 seconds after the last address finishes. A job that is waiting for warm-up or daily
limits is not finished, so it is not sent early.

### Retry schedule

| After failed try | Next try in |
|---|---|
| 1 | 2 minutes |
| 2 | 4 minutes |
| 3 | 8 minutes |
| 4 | 16 minutes |
| 5 | 32 minutes |
| 6 | give up, alert email |

Delivery is **at least once**: if your server answered after the 8-second timeout, you may receive the same event twice.
Make the receiver idempotent (for example, ignore a `job_id` you already processed).

## 4. What the receiver gets

```
POST /hook
Content-Type: application/json
X-Timestamp: 1767225600
X-Signature: sha256=3f9a...e1

{"event":"job.finished","job_id":7,"name":"march list","total":1000,
 "verdicts":{"valid":600,"invalid":200,"catch_all":100,"unknown":100},
 "results_url":"https://emailval.client.local/v1/jobs/7/results.csv"}
```

The body holds only counts and a link. To get the per-address results, download `results_url` with your normal
`X-API-Key` header. No personal data travels in the webhook itself.

## 5. Verify the signature (receiver)

The signature is `HMAC-SHA256(WEBHOOK_SECRET, timestamp + "." + raw_body)`, hex-encoded, prefixed with `sha256=`.
Always verify against the **raw bytes** of the body, before parsing JSON, and reject timestamps older than 5 minutes.

Python (the same function is in `examples/webhook_receiver.py`):

```python
import hashlib, hmac, time

def verify(secret, timestamp, body: bytes, signature):
    if abs(time.time() - int(timestamp)) > 300:
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return hmac.compare_digest("sha256=" + mac.hexdigest(), signature or "")
```

Node.js (Express; keep the body raw):

```js
const crypto = require('crypto');
app.post('/hook', express.raw({ type: 'application/json' }), (req, res) => {
  const ts = req.header('X-Timestamp') || '', sig = req.header('X-Signature') || '';
  const mac = 'sha256=' + crypto.createHmac('sha256', process.env.WEBHOOK_SECRET)
                               .update(ts + '.').update(req.body).digest('hex');
  const ok = Math.abs(Date.now() / 1000 - Number(ts)) <= 300 &&
             sig.length === mac.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(mac));
  if (!ok) return res.sendStatus(401);
  const event = JSON.parse(req.body);   // handle event.job_id ...
  res.sendStatus(200);
});
```

Answer `2xx` quickly and do heavy work afterwards, otherwise the server may time out and retry.

## 6. Try it on one machine

1. In `.env`: `WEBHOOK_SECRET=local-test-secret-123456789` and, **for development only**, `WEBHOOK_ALLOW_LOOPBACK=1`. Restart the API and monitor.
2. Start the sample receiver: `WEBHOOK_SECRET=local-test-secret-123456789 python examples/webhook_receiver.py 9000`
   (PowerShell: `$env:WEBHOOK_SECRET="local-test-secret-123456789"; python examples\webhook_receiver.py 9000`).
3. Submit a small job with `"webhook_url":"http://127.0.0.1:9000/hook"`.
4. When the job finishes, the receiver prints the verdict counts.

`GET /v1/jobs/{id}` shows `webhook: {url, delivered_at, attempts}`. In production leave `WEBHOOK_ALLOW_LOOPBACK` at `0`.

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| 400 "webhooks are not enabled on this server" | `WEBHOOK_SECRET` is empty |
| 400 "webhook address is not allowed" | URL points to loopback or a link-local address |
| 400 "webhook host is not in the allow-list" | Host missing from `WEBHOOK_ALLOWED_HOSTS` |
| 400 "webhook host does not resolve" | Typo, or DNS cannot resolve the name from the server |
| Never arrives | Job is not finished yet; receiver blocked by a firewall; check `webhook.attempts` and `docker compose logs monitor` |
| Receiver answers 401 | Different secret on each side, wrong clock (more than 5 minutes off), or the body was parsed and re-serialised before verifying |

## 8. Code map

`app/webhook.py` (validation, signing, delivery) · `app/api.py` (`check_webhook`, `enqueue`, job status) ·
`app/monitor.py` (`webhook_loop`, `send_webhooks`) · `sql/schema.sql` (`jobs.webhook_*` columns) · `examples/webhook_receiver.py`.
