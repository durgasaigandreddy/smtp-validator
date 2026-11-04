# Results CSV format

`GET /v1/jobs/{id}/results.csv` returns the same 13 columns, in the same order, with the same wording as the client's
existing validation export. Checked against a real client file of 95 rows: re-creating it from the stored data gives
**the identical file, byte for byte**, and every recorded server reply gets the same reason.

| `?format=` | Columns |
|---|---|
| `full` (default) | the 13 columns below |
| `extended` | the 13 columns plus `provider` (mail provider group, for example google or microsoft) |
| `simple` | `email, verdict, reason, provider, checked_at` |

CSV details: UTF-8, comma separated, Windows line endings (CRLF), fields quoted only when needed, one row per address,
in the order the addresses were submitted. (The client's file lists rows in the order they finished.)

## Columns

| Column | Meaning |
|---|---|
| `email` | The address as it was submitted (original upper and lower case kept). |
| `verdict` | `valid`, `invalid`, `catch_all`, `unknown`, or `pending` while it is still being checked. |
| `reason` | Why. See the table below. |
| `description` | One plain-language sentence for the reason. |
| `domain` | Part after the @. Blank when the address is not valid in form. |
| `mx_host` | The mail server that answered. Blank when no server was contacted. |
| `smtp_code` | The server's reply code, with the enhanced status code when it gave one, for example `250 2.1.5` or `554`. |
| `smtp_message` | The server's own reply text, on one line. |
| `catch_all` | `yes` (domain accepts every address), `no` (domain was tested and rejects made-up addresses), blank (not tested or no clear answer). |
| `role` | `yes` for role addresses such as info@, admin@, sales@, support@. |
| `free_provider` | `yes` for free mailbox providers such as gmail.com or outlook.com. |
| `disposable` | `yes` for throw-away email domains. |
| `checked_at` | When it was checked: UTC, milliseconds, trailing Z, for example `2026-10-19T17:35:28.792Z`. |

## Reasons

| Verdict | Reason | Seen in client file | Meaning |
|---|---|---|---|
| valid | `mailbox_exists` | yes | The mail server confirmed this mailbox exists. |
| catch_all | `catch_all` | yes | The domain accepts mail for any address. |
| invalid | `mailbox_not_found` | yes | The mail server says this mailbox doesn't exist. |
| invalid | `syntax_too_long` | yes | Longer than email allows (254 characters, or 64 before the @). |
| invalid | `syntax_invalid` | no, our addition | Not a valid email format. |
| invalid | `no_mail_server` | no, our addition | The domain has no mail server. |
| unknown | `probe_blocked` | yes | The server refused our check (anti-spam, blacklist, reverse DNS or policy). |
| unknown | `dns_error` | yes | The DNS lookup failed or timed out. |
| unknown | `timeout` | no, our addition | The server did not answer in time. |
| unknown | `connection_failed` | no, our addition | Could not connect to the server. |
| unknown | `temporary_failure` | no, our addition | The server asked us to try later (for example greylisting). |
| unknown | `mailbox_full` | no, our addition | The mailbox is full. |
| unknown | `smtp_error` | no, our addition | An unexpected answer; see `smtp_code` and `smtp_message`. |

Retries: temporary results (`temporary_failure`, `timeout`, `connection_failed`, `dns_error`, `probe_blocked`) are tried
up to 3 times, 30 minutes apart, before the row is finalised as `unknown`. Only clear results (valid, invalid, catch_all)
are stored and reused for 30 days.

## Differences from the client's current export

- The `role`, `free_provider` and `disposable` columns come from built-in lists. The client's definitions are unknown, so
  compare on a larger sample. The disposable list is short: paste an open-source list into `config/disposable_domains.txt`.
- Rows are in submission order, not completion order.
- A domain already known to accept everything is answered without a new check. Its `smtp_code` is `250` and the message
  says it is a known result.
- `smtp_message` is shortened to 500 characters, and values starting with `=`, `+`, `-` or `@` get a leading apostrophe so
  spreadsheets do not run them as formulas.

## Questions for the client
1. Is the list of reasons complete? Their sample shows 6; we added 7 in the same style.
2. How do they define role, free provider and disposable?
3. Is `provider` (google, microsoft ...) wanted as an extra column? It is available as `?format=extended`.
4. Should rows stay in submission order?
