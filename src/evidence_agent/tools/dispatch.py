"""Unified tool dispatch with schema validation (S15)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from evidence_agent.tools.candidates import CandidateRegistry, GLOBAL_CANDIDATES
from evidence_agent.tools.local_search import local_search
from evidence_agent.tools.read_evidence import read_evidence
from evidence_agent.tools.types import ToolResult, ToolStatus, fail
from evidence_agent.tools.web_search import WebSearchBudget, web_search

ALLOWED_TOOLS = frozenset({"local_search", "web_search", "read_evidence"})


def dispatch_tool(
    action: dict[str, Any],
    *,
    root: Path,
    project_id: str,
    run_id: str,
    allow_web: bool = False,
    web_mode: str = "off",
    authorized_version_ids: list[str] | None = None,
    registry: CandidateRegistry | None = None,
    budget: WebSearchBudget | None = None,
    retriever: Any = None,
) -> ToolResult:
    """Execute one of the three external tools. Controllers cannot bypass this."""
    registry = registry or GLOBAL_CANDIDATES
    name = (action.get("action") or action.get("tool") or "").strip()
    if name not in ALLOWED_TOOLS:
        return fail(
            "dispatch",
            ToolStatus.PERMISSION_DENIED,
            error_code="unknown_tool",
            error_message=f"only {sorted(ALLOWED_TOOLS)} allowed",
        )

    if name == "local_search":
        return local_search(
            root=root,
            project_id=project_id,
            run_id=run_id,
            query=str(action.get("query") or ""),
            retriever=retriever,
            registry=registry,
        )
    if name == "web_search":
        return web_search(
            query=str(action.get("query") or ""),
            mode=web_mode if allow_web else "off",
            project_id=project_id,
            run_id=run_id,
            root=root,
            allow_web=allow_web,
            registry=registry,
            budget=budget,
        )
    if name == "read_evidence":
        return read_evidence(
            candidate_id=str(action.get("candidate_id") or ""),
            run_id=run_id,
            project_id=project_id,
            root=root,
            registry=registry,
            authorized_version_ids=authorized_version_ids,
            allow_web_fetch=allow_web or web_mode in {"replay", "live"},
        )
    return fail("dispatch", ToolStatus.ERROR, error_code="unreachable", error_message=name)
