-- S16–S21: extend evidence ledger, usage, and step recovery fields

ALTER TABLE evidence ADD COLUMN context_text TEXT;
ALTER TABLE evidence ADD COLUMN content_hash TEXT;
ALTER TABLE evidence ADD COLUMN source_type TEXT;
ALTER TABLE evidence ADD COLUMN canonical_ref TEXT;
ALTER TABLE evidence ADD COLUMN captured_at TEXT;
ALTER TABLE evidence ADD COLUMN requirement_ids_json TEXT;
ALTER TABLE evidence ADD COLUMN scope_json TEXT;
ALTER TABLE evidence ADD COLUMN chunk_id TEXT;
ALTER TABLE evidence ADD COLUMN project_id TEXT;

ALTER TABLE claims ADD COLUMN scope_json TEXT;
ALTER TABLE claims ADD COLUMN status TEXT;
ALTER TABLE claims ADD COLUMN evidence_ids_json TEXT;

ALTER TABLE usage_events ADD COLUMN step_id TEXT;
ALTER TABLE usage_events ADD COLUMN kind TEXT;
ALTER TABLE usage_events ADD COLUMN input_tokens INTEGER;
ALTER TABLE usage_events ADD COLUMN output_tokens INTEGER;
ALTER TABLE usage_events ADD COLUMN logical_tool_call INTEGER DEFAULT 0;
ALTER TABLE usage_events ADD COLUMN physical_request INTEGER DEFAULT 0;
ALTER TABLE usage_events ADD COLUMN cache_hit INTEGER DEFAULT 0;
ALTER TABLE usage_events ADD COLUMN meta_json TEXT;

ALTER TABLE actions ADD COLUMN duration_ms REAL;
ALTER TABLE actions ADD COLUMN model_id TEXT;
ALTER TABLE actions ADD COLUMN adapter_id TEXT;
ALTER TABLE actions ADD COLUMN snapshot_id TEXT;
ALTER TABLE actions ADD COLUMN paid_call_state TEXT;

ALTER TABLE runs ADD COLUMN resume_step INTEGER;
ALTER TABLE runs ADD COLUMN packed_prompt_path TEXT;
