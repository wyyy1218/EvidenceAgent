"""B0: static hybrid retrieval → Top-6 read → fixed Writer/Verifier."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow running as script from repo root
_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.agent.answer_pipeline import produce_answer
from evidence_agent.agent.llm import HttpLLMClient, LLMClient, MockLLMClient
from evidence_agent.evidence.ledger import register_from_read
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage import repositories as repo
from evidence_agent.storage.migrate import ensure_db
from evidence_agent.tools.candidates import CandidateRegistry
from evidence_agent.tools.local_search import local_search
from evidence_agent.tools.read_evidence import read_evidence
from evidence_agent.tools.types import ToolStatus


def run_b0(
    *,
    root: Path,
    project_id: str,
    question: str,
    client: LLMClient | None = None,
    conn=None,
    run_id: str | None = None,
    top_k: int = 6,
    embedder=None,
    reranker=None,
) -> dict[str, Any]:
    """Execute static RAG baseline. Internal reads are metered as tool calls."""
    close_conn = False
    if conn is None:
        ensure_db(root)
        conn = connect(root)
        close_conn = True
    client = client or HttpLLMClient()
    usage: dict[str, Any] = {
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "logical_tool_calls": 0,
        "physical_requests": 0,
    }
    try:
        versions = repo.list_project_version_ids(conn, project_id)
        if run_id is None:
            run_id, _ = repo.create_run(
                conn,
                project_id=project_id,
                question=question,
                allow_web=False,
                budget_profile="standard",
                budget={"tool_calls": 8},
                idempotency_key=None,
                request_hash=None,
                version_set=versions,
            )

        reg = CandidateRegistry()
        retriever = HybridRetriever(
            root,
            project_id,
            embedder=embedder or HashEmbedder(dim=32),
            reranker=reranker or LexicalReranker(),
        )
        search = local_search(
            root=root,
            project_id=project_id,
            run_id=run_id,
            query=question,
            retriever=retriever,
            registry=reg,
        )
        usage["tool_calls"] += 1
        usage["logical_tool_calls"] += 1
        usage["physical_requests"] += 1

        evidence_cards: list[dict[str, Any]] = []
        if search.status == ToolStatus.OK:
            cands = (search.data.get("candidates") or [])[:top_k]
            for cand in cands:
                read = read_evidence(
                    candidate_id=cand["candidate_id"],
                    run_id=run_id,
                    project_id=project_id,
                    root=root,
                    registry=reg,
                    authorized_version_ids=versions,
                )
                usage["tool_calls"] += 1
                usage["logical_tool_calls"] += 1
                usage["physical_requests"] += 1
                if read.status != ToolStatus.OK:
                    continue
                rec = register_from_read(
                    conn,
                    root=root,
                    run_id=run_id,
                    project_id=project_id,
                    tool_result=read,
                    authorized_version_ids=versions,
                )
                evidence_cards.append(rec.to_dict())

        result = produce_answer(
            client,
            conn=conn,
            root=root,
            run_id=run_id,
            project_id=project_id,
            question=question,
            evidence_cards=evidence_cards,
            authorized_version_ids=versions,
            usage_acc=usage,
        )
        out = result.to_dict()
        out["run_id"] = run_id
        out["system"] = "B0"
        repo.finalize_run(
            conn,
            run_id,
            status=result.status,
            result=out,
        )
        conn.commit()
        return out
    finally:
        if close_conn:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="B0 static RAG baseline")
    p.add_argument("--project-id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--mock", action="store_true")
    args = p.parse_args(argv)
    root = work_root()
    client: LLMClient
    if args.mock:
        client = MockLLMClient(
            responses=[
                json.dumps(
                    {
                        "status_hint": "insufficient_evidence",
                        "claims": [],
                        "unresolved": ["mock_mode"],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
    else:
        client = HttpLLMClient()
    out = run_b0(root=root, project_id=args.project_id, question=args.question, client=client)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
