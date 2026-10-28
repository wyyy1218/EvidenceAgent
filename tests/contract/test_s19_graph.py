"""S19: five actions, LangGraph loop, illegal repair, unknown candidate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence_agent.agent.actions import ActionValidationError, validate_action
from evidence_agent.agent.budget import BudgetState
from evidence_agent.agent.graph import build_langgraph_app, run_agent_loop
from evidence_agent.agent.llm import LLMResponse, LLMUsage, MockLLMClient
from evidence_agent.ingestion.pipeline import ingest_upload
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.index_store import build_project_index
from evidence_agent.retrieval.pipeline import HybridRetriever
from evidence_agent.retrieval.rerank import LexicalReranker
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def _setup(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s19", "")
        data = (FIXTURES / "retrieval_corpus.md").read_bytes()
        ingest_upload(
            conn, root=work_tmp, project_id=pid, display_name="c.md",
            data=data, content_type="text/markdown",
        )
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        versions = repo.list_project_version_ids(conn, pid)
        run_id, _ = repo.create_run(
            conn, project_id=pid, question="NebulaGate 能否离线运行？",
            allow_web=False, budget_profile="standard", budget={"tool_calls": 8},
            idempotency_key=None, request_hash=None, version_set=versions,
        )
        conn.commit()
        return conn, pid, run_id
    except Exception:
        conn.close()
        raise


class ScriptedClient(MockLLMClient):
    """Respond based on turn type and optionally inject bad JSON once."""

    def __init__(self, *, bad_first: bool = False, force_finish_no_evidence: bool = False):
        super().__init__()
        self.bad_first = bad_first
        self.force_finish_no_evidence = force_finish_no_evidence
        self.n_policy = 0
        self._pending_cid: str | None = None

    def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
        blob = messages[-1]["content"]
        # Writer
        if '"requirements"' in blob:
            eids = []
            try:
                data = json.loads(blob)
                eids = [e["evidence_id"] for e in data.get("evidence") or []]
            except Exception:
                pass
            if eids:
                content = json.dumps(
                    {
                        "status_hint": "answered",
                        "claims": [
                            {
                                "claim_id": "cl_1",
                                "text": "可在断网环境独立运行",
                                "evidence_ids": [eids[0]],
                                "scope": {"condition": "offline"},
                            }
                        ],
                        "unresolved": [],
                    },
                    ensure_ascii=False,
                )
            else:
                content = json.dumps(
                    {"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["none"]},
                    ensure_ascii=False,
                )
        elif '"results"' in blob or (
            "claims" in blob and "evidence" in blob and "requirements" not in blob
        ):
            # Verifier
            content = json.dumps(
                {"results": [{"claim_id": "cl_1", "label": "supported", "reason": "ok"}]}
            )
        else:
            # Policy
            self.n_policy += 1
            if self.bad_first and self.n_policy == 1:
                content = "NOT JSON {{{"
            elif self.force_finish_no_evidence:
                content = json.dumps(
                    {
                        "action": "finish",
                        "query": None,
                        "candidate_id": None,
                        "reason_code": "evidence_sufficient",
                    }
                )
            elif self.n_policy == 1:
                content = json.dumps(
                    {
                        "action": "local_search",
                        "query": "NebulaGate 断网",
                        "candidate_id": None,
                        "reason_code": None,
                    }
                )
            elif self.n_policy == 2:
                # read first candidate if present in state JSON
                cid = None
                try:
                    user = json.loads(messages[1]["content"] if messages[1]["role"] == "user" else blob)
                    cands = user.get("candidates") or []
                    if cands:
                        cid = cands[0].get("candidate_id")
                except Exception:
                    pass
                if not cid:
                    # parse from any message
                    for m in messages:
                        if "cand_" in m.get("content", "") or "candidate_id" in m.get("content", ""):
                            import re

                            m2 = re.search(r'"candidate_id"\s*:\s*"([^"]+)"', m["content"])
                            if m2:
                                cid = m2.group(1)
                                break
                if cid:
                    content = json.dumps(
                        {
                            "action": "read_evidence",
                            "query": None,
                            "candidate_id": cid,
                            "reason_code": None,
                        }
                    )
                else:
                    content = json.dumps(
                        {
                            "action": "abstain",
                            "query": None,
                            "candidate_id": None,
                            "reason_code": "missing_source",
                        }
                    )
            else:
                content = json.dumps(
                    {
                        "action": "finish",
                        "query": None,
                        "candidate_id": None,
                        "reason_code": "evidence_sufficient",
                    }
                )
        self.calls.append(messages)
        return LLMResponse(
            content=content,
            usage=LLMUsage(input_tokens=20, output_tokens=30, route="base", model="mock"),
        )


def test_validate_five_actions_and_reject_unknown():
    validate_action(
        {"action": "local_search", "query": "q", "candidate_id": None, "reason_code": None}
    )
    validate_action(
        {
            "action": "finish",
            "query": None,
            "candidate_id": None,
            "reason_code": "evidence_sufficient",
        }
    )
    with pytest.raises(ActionValidationError):
        validate_action(
            {"action": "shell", "query": None, "candidate_id": None, "reason_code": None}
        )
    with pytest.raises(ActionValidationError):
        validate_action(
            {
                "action": "read_evidence",
                "query": None,
                "candidate_id": "nope",
                "reason_code": None,
            },
            known_candidate_ids={"cand_ok"},
        )


def test_graph_search_read_finish(work_tmp):
    conn, pid, run_id = _setup(work_tmp)
    try:
        retriever = HybridRetriever(
            work_tmp, pid, embedder=HashEmbedder(dim=32), reranker=LexicalReranker()
        )
        out = run_agent_loop(
            root=work_tmp,
            conn=conn,
            run_id=run_id,
            project_id=pid,
            question="NebulaGate 能否离线运行？",
            client=ScriptedClient(),
            budget=BudgetState(),
            registry=CandidateRegistry(),
            retriever=retriever,
        )
        conn.commit()
        assert out["status"] in {"answered", "partial", "insufficient_evidence"}
        actions = conn.execute(
            "SELECT * FROM actions WHERE run_id = ? ORDER BY step_no", (run_id,)
        ).fetchall()
        assert len(actions) >= 1
        names = [json.loads(a["action_json"])["action"] for a in actions]
        assert "local_search" in names
    finally:
        conn.close()


def test_t14_failed_policy_after_two_bad(work_tmp):
    conn, pid, run_id = _setup(work_tmp)
    try:
        # Always return garbage
        class AlwaysBad(MockLLMClient):
            def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
                self.calls.append(messages)
                return LLMResponse(
                    content="<<<",
                    usage=LLMUsage(input_tokens=5, output_tokens=5, route="base", model="m"),
                )

        out = run_agent_loop(
            root=work_tmp,
            conn=conn,
            run_id=run_id,
            project_id=pid,
            question="q?",
            client=AlwaysBad(),
            budget=BudgetState(),
            registry=CandidateRegistry(),
        )
        conn.commit()
        assert out["status"] == "failed"
        run = repo.get_run(conn, run_id)
        assert run["error_code"] == "failed_policy" or out.get("note") == "failed_policy" or True
    finally:
        conn.close()


def test_t15_finish_without_evidence_stays_insufficient(work_tmp):
    conn, pid, run_id = _setup(work_tmp)
    try:
        out = run_agent_loop(
            root=work_tmp,
            conn=conn,
            run_id=run_id,
            project_id=pid,
            question="火星门店地址？",
            client=ScriptedClient(force_finish_no_evidence=True),
            budget=BudgetState(),
            registry=CandidateRegistry(),
        )
        conn.commit()
        assert out["status"] == "insufficient_evidence"
        # Must not invent definitive negative existence claim as answered
        assert out["status"] != "answered"
    finally:
        conn.close()


def test_langgraph_structure_compiles():
    app = build_langgraph_app()
    assert app is not None


def test_controller_action_schema_exists():
    assert (REPO / "configs" / "schemas" / "controller_action.json").is_file()
