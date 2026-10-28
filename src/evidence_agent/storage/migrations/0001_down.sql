-- Rollback v0001 (test / empty DB only — do not use to hide production history)

DROP TABLE IF EXISTS ingest_jobs;
DROP TABLE IF EXISTS audit_events;
DROP TABLE IF EXISTS usage_events;
DROP TABLE IF EXISTS claim_evidence;
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS evidence;
DROP TABLE IF EXISTS actions;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS indexes;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS source_versions;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS projects;
DELETE FROM schema_migrations WHERE version = '0001';
