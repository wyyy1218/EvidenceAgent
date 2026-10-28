"""E0 comparable entrypoint — wraps controlled LangGraph loop (ledger + packing)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.graph import run_agent_loop
from evidence_agent.agent.llm import HttpLLMClient, LLMClient, MockLLMClient
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage import repositories as repo
from evidence_agent.storage.migrate import ensure_db
from evidence_agent.tools.candidates import CandidateRegistry


def run_e0(
    *,
    root: Path,
    project_id: str,
    question: str,
    client: LLMClient | None = None,
    conn=None,
    run_id: str | None = None,
    allow_web: bool = False,
    web_mode: str = "off",
    budget: BudgetState | None = None,
    embedder=None,
    reranker=None,
    max_steps: int = 24,
    policy_adapter_id: str | None = None,
) -> dict[str, Any]:
    """Product E0 surface for fair comparison probes (same protocol as worker loop)."""
    close_conn = False
    if conn is None:
        ensure_db(root)
        conn = connect(root)
        close_conn = True
    client = client or HttpLLMClient()
    budget = budget or BudgetState(cfg=BudgetConfig())
    try:
        versions = repo.list_project_version_ids(conn, project_id)
        if run_id is None:
            run_id, _ = repo.create_run(
                conn,
                project_id=project_id,
                question=question,
                allow_web=allow_web,
                budget_profile="standard",
                budget={"tool_calls": budget.cfg.tool_calls},
                idempotency_key=None,
                request_hash=None,
                version_set=versions,
            )
        retriever = HybridRetriever(
            root,
            project_id,
            embedder=embedder or HashEmbedder(dim=32),
            reranker=reranker or LexicalReranker(),
        )
        out = run_agent_loop(
            root=root,
            conn=conn,
            run_id=run_id,
            project_id=project_id,
            question=question,
            client=client,
            allow_web=allow_web,
            web_mode=web_mode,
            budget=budget,
            registry=CandidateRegistry(),
            retriever=retriever,
            max_steps=max_steps,
            policy_adapter_id=policy_adapter_id,
        )
        out = dict(out or {})
        out["run_id"] = run_id
        out["system"] = "E0"
        out["memory_mode"] = "evidence_ledger_packed"
        # Ensure finalize already ran inside loop; refresh result tag
        conn.execute(
            "UPDATE runs SET result_json = ? WHERE id = ?",
            (json.dumps(out, ensure_ascii=False), run_id),
        )
        conn.commit()
        return out
    finally:
        if close_conn:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="E0 controlled-loop baseline")
    p.add_argument("--project-id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--mock", action="store_true")
    args = p.parse_args(argv)
    root = work_root()
    if args.mock:
        client: LLMClient = MockLLMClient(
            responses=[
                json.dumps(
                    {
                        "action": "abstain",
                        "query": None,
                        "candidate_id": None,
                        "reason_code": "missing_source",
                    }
                ),
                json.dumps({"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["mock"]}),
                json.dumps({"results": []}),
            ]
        )
    else:
        client = HttpLLMClient()
    out = run_e0(root=root, project_id=args.project_id, question=args.question, client=client)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
