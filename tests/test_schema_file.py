from pathlib import Path

SCHEMA = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text(encoding="utf-8")
TABLES = ["api_keys", "audit_log", "domains", "results", "jobs", "job_items",
          "ip_state", "usage_daily", "probe_log", "alerts_sent"]


def test_all_tables_present_and_idempotent():
    for t in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t}(" in SCHEMA, t
    assert SCHEMA.count("CREATE TABLE") == SCHEMA.count("CREATE TABLE IF NOT EXISTS") == len(TABLES)
    assert SCHEMA.count("CREATE INDEX") == SCHEMA.count("CREATE INDEX IF NOT EXISTS")
    assert "ADD COLUMN IF NOT EXISTS webhook_url" in SCHEMA
    assert "GRANT" not in SCHEMA  # grants live in sql/grants.sql (role may differ per install)
