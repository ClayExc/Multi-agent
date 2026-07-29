-- Development rollback only. Production destructive rollback requires a
-- separately approved work package and backup/restore evidence.
BEGIN;
DROP SCHEMA IF EXISTS flowpilot CASCADE;
DROP ROLE IF EXISTS flowpilot_publisher;
DROP ROLE IF EXISTS flowpilot_gateway;
DROP ROLE IF EXISTS flowpilot_worker;
DROP ROLE IF EXISTS flowpilot_api;
COMMIT;
