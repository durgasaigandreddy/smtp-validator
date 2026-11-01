-- STEP 1 (pgAdmin). Connect to the default "postgres" database and open the Query Tool.
-- Run the statements ONE AT A TIME (select a statement, press F5): CREATE DATABASE cannot
-- run together with other statements.

-- 1) Application user. Change the password! Avoid the characters @ : / # ? in it, or
--    URL-encode them in DATABASE_URL.
CREATE ROLE validator WITH LOGIN PASSWORD 'ChangeMe-Long-Random-123';

-- 2) Database owned by that user
CREATE DATABASE validator OWNER validator ENCODING 'UTF8';
