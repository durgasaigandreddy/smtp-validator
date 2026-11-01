-- OPTIONAL helper queries. Run in the "validator" database.

-- A) Create an admin API key without the CLI.
-- Use a long random value of your own in place of the text below, then send it
-- as the X-API-Key header. Only its SHA-256 hash is stored.
INSERT INTO api_keys(name, key_hint, key_hash, is_admin)
VALUES ('Admin', right('ev_REPLACE_WITH_A_LONG_RANDOM_STRING', 4),
        encode(sha256('ev_REPLACE_WITH_A_LONG_RANDOM_STRING'::bytea), 'hex'), true);

-- B) Check that all tables exist (expect 10 rows)
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;

-- C) Queue size
SELECT status, count(*) FROM job_items GROUP BY status;

-- D) Latest jobs with progress
SELECT j.id, j.name, j.total, j.created_at,
       count(*) FILTER (WHERE i.status = 'done') AS done
FROM jobs j LEFT JOIN job_items i ON i.job_id = j.id
GROUP BY j.id ORDER BY j.id DESC LIMIT 20;

-- E) Verdicts by provider for one job (change the id)
SELECT provider, verdict, count(*) FROM job_items
WHERE job_id = 1 AND status = 'done' GROUP BY 1, 2 ORDER BY 1, 2;

-- F) IP health
SELECT ip, status, pause_reason, paused_until, blacklisted, last_seen FROM ip_state;

-- G) Today's usage per IP
SELECT ip, count FROM usage_daily WHERE day = current_date AND domain = '*';

-- H) Start over (DELETES ALL DATA, keeps tables)
-- TRUNCATE job_items, jobs, results, domains, probe_log, usage_daily, alerts_sent RESTART IDENTITY CASCADE;
