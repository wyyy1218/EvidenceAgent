# State and action protocol (S18–S19)

## Visible state (§10.1)

Controller-visible fields only:

- `question`, `requirements`
- `project_id`, `snapshot_set_id`
- `candidates`, `evidence_cards`
- `open_gaps` (**suggestion**, not ground truth)
- `recent_actions`, `budget`, `source_failures`

Never visible: `full_raw_history`, `gold_answer`, `gold_support`, or any `gold_*` field.

`state_hash` = SHA-256 of canonical JSON of the visible dict (`sort_keys`, compact separators).

## Packer rules

| Limit | Value |
| --- | ---: |
| Policy prompt | ≤ 2880 Qwen tokens |
| Policy completion | ≤ 192 |
| Train total | ≤ 3072 |

Priority keep order: system protocol → question → budget → requirements → evidence cards → candidates → old actions.

On overflow: reduce card counts; retain re-readable IDs; set `truncated=true`. Never mid-string-truncate JSON. Do not replace precise numbers/versions with summaries.

If the question itself cannot retain negation/constraints within budget → **reject at entry** (`PackRejectError`).

Same input → same packed prompt (deterministic).

## Actions (§10.2)

Five actions only: `local_search`, `web_search`, `read_evidence`, `finish`, `abstain`.

Four fields always present (`null` when N/A): `action`, `query`, `candidate_id`, `reason_code`.

`reason_code` enum: `evidence_sufficient`, `missing_source`, `conflicting_sources`, `low_information_gain`, `budget_exhausted`, `tool_unavailable`.
