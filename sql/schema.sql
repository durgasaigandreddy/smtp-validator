-- Email Validation System: database schema (single source of truth).
-- The application runs this file at startup (it is safe to run again), so you normally do
-- not need to run it yourself. Use it in pgAdmin to prepare or inspect a database by hand:
--   1. sql/create_database.sql   (as the postgres superuser, statements one at a time)
--   2. this file                 (Query Tool connected to the "validator" database)
--   3. sql/grants.sql            (only if you ran step 2 as a different user than "validator")

CREATE TABLE IF NOT EXISTS api_keys(
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT false, active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS audit_log(
  id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
  key_id INT, action TEXT, detail TEXT, client_ip TEXT);

CREATE TABLE IF NOT EXISTS domains(
  domain TEXT PRIMARY KEY, mx TEXT[], provider TEXT, mx_checked_at TIMESTAMPTZ,
  catch_all BOOLEAN, catch_all_checked_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS results(
  email TEXT PRIMARY KEY, domain TEXT, verdict TEXT, reason TEXT, provider TEXT,
  smtp_code INT, checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), checked_by_ip TEXT);

CREATE TABLE IF NOT EXISTS jobs(
  id BIGSERIAL PRIMARY KEY, key_id INT REFERENCES api_keys(id), name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), total INT NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS job_items(
  id BIGSERIAL PRIMARY KEY, job_id BIGINT REFERENCES jobs(id) ON DELETE CASCADE,
  email TEXT NOT NULL, domain TEXT, status TEXT NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0, not_before TIMESTAMPTZ NOT NULL DEFAULT now(),
  claimed_at TIMESTAMPTZ, verdict TEXT, reason TEXT, provider TEXT, finished_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS job_items_queue ON job_items(status, not_before, id);
CREATE INDEX IF NOT EXISTS job_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS job_items_ready ON job_items(id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS job_items_finished ON job_items(finished_at);

CREATE TABLE IF NOT EXISTS ip_state(
  ip TEXT PRIMARY KEY, added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'active', paused_until TIMESTAMPTZ, pause_reason TEXT,
  blacklisted TEXT[] NOT NULL DEFAULT '{}', last_blacklist_check TIMESTAMPTZ,
  last_seen TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS usage_daily(
  day DATE, ip TEXT, domain TEXT, count INT NOT NULL DEFAULT 0,
  PRIMARY KEY(day, ip, domain));

CREATE TABLE IF NOT EXISTS probe_log(
  id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ip TEXT, domain TEXT, outcome TEXT);
CREATE INDEX IF NOT EXISTS probe_log_ip_at ON probe_log(ip, at);

CREATE TABLE IF NOT EXISTS alerts_sent(key TEXT PRIMARY KEY, at TIMESTAMPTZ NOT NULL);

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS webhook_url TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS webhook_sent_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS webhook_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS webhook_next_at TIMESTAMPTZ;
