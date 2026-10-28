"""web_search: off / replay / live (Tavily basic). Discovery ≠ evidence."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evidence_agent.tools.candidates import CandidateRecord, CandidateRegistry, GLOBAL_CANDIDATES
from evidence_agent.tools.types import ToolResult, ToolStatus, fail

MAX_QUERY_LEN = 256
RESULTS_PER_SEARCH = 5
MAX_LIVE_SEARCH_CALLS = 3
SEARCH_TIMEOUT = 20.0


@dataclass
class WebSearchBudget:
    live_calls: int = 0
    max_live: int = MAX_LIVE_SEARCH_CALLS


@dataclass
class ReplayCorpus:
    """Frozen web library for replay mode — not a reproduction of live SERP ranks."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "ReplayCorpus":
        if not path.is_file():
            return cls([])
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return cls(data)
        return cls(data.get("entries") or [])

    def search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        q = query.lower()
        terms = [t for t in q.replace("/", " ").split() if t]
        scored: list[tuple[float, dict[str, Any]]] = []
        for e in self.entries:
            blob = " ".join(
                str(e.get(k) or "") for k in ("title", "snippet", "url", "text", "tags")
            ).lower()
            score = sum(1.0 for t in terms if t in blob)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for sc, e in scored[:top_k]:
            out.append(
                {
                    "url": e["url"],
                    "title": e.get("title") or e["url"],
                    "snippet": e.get("snippet") or (e.get("text") or "")[:240],
                    "score": sc,
                    "source": "replay",
                }
            )
        return out


def _candidate_id_for_url(url: str) -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"cand_web_{h}"


def web_search(
    *,
    query: str,
    mode: str,
    project_id: str,
    run_id: str,
    root: Path | None = None,
    allow_web: bool = False,
    registry: CandidateRegistry | None = None,
    budget: WebSearchBudget | None = None,
    replay_corpus: ReplayCorpus | None = None,
    tavily_api_key: str | None = None,
    results_per_search: int = RESULTS_PER_SEARCH,
    search_timeout: float = SEARCH_TIMEOUT,
    transient_retries: int = 1,
) -> ToolResult:
    """Discover URL candidates. Never upgrades snippet to evidence."""
    tool = "web_search"
    registry = registry or GLOBAL_CANDIDATES
    budget = budget or WebSearchBudget()
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

    mode = (mode or "off").lower()
    # User file Q&A defaults off — zero external calls
    if mode == "off":
        return ToolResult(
            tool=tool,
            status=ToolStatus.OK,
            data={"candidates": [], "mode": "off", "external_calls": 0},
            billing_status="n/a",
            meta={"mode": "off", "external_calls": 0},
        )
    if mode == "live" and not allow_web:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="web_not_allowed",
            error_message="allow_web=false",
            billing_status="n/a",
            meta={"mode": "off", "external_calls": 0},
        )

    if mode == "replay":
        if replay_corpus is None and root is not None:
            replay_path = root / "data" / "snapshots" / "replay_corpus.json"
            replay_corpus = ReplayCorpus.load(replay_path)
        replay_corpus = replay_corpus or ReplayCorpus([])
        hits = replay_corpus.search(q, top_k=results_per_search)
        return _register_hits(
            tool=tool,
            hits=hits,
            mode="replay",
            project_id=project_id,
            run_id=run_id,
            registry=registry,
            query=q,
            billing_status="n/a",
            external_calls=0,
            note="replay_is_not_live_serp_reproduction",
        )

    if mode != "live":
        return fail(
            tool,
            ToolStatus.UNSUPPORTED,
            error_code="unknown_mode",
            error_message=f"mode must be off|replay|live, got {mode}",
        )

    if budget.live_calls >= budget.max_live:
        return fail(
            tool,
            ToolStatus.PERMISSION_DENIED,
            error_code="live_quota_exhausted",
            error_message=f"max {budget.max_live} live searches per task",
            billing_status="n/a",
        )

    api_key = tavily_api_key or os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return fail(
            tool,
            ToolStatus.INACCESSIBLE,
            error_code="tavily_key_missing",
            error_message="TAVILY_API_KEY not configured; keep off/replay",
            billing_status="n/a",
            meta={"live_available": False},
        )

    # Only send the query string — never upload user documents
    last_err: ToolResult | None = None
    attempts = 1 + max(0, transient_retries)
    for attempt in range(attempts):
        try:
            import httpx

            payload = {
                "api_key": api_key,
                "query": q,
                "search_depth": "basic",
                "max_results": results_per_search,
                "include_answer": False,
                "include_raw_content": False,
            }
            with httpx.Client(timeout=search_timeout) as client:
                resp = client.post("https://api.tavily.com/search", json=payload)
            if resp.status_code in {401, 403}:
                return fail(
                    tool,
                    ToolStatus.PERMISSION_DENIED,
                    error_code=f"tavily_http_{resp.status_code}",
                    error_message="auth failed — not retried",
                    billing_status="unknown",
                )
            if resp.status_code >= 500 and attempt + 1 < attempts:
                last_err = fail(
                    tool,
                    ToolStatus.INACCESSIBLE,
                    error_code=f"tavily_http_{resp.status_code}",
                    error_message="transient server error",
                )
                time.sleep(0.2)
                continue
            if resp.status_code >= 400:
                return fail(
                    tool,
                    ToolStatus.INACCESSIBLE,
                    error_code=f"tavily_http_{resp.status_code}",
                    error_message=resp.text[:300],
                    billing_status="unknown",
                )
            data = resp.json()
            results = data.get("results") or []
            hits = []
            for r in results[:results_per_search]:
                hits.append(
                    {
                        "url": r.get("url"),
                        "title": r.get("title") or r.get("url"),
                        "snippet": r.get("content") or r.get("snippet") or "",
                        "score": r.get("score"),
                        "source": "tavily_basic",
                    }
                )
            budget.live_calls += 1
            return _register_hits(
                tool=tool,
                hits=hits,
                mode="live",
                project_id=project_id,
                run_id=run_id,
                registry=registry,
                query=q,
                billing_status="charged",
                external_calls=1,
                note="snippet_is_not_evidence; must read_evidence after fetch",
                usage={"tavily_credits": 1, "live_calls": budget.live_calls},
            )
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "Timeout" in name:
                # billing unknown on timeout
                if attempt + 1 < attempts:
                    last_err = fail(
                        tool,
                        ToolStatus.BILLING_UNKNOWN,
                        error_code="search_timeout_billing_unknown",
                        error_message=str(exc),
                        billing_status="unknown",
                    )
                    continue
                budget.live_calls += 1  # conservative reserve
                return fail(
                    tool,
                    ToolStatus.BILLING_UNKNOWN,
                    error_code="search_timeout_billing_unknown",
                    error_message=str(exc),
                    billing_status="unknown",
                    meta={"conservative_reserve": True, "no_unlimited_retry": True},
                )
            if attempt + 1 < attempts:
                last_err = fail(
                    tool,
                    ToolStatus.INACCESSIBLE,
                    error_code="search_error",
                    error_message=str(exc),
                )
                continue
            return fail(
                tool,
                ToolStatus.INACCESSIBLE,
                error_code="search_error",
                error_message=str(exc),
                billing_status="unknown",
            )
    return last_err or fail(
        tool, ToolStatus.ERROR, error_code="search_failed", error_message="unknown"
    )


def _register_hits(
    *,
    tool: str,
    hits: list[dict[str, Any]],
    mode: str,
    project_id: str,
    run_id: str,
    registry: CandidateRegistry,
    query: str,
    billing_status: str,
    external_calls: int,
    note: str,
    usage: dict[str, Any] | None = None,
) -> ToolResult:
    clean = [h for h in hits if h.get("url")]
    if not clean:
        return ToolResult(
            tool=tool,
            status=ToolStatus.EMPTY,
            data={"candidates": [], "mode": mode, "query": query},
            error_code="zero_results",
            error_message="no urls",
            billing_status=billing_status,
            meta={"external_calls": external_calls, "note": note},
            usage=usage or {},
        )
    payload = []
    records = []
    for h in clean:
        cid = _candidate_id_for_url(h["url"])
        records.append(
            CandidateRecord(
                candidate_id=cid,
                kind="web_url",
                project_id=project_id,
                run_id=run_id,
                url=h["url"],
                title=h.get("title"),
                snippet=h.get("snippet"),
                authorized=True,
                meta={"mode": mode},
            )
        )
        payload.append(
            {
                "candidate_id": cid,
                "url": h["url"],
                "title": h.get("title"),
                "snippet": h.get("snippet"),
                "source": h.get("source"),
                "snippet_is_not_evidence": True,
            }
        )
    registry.register_many(records)
    return ToolResult(
        tool=tool,
        status=ToolStatus.OK,
        data={"candidates": payload, "mode": mode, "query": query, "external_calls": external_calls},
        billing_status=billing_status,
        meta={"note": note, "external_calls": external_calls},
        usage=usage or {},
    )
