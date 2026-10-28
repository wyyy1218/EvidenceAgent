-- EvidenceAgent schema v0001 (S09)

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'uploaded',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  content_hash TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  file_path TEXT,
  snapshot_time TEXT NOT NULL,
  byte_size INTEGER,
  mime_type TEXT,
  page_count INTEGER,
  parse_status TEXT NOT NULL DEFAULT 'pending',
  normalized_path TEXT,
  mapping_path TEXT,
  dedup_of_version_id TEXT REFERENCES source_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_source_versions_hash ON source_versions(content_hash);
CREATE INDEX IF NOT EXISTS idx_source_versions_document ON source_versions(document_id);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  text TEXT NOT NULL,
  page INTEGER,
  section TEXT,
  start INTEGER,
  end INTEGER,
  parent_id TEXT
);

CREATE TABLE IF NOT EXISTS indexes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  version_set_hash TEXT NOT NULL,
  embedding_revision TEXT,
  index_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  question TEXT NOT NULL,
  status TEXT NOT NULL,
  policy_id TEXT,
  budget TEXT,
  worker_lease TEXT,
  lease_expires_at TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  allow_web INTEGER NOT NULL DEFAULT 0,
  budget_profile TEXT NOT NULL DEFAULT 'standard',
  idempotency_key TEXT,
  request_hash TEXT,
  version_set_json TEXT,
  failure_reason TEXT,
  error_code TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency
  ON runs(idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key != '';

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);

CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  step_no INTEGER NOT NULL,
  state_hash TEXT,
  action_json TEXT NOT NULL,
  result_status TEXT,
  result_json TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, step_no)
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  span TEXT,
  quote TEXT,
  read_action_id TEXT,
  page INTEGER,
  title TEXT,
  line_start INTEGER,
  char_start INTEGER,
  char_end INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  requirement_id TEXT,
  text TEXT NOT NULL,
  scope TEXT,
  verification_status TEXT
);

CREATE TABLE IF NOT EXISTS claim_evidence (
  claim_id TEXT NOT NULL REFERENCES claims(id),
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  PRIMARY KEY (claim_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  provider TEXT,
  model TEXT,
  tokens INTEGER,
  latency REAL,
  credits REAL,
  billing_status TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id),
  event_type TEXT NOT NULL,
  payload TEXT,
  timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, id);

CREATE TABLE IF NOT EXISTS ingest_jobs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  version_id TEXT NOT NULL REFERENCES source_versions(id),
  status TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
