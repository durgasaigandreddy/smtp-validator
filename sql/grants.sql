-- STEP 3 (pgAdmin, only if needed). Run in the "validator" database as the postgres superuser
-- AFTER sql/schema.sql was run by that superuser. It lets the application user "validator"
-- use the tables. Not needed if you ran schema.sql while logged in as "validator", and not
-- needed with the Docker setup (the Postgres container user already owns everything).
GRANT USAGE ON SCHEMA public TO validator;
GRANT ALL ON ALL TABLES IN SCHEMA public TO validator;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO validator;
