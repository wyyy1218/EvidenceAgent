"""local_search tool — wraps HybridRetriever."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.tools.candidates import CandidateRecord, CandidateRegistry, GLOBAL_CANDIDATES
from evidence_agent.tools.types import ToolResult, ToolStatus, fail

MAX_QUERY_LEN = 256


def local_search(
    *,
    root: Path,
    project_id: str,
    run_id: str,
    query: str,
    retriever: HybridRetriever | None = None,
    registry: CandidateRegistry | None = None,
) -> ToolResult:
    tool = "local_search"
    registry = registry or GLOBAL_CANDIDATES
    q = (query or "").strip()
    if not q:
        return fail(tool, ToolStatus.EMPTY, error_code="empty_query", error_message="query required")
    if len(q) > MAX_QUERY_LEN:
        return fail(
            tool,
            ToolStatus.UNSUPPORTED,
            error_code="query_too_long",
            error_message=f"query max {MAX_QUERY_LEN} chars",
        )

    retriever = retriever or HybridRetriever(root, project_id)
    result = retriever.search(q)
    if result.status == "empty" or not result.candidates:
        return ToolResult(
            tool=tool,
            status=ToolStatus.EMPTY,
            data={"candidates": [], "query": q},
            error_code="zero_results",
            error_message="no candidates",
            billing_status="n/a",
            meta={"cache": result.cache, "debug": result.debug, "preview_is_not_evidence": True},
        )

    records: list[CandidateRecord] = []
    payload: list[dict[str, Any]] = []
    for c in result.candidates:
        records.append(
            CandidateRecord(
                candidate_id=c.candidate_id,
                kind="local_chunk",
                project_id=project_id,
                run_id=run_id,
                source_version_id=c.source_version_id,
                chunk_id=c.chunk_id,
                title=c.title,
                snippet=c.preview,
                authorized=True,
                meta={"start": c.start, "end": c.end, "page": c.page},
            )
        )
        payload.append(c.to_dict())
    registry.register_many(records)

    return ToolResult(
        tool=tool,
        status=ToolStatus.OK,
        data={"candidates": payload, "query": q},
        billing_status="n/a",
        meta={"cache": result.cache, "preview_is_not_evidence": True, "debug": result.debug},
    )
