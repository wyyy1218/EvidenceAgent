"""Register successful read_evidence bodies into the immutable evidence ledger."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evidence_agent.storage import repositories as repo
from evidence_agent.storage.ids import new_id
from evidence_agent.tools.types import ToolResult, ToolStatus


@dataclass
class EvidenceRecord:
    evidence_id: str
    run_id: str
    project_id: str
    source_version_id: str
    source_type: str
    canonical_ref: str
    content_hash: str
    captured_at: str | None
    page: int | None
    title: str | None
    line_start: int | None
    char_start: int | None
    char_end: int | None
    quote: str
    context_text: str
    requirement_ids: list[str] = field(default_factory=list)
    read_action_id: str | None = None
    chunk_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    span: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def reject_non_body(tool_result: ToolResult | dict[str, Any]) -> str | None:
    """Return rejection reason if payload must not become evidence; else None."""
    if isinstance(tool_result, ToolResult):
        if tool_result.is_failure or tool_result.status == ToolStatus.EMPTY:
            return f"tool_status_{tool_result.status.value}"
        if tool_result.status != ToolStatus.OK:
            return f"tool_status_{tool_result.status.value}"
        data = tool_result.data or {}
        ev = data.get("evidence")
    else:
        if tool_result.get("is_failure") or tool_result.get("status") in {
            "empty",
            "inaccessible",
            "timeout",
            "permission_denied",
            "unsupported",
            "billing_unknown",
            "error",
        }:
            return f"tool_status_{tool_result.get('status')}"
        ev = tool_result.get("evidence") or (tool_result.get("data") or {}).get("evidence")
    if not ev:
        return "missing_evidence_payload"
    quote = (ev.get("quote") or "").strip()
    if not quote:
        return "empty_body"
    # Search snippets / previews must never upgrade
    if ev.get("snippet_not_used_as_evidence") is False and ev.get("is_snippet"):
        return "snippet_not_body"
    if ev.get("is_search_snippet") or ev.get("preview_only"):
        return "search_snippet_rejected"
    return None


def _context_window(full_text: str, start: int | None, end: int | None, radius: int = 120) -> str:
    if not full_text:
        return ""
    if start is None or end is None:
        return full_text[: min(len(full_text), radius * 2)]
    lo = max(0, int(start) - radius)
    hi = min(len(full_text), int(end) + radius)
    return full_text[lo:hi]


def _load_normalized_text(root: Path, source_version_id: str) -> str | None:
    path = root / "data" / "normalized" / source_version_id / "content_clean.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def register_from_read(
    conn,
    *,
    root: Path,
    run_id: str,
    project_id: str,
    tool_result: ToolResult,
    read_action_id: str | None = None,
    requirement_ids: list[str] | None = None,
    scope: dict[str, Any] | None = None,
    authorized_version_ids: set[str] | list[str] | None = None,
) -> EvidenceRecord:
    """Persist OK read body. Raises ValueError if not eligible for ledger."""
    reason = reject_non_body(tool_result)
    if reason:
        raise ValueError(f"cannot_register_evidence:{reason}")

    ev = tool_result.data["evidence"]
    quote = ev["quote"]
    source_version_id = ev.get("source_version_id") or ""
    auth = set(authorized_version_ids or [])
    if auth and source_version_id and source_version_id not in auth:
        raise PermissionError("source_version_id outside run authorization set")

    # Cross-project: ensure source belongs to project when local
    if source_version_id:
        ver = repo.get_source_version(conn, source_version_id)
        if ver is None:
            raise ValueError("unknown_source_version")
        doc = repo.get_document(conn, ver["document_id"])
        if doc and doc["project_id"] != project_id:
            raise PermissionError("cross_project_source")

    locator = ev.get("locator") or {}
    char_start = locator.get("start") if locator.get("start") is not None else ev.get("char_start")
    char_end = locator.get("end") if locator.get("end") is not None else ev.get("char_end")
    page = locator.get("page") if locator.get("page") is not None else ev.get("page")
    title = ev.get("title") or locator.get("title") or locator.get("section")
    line_start = ev.get("line_start") or locator.get("line_start")

    full = _load_normalized_text(root, source_version_id) if source_version_id else None
    context = _context_window(full or quote, char_start, char_end)

    content_hash = ev.get("content_hash")
    if not content_hash and source_version_id:
        ver = repo.get_source_version(conn, source_version_id)
        content_hash = ver["content_hash"] if ver else None
    if not content_hash:
        content_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()

    source_type = "web" if ev.get("url") else "document"
    if ev.get("source_type"):
        source_type = ev["source_type"]
    canonical_ref = ev.get("url") or ev.get("chunk_id") or source_version_id
    captured_at = ev.get("fetched_at") or (repo.get_source_version(conn, source_version_id) or {}).get(
        "snapshot_time"
    )

    # Web without source_version: create ephemeral web source version under project
    if not source_version_id:
        source_version_id = _ensure_web_source_version(
            conn,
            project_id=project_id,
            url=str(canonical_ref),
            content_hash=content_hash,
            captured_at=captured_at,
        )

    span = None
    if char_start is not None and char_end is not None:
        span = f"{char_start}:{char_end}"

    eid = new_id("ev")
    req_ids = list(requirement_ids or [])
    scope_obj = dict(scope or {})
    now = repo.utc_now()
    conn.execute(
        "INSERT INTO evidence("
        "id, run_id, source_version_id, span, quote, read_action_id, page, title, "
        "line_start, char_start, char_end, created_at, context_text, content_hash, "
        "source_type, canonical_ref, captured_at, requirement_ids_json, scope_json, "
        "chunk_id, project_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            now,
            context,
            content_hash,
            source_type,
            str(canonical_ref),
            captured_at,
            json.dumps(req_ids, ensure_ascii=False),
            json.dumps(scope_obj, ensure_ascii=False),
            ev.get("chunk_id"),
            project_id,
        ),
    )
    return EvidenceRecord(
        evidence_id=eid,
        run_id=run_id,
        project_id=project_id,
        source_version_id=source_version_id,
        source_type=source_type,
        canonical_ref=str(canonical_ref),
        content_hash=content_hash,
        captured_at=captured_at,
        page=page,
        title=title,
        line_start=line_start,
        char_start=char_start,
        char_end=char_end,
        quote=quote,
        context_text=context,
        requirement_ids=req_ids,
        read_action_id=read_action_id,
        chunk_id=ev.get("chunk_id"),
        scope=scope_obj,
        span=span,
    )


def _ensure_web_source_version(
    conn,
    *,
    project_id: str,
    url: str,
    content_hash: str,
    captured_at: str | None,
) -> str:
    """Create a document+version row for a web snapshot so FK holds."""
    doc_id = repo.create_document(conn, project_id, display_name=url[:200], status="web_snapshot")
    return repo.create_source_version(
        conn,
        document_id=doc_id,
        content_hash=content_hash,
        parser_version="web_fetch_v1",
        file_path=None,
        byte_size=None,
        mime_type="text/html",
        page_count=None,
        parse_status="ok",
    )


def list_run_evidence(conn, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM evidence WHERE run_id = ? ORDER BY created_at ASC", (run_id,)
    ).fetchall()
    return [repo.row_to_dict(r) for r in rows]  # type: ignore[misc]
