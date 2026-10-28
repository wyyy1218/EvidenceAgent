"""Repositories with project isolation and transactional boundaries."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from evidence_agent.storage.ids import new_id

TERMINAL_STATUSES = frozenset(
    {
        "answered",
        "partial",
        "insufficient_evidence",
        "conflicting_evidence",
        "cancelled",
        "timeout",
        "failed",
    }
)
QUEUE_STATUSES = frozenset({"queued", "running"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


class StorageError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class IdempotencyConflict(StorageError):
    def __init__(self, message: str = "idempotency key conflict"):
        super().__init__("idempotency_conflict", message)


class QueueFull(StorageError):
    def __init__(self, message: str = "queue full"):
        super().__init__("queue_full", message)


# ----- projects -----


def create_project(conn: sqlite3.Connection, name: str, description: str | None = None) -> str:
    pid = new_id("proj")
    conn.execute(
        "INSERT INTO projects(id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (pid, name, description or "", utc_now()),
    )
    return pid


def get_project(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    )


# ----- documents / versions -----


def count_documents(conn: sqlite3.Connection, project_id: str) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM documents WHERE project_id = ?", (project_id,)
    ).fetchone()
    return int(r["c"])


def create_document(
    conn: sqlite3.Connection,
    project_id: str,
    display_name: str,
    *,
    status: str = "uploaded",
) -> str:
    did = new_id("doc")
    now = utc_now()
    conn.execute(
        "INSERT INTO documents(id, project_id, display_name, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (did, project_id, display_name, status, now, now),
    )
    return did


def get_document(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    )


def update_document_status(conn: sqlite3.Connection, document_id: str, status: str) -> None:
    conn.execute(
        "UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
        (status, utc_now(), document_id),
    )


def create_source_version(
    conn: sqlite3.Connection,
    document_id: str,
    content_hash: str,
    parser_version: str,
    *,
    file_path: str | None = None,
    byte_size: int | None = None,
    mime_type: str | None = None,
    page_count: int | None = None,
    parse_status: str = "pending",
    normalized_path: str | None = None,
    mapping_path: str | None = None,
    dedup_of_version_id: str | None = None,
) -> str:
    vid = new_id("src")
    conn.execute(
        "INSERT INTO source_versions("
        "id, document_id, content_hash, parser_version, file_path, snapshot_time, "
        "byte_size, mime_type, page_count, parse_status, normalized_path, mapping_path, "
        "dedup_of_version_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            vid,
            document_id,
            content_hash,
            parser_version,
            file_path,
            utc_now(),
            byte_size,
            mime_type,
            page_count,
            parse_status,
            normalized_path,
            mapping_path,
            dedup_of_version_id,
        ),
    )
    return vid


def get_source_version(conn: sqlite3.Connection, version_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute("SELECT * FROM source_versions WHERE id = ?", (version_id,)).fetchone()
    )


def find_version_by_hash(
    conn: sqlite3.Connection, content_hash: str, *, project_id: str | None = None
) -> dict[str, Any] | None:
    if project_id:
        row = conn.execute(
            "SELECT sv.* FROM source_versions sv "
            "JOIN documents d ON d.id = sv.document_id "
            "WHERE sv.content_hash = ? AND d.project_id = ? "
            "AND sv.parse_status IN ('parsed', 'deduped') "
            "ORDER BY sv.snapshot_time ASC LIMIT 1",
            (content_hash, project_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM source_versions WHERE content_hash = ? "
            "AND parse_status IN ('parsed', 'deduped') "
            "ORDER BY snapshot_time ASC LIMIT 1",
            (content_hash,),
        ).fetchone()
    return row_to_dict(row)


def list_project_version_ids(conn: sqlite3.Connection, project_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT sv.id FROM source_versions sv "
        "JOIN documents d ON d.id = sv.document_id "
        "WHERE d.project_id = ? AND sv.parse_status IN ('parsed', 'deduped') "
        "ORDER BY sv.snapshot_time",
        (project_id,),
    ).fetchall()
    return [r["id"] for r in rows]


def latest_version_for_document(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            "SELECT * FROM source_versions WHERE document_id = ? "
            "ORDER BY snapshot_time DESC LIMIT 1",
            (document_id,),
        ).fetchone()
    )


def create_ingest_job(
    conn: sqlite3.Connection, document_id: str, version_id: str, status: str = "queued"
) -> str:
    jid = new_id("ingest")
    now = utc_now()
    conn.execute(
        "INSERT INTO ingest_jobs(id, document_id, version_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (jid, document_id, version_id, status, now, now),
    )
    return jid


def update_ingest_job(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    conn.execute(
        "UPDATE ingest_jobs SET status = ?, error_code = ?, error_message = ?, updated_at = ? "
        "WHERE id = ?",
        (status, error_code, error_message, utc_now(), job_id),
    )


def update_source_version_parse(
    conn: sqlite3.Connection,
    version_id: str,
    *,
    parse_status: str,
    file_path: str | None = None,
    page_count: int | None = None,
    normalized_path: str | None = None,
    mapping_path: str | None = None,
    dedup_of_version_id: str | None = None,
) -> None:
    fields = ["parse_status = ?"]
    vals: list[Any] = [parse_status]
    if file_path is not None:
        fields.append("file_path = ?")
        vals.append(file_path)
    if page_count is not None:
        fields.append("page_count = ?")
        vals.append(page_count)
    if normalized_path is not None:
        fields.append("normalized_path = ?")
        vals.append(normalized_path)
    if mapping_path is not None:
        fields.append("mapping_path = ?")
        vals.append(mapping_path)
    if dedup_of_version_id is not None:
        fields.append("dedup_of_version_id = ?")
        vals.append(dedup_of_version_id)
    vals.append(version_id)
    conn.execute(
        f"UPDATE source_versions SET {', '.join(fields)} WHERE id = ?",
        vals,
    )


# ----- runs -----


def count_queued(conn: sqlite3.Connection) -> int:
    r = conn.execute(
        "SELECT COUNT(*) AS c FROM runs WHERE status = 'queued'"
    ).fetchone()
    return int(r["c"])


def create_run(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    question: str,
    allow_web: bool,
    budget_profile: str,
    budget: dict[str, Any] | None,
    idempotency_key: str | None,
    request_hash: str | None,
    version_set: list[str],
    max_queue: int = 10,
) -> tuple[str, bool]:
    """Return (run_id, created_new). Raises IdempotencyConflict or QueueFull."""
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise IdempotencyConflict(
                    "same Idempotency-Key with different request body"
                )
            return existing["id"], False

    if count_queued(conn) >= max_queue:
        raise QueueFull(f"queue full (max {max_queue})")

    rid = new_id("run")
    now = utc_now()
    conn.execute(
        "INSERT INTO runs("
        "id, project_id, question, status, policy_id, budget, worker_lease, "
        "lease_expires_at, cancel_requested, allow_web, budget_profile, "
        "idempotency_key, request_hash, version_set_json, created_at, updated_at"
        ") VALUES (?, ?, ?, 'queued', NULL, ?, NULL, NULL, 0, ?, ?, ?, ?, ?, ?, ?)",
        (
            rid,
            project_id,
            question,
            json.dumps(budget or {}, ensure_ascii=False),
            1 if allow_web else 0,
            budget_profile,
            idempotency_key,
            request_hash,
            json.dumps(version_set, ensure_ascii=False),
            now,
            now,
        ),
    )
    add_audit(conn, rid, "run_queued", {"question_len": len(question)})
    return rid, True


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def request_cancel(conn: sqlite3.Connection, run_id: str) -> bool:
    row = get_run(conn, run_id)
    if not row:
        return False
    if row["status"] in TERMINAL_STATUSES:
        return True
    conn.execute(
        "UPDATE runs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
        (utc_now(), run_id),
    )
    add_audit(conn, run_id, "cancel_requested", {})
    return True


def claim_run(
    conn: sqlite3.Connection, lease_id: str, *, lease_seconds: int = 120
) -> dict[str, Any] | None:
    """Claim one queued run. Caller should hold a transaction."""
    from datetime import timedelta

    row = conn.execute(
        "SELECT id FROM runs WHERE status = 'queued' AND cancel_requested = 0 "
        "ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    if not row:
        # honour cancel on queued
        crow = conn.execute(
            "SELECT id FROM runs WHERE status = 'queued' AND cancel_requested = 1 "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if crow:
            finalize_run(conn, crow["id"], status="cancelled", failure_reason="cancelled")
        return None
    expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    cur = conn.execute(
        "UPDATE runs SET status = 'running', worker_lease = ?, lease_expires_at = ?, "
        "updated_at = ? WHERE id = ? AND status = 'queued'",
        (lease_id, expires, utc_now(), row["id"]),
    )
    if cur.rowcount != 1:
        return None
    add_audit(conn, row["id"], "run_claimed", {"lease": lease_id})
    return get_run(conn, row["id"])


def heartbeat_run(conn: sqlite3.Connection, run_id: str, lease_id: str, *, lease_seconds: int = 120) -> bool:
    from datetime import timedelta

    expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    cur = conn.execute(
        "UPDATE runs SET lease_expires_at = ?, updated_at = ? "
        "WHERE id = ? AND worker_lease = ? AND status = 'running'",
        (expires, utc_now(), run_id, lease_id),
    )
    return cur.rowcount == 1


def finalize_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    failure_reason: str | None = None,
    error_code: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    if status == "failed" and failure_reason == "failed_policy":
        error_code = error_code or "failed_policy"
    conn.execute(
        "UPDATE runs SET status = ?, failure_reason = ?, error_code = ?, "
        "result_json = ?, worker_lease = NULL, updated_at = ? WHERE id = ?",
        (
            status,
            failure_reason,
            error_code,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            utc_now(),
            run_id,
        ),
    )
    add_audit(
        conn,
        run_id,
        "run_finalized",
        {"status": status, "failure_reason": failure_reason, "error_code": error_code},
    )


def register_action_and_result(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_no: int,
    action: dict[str, Any],
    result_status: str,
    result: dict[str, Any] | None,
    state_hash: str | None = None,
    commit: bool = True,
) -> str:
    """Atomic: insert action with result in one transaction. No half-rows."""
    aid = new_id("act")
    if commit:
        conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO actions(id, run_id, step_no, state_hash, action_json, "
            "result_status, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                aid,
                run_id,
                step_no,
                state_hash,
                json.dumps(action, ensure_ascii=False),
                result_status,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                utc_now(),
            ),
        )
        if commit:
            conn.execute("COMMIT")
    except Exception:
        if commit:
            conn.execute("ROLLBACK")
        raise
    return aid


def register_action_then_fail(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    step_no: int,
    action: dict[str, Any],
) -> None:
    """Test helper: insert action without result then rollback — must leave zero rows."""
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO actions(id, run_id, step_no, state_hash, action_json, "
            "result_status, result_json, created_at) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)",
            (
                new_id("act"),
                run_id,
                step_no,
                None,
                json.dumps(action, ensure_ascii=False),
                utc_now(),
            ),
        )
        raise RuntimeError("simulated_crash")
    except RuntimeError:
        conn.execute("ROLLBACK")
        raise


def add_audit(
    conn: sqlite3.Connection, run_id: str, event_type: str, payload: dict[str, Any]
) -> int:
    cur = conn.execute(
        "INSERT INTO audit_events(run_id, event_type, payload, timestamp) VALUES (?, ?, ?, ?)",
        (run_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
    )
    return int(cur.lastrowid)


def list_audit_events(
    conn: sqlite3.Connection, run_id: str, *, after_id: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE run_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
        (run_id, after_id, limit),
    ).fetchall()
    return [row_to_dict(r) for r in rows]  # type: ignore[misc]


def get_evidence(
    conn: sqlite3.Connection, run_id: str, evidence_id: str
) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            "SELECT * FROM evidence WHERE id = ? AND run_id = ?",
            (evidence_id, run_id),
        ).fetchone()
    )


def insert_evidence(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    source_version_id: str,
    quote: str,
    span: str | None = None,
    read_action_id: str | None = None,
    page: int | None = None,
    title: str | None = None,
    line_start: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> str:
    eid = new_id("ev")
    conn.execute(
        "INSERT INTO evidence("
        "id, run_id, source_version_id, span, quote, read_action_id, page, title, "
        "line_start, char_start, char_end, created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            eid,
            run_id,
            source_version_id,
            span,
            quote,
            read_action_id,
            page,
            title,
            line_start,
            char_start,
            char_end,
            utc_now(),
        ),
    )
    return eid
