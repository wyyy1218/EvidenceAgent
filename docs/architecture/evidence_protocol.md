# Evidence protocol (S16)

## Registration rule

Only a successful `read_evidence` body may enter the ledger. Search snippets, empty bodies, fetch failures, login walls, and tool failures must not upgrade to citeable evidence.

## Required fields

| Field | Meaning |
| --- | --- |
| `evidence_id` | Stable id (`ev_…`) |
| `source_version_id` | Immutable source version (local doc or web snapshot row) |
| `source_type` | `document` \| `web` |
| `canonical_ref` | Document/chunk id or canonical URL |
| `content_hash` | SHA-256 of source content (or body for web) |
| `captured_at` / version time | Snapshot or fetch time |
| `page` / `title` / `line_start` | Locator metadata when applicable |
| `char_start` / `char_end` | Unicode code-point half-open span when known |
| `quote` | Verbatim excerpt |
| `context_text` | Surrounding window for UI; not a substitute for quote |
| `requirement_ids` | Linked requirement ids |
| `read_action_id` | Action that produced the read |

## Verification

`verify_evidence` opens the immutable version by id and checks:

1. Evidence belongs to the run (and project when provided)
2. `source_version_id` is in the run authorization set
3. Content hash matches the stored source version (document path)
4. Quote equals the span slice, or is verbatim-present in normalized text when offsets are chunk-local
5. Page is within `page_count` when both are set

Truncating model context must not break recovery: ledger rows and normalized files on disk are authoritative.

## Claims and joint support

A claim may link to a set of evidence ids. Multi-document conclusions are judged against the **full evidence set**, not each document alone.

## Conflict expression

| Status | When |
| --- | --- |
| `compatible` | Texts agree or empty |
| `scoped_difference` | Texts differ but version/time/region/condition differ — report both ranges |
| `conflicting` | Same condition, irreconcilable claims |
| `unresolved` | Insufficient scope to decide |

Never auto-pick “latest” as truth for a user-specified older version.
