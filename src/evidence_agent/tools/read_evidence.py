"""read_evidence — only registered candidate_id; no arbitrary paths/URLs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evidence_agent.tools.candidates import CandidateRegistry, GLOBAL_CANDIDATES
from evidence_agent.tools.types import ToolResult, ToolStatus, fail
from evidence_agent.tools.web_fetch import fetch_url

MAX_CANDIDATE_ID_LEN = 128
# Instruction-injection patterns in content are DATA only — never elevate privileges
_INJECTION_HINT = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior)\s+instructions|忽略(以上|之前|所有).{0,8}指令|"
    r"you\s+are\s+now|system\s*prompt)",
    re.I,
)


def read_evidence(
    *,
    candidate_id: str,
    run_id: str,
    project_id: str,
    root: Path,
    registry: CandidateRegistry | None = None,
    authorized_version_ids: set[str] | list[str] | None = None,
    allow_web_fetch: bool = False,
) -> ToolResult:
    tool = "read_evidence"
    registry = registry or GLOBAL_CANDIDATES
    cid = (candidate_id or "").strip()
    if not cid:
        return fail(tool, ToolStatus.UNSUPPORTED, error_code="missing_candidate_id", error_message="required")
    if len(cid) > MAX_CANDIDATE_ID_LEN:
        return fail(tool, ToolStatus.UNSUPPORTED, error_code="candidate_id_too_long", error_message="max 128")

    # Reject path-like or raw URL abuse
    if cid.startswith("/") or cid.startswith("\\") or ".." in cid or "://" in cid:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="arbitrary_path_or_url_rejected",
            error_message="only registered candidate_id accepted",
        )

    rec = registry.get(run_id, cid)
    if rec is None:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="unknown_candidate",
            error_message="candidate not registered for this run",
            meta={"candidate_id": cid},
        )
    if rec.project_id != project_id:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="cross_project",
            error_message="candidate not in current project",
        )
    if not rec.authorized:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="not_authorized",
            error_message="candidate not in run authorization set",
        )

    auth_versions = set(authorized_version_ids or [])

    if rec.kind == "local_chunk":
        if auth_versions and rec.source_version_id and rec.source_version_id not in auth_versions:
            return fail(
                tool,
                ToolStatus.PERMISSION_DENIED,
                error_code="version_not_in_run_set",
                error_message="source_version_id outside run version_set",
            )
        # Load chunk text from chunks store via candidate meta / index
        text, loc = _load_local_chunk(root, project_id, rec.chunk_id or "", rec.source_version_id)
        if text is None:
            return fail(
                tool,
                ToolStatus.INACCESSIBLE,
                error_code="chunk_missing",
                error_message="chunk body not found",
            )
        injection_flag = bool(_INJECTION_HINT.search(text))
        return ToolResult(
            tool=tool,
            status=ToolStatus.OK,
            data={
                "evidence": {
                    "candidate_id": cid,
                    "source_version_id": rec.source_version_id,
                    "chunk_id": rec.chunk_id,
                    "quote": text,
                    "title": rec.title,
                    "locator": loc,
                    "content_treated_as_data_only": True,
                    "injection_like_text_detected": injection_flag,
                }
            },
            billing_status="n/a",
            meta={"kind": "local_chunk", "permissions_unchanged": True},
        )

    if rec.kind == "web_url":
        if not allow_web_fetch:
            return fail(
                tool,
                ToolStatus.PERMISSION_DENIED,
                error_code="web_fetch_disabled",
                error_message="web fetch not allowed for this run",
            )
        if not rec.url:
            return fail(tool, ToolStatus.INACCESSIBLE, error_code="missing_url", error_message="no url")
        # Snippet alone must NEVER become evidence — must fetch body
        fetched = fetch_url(rec.url, root=root, save_snapshot=True)
        if fetched.is_failure or fetched.status != ToolStatus.OK:
            # Preserve failure — do not fall back to snippet
            return ToolResult(
                tool=tool,
                status=fetched.status if fetched.is_failure else ToolStatus.INACCESSIBLE,
                data={},
                error_code=fetched.error_code or "fetch_failed",
                error_message=(fetched.error_message or "fetch failed")
                + " (snippet not upgraded to evidence)",
                billing_status=fetched.billing_status,
                meta={"snippet_discarded": True, "url": rec.url},
            )
        body = fetched.data.get("text") or ""
        injection_flag = bool(_INJECTION_HINT.search(body))
        return ToolResult(
            tool=tool,
            status=ToolStatus.OK,
            data={
                "evidence": {
                    "candidate_id": cid,
                    "url": fetched.data.get("canonical_url") or rec.url,
                    "quote": body,
                    "content_hash": fetched.data.get("content_hash"),
                    "fetched_at": fetched.data.get("fetched_at"),
                    "snapshot_path": fetched.data.get("snapshot_path"),
                    "title": rec.title,
                    "content_treated_as_data_only": True,
                    "injection_like_text_detected": injection_flag,
                    "snippet_not_used_as_evidence": True,
                }
            },
            billing_status="n/a",
            meta={"kind": "web_url", "permissions_unchanged": True},
        )

    return fail(
        tool,
        ToolStatus.UNSUPPORTED,
        error_code="unknown_candidate_kind",
        error_message=rec.kind,
    )


def _load_local_chunk(
    root: Path, project_id: str, chunk_id: str, source_version_id: str | None
) -> tuple[str | None, dict[str, Any]]:
    ptr = root / "data" / "indexes" / f"current_{project_id}.json"
    if not ptr.is_file():
        return None, {}
    pointer = json.loads(ptr.read_text(encoding="utf-8"))
    chunks_path = root / "data" / "chunks" / pointer["index_id"] / "chunks.jsonl"
    if not chunks_path.is_file():
        return None, {}
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("chunk_id") == chunk_id:
            if source_version_id and row.get("source_version_id") != source_version_id:
                continue
            loc = {
                "start": row.get("start"),
                "end": row.get("end"),
                "page": row.get("page"),
                "section": row.get("section"),
                "title": row.get("title"),
            }
            return row.get("text"), loc
    return None, {}
