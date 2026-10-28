"""S20: hard budget — reserve, tool=0, timeout, billing_unknown (T12/T13/T16)."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.graph import run_agent_loop
from evidence_agent.agent.llm import LLMResponse, LLMUsage, MockLLMClient
from evidence_agent.agent.usage_ledger import UsageLedger
from evidence_agent.ingestion.pipeline import ingest_upload
from evidence_agent.retrieval.dense import HashEmbedder
from evidence_agent.retrieval.index_store import build_project_index
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_t13_tool_budget_zero_no_dispatch(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s20", "")
        data = (FIXTURES / "retrieval_corpus.md").read_bytes()
        ingest_upload(
            conn, root=work_tmp, project_id=pid, display_name="c.md",
            data=data, content_type="text/markdown",
        )
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        versions = repo.list_project_version_ids(conn, pid)
        run_id, _ = repo.create_run(
            conn, project_id=pid, question="q?", allow_web=False,
            budget_profile="standard", budget={}, idempotency_key=None,
            request_hash=None, version_set=versions,
        )
        conn.commit()

        class FinishOnly(MockLLMClient):
            def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
                blob = messages[-1]["content"]
                if '"requirements"' in blob:
                    content = json.dumps(
                        {"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["none"]}
                    )
                elif "results" in blob and "requirements" not in blob and '"action"' not in blob:
                    content = json.dumps({"results": []})
                else:
                    # Would want to search — but if somehow called for policy asking tools
                    content = json.dumps(
                        {
                            "action": "local_search",
                            "query": "x",
                            "candidate_id": None,
                            "reason_code": None,
                        }
                    )
                self.calls.append(messages)
                return LLMResponse(
                    content=content,
                    usage=LLMUsage(input_tokens=5, output_tokens=5, route="base", model="m"),
                )

        # Actually with tool_calls=0, policy may request search but dispatch must block
        class WantSearch(FinishOnly):
            def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
                blob = messages[-1]["content"]
                if '"requirements"' in blob:
                    content = json.dumps(
                        {"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["tb0"]}
                    )
                else:
                    content = json.dumps(
                        {
                            "action": "local_search",
                            "query": "NebulaGate",
                            "candidate_id": None,
                            "reason_code": None,
                        }
                    )
                self.calls.append(messages)
                return LLMResponse(
                    content=content,
                    usage=LLMUsage(input_tokens=5, output_tokens=5, route="base", model="m"),
                )

        budget = BudgetState(cfg=BudgetConfig(tool_calls=0, final_output_reserve=1536))
        out = run_agent_loop(
            root=work_tmp,
            conn=conn,
            run_id=run_id,
            project_id=pid,
            question="q?",
            client=WantSearch(),
            budget=budget,
            registry=CandidateRegistry(),
        )
        conn.commit()
        actions = conn.execute(
            "SELECT action_json FROM actions WHERE run_id = ?", (run_id,)
        ).fetchall()
        # No successful tool side-effect: either no local_search result rows with ok,
        # or dispatch blocked before tool — tool_calls_used stays 0
        assert budget.tool_calls_used == 0
        assert out["status"] in {"insufficient_evidence", "partial", "timeout", "failed"}
    finally:
        conn.close()


def test_t12_reserve_blocks_new_retrieval():
    b = BudgetState(
        cfg=BudgetConfig(tool_calls=8, output_tokens=1600, final_output_reserve=1536)
    )
    # Spend almost all non-reserve output
    b.record_tokens(output_tokens=100)
    ok, reason = b.can_call_tool()
    assert not ok
    assert reason == "output_reserve_blocked"
    # Final writer still allowed
    ok2, _ = b.can_call_model(max_input=100, max_output=700, is_final_writer_or_verifier=True)
    assert ok2


def test_check_before_call_not_after():
    b = BudgetState(cfg=BudgetConfig(tool_calls=1))
    ok, _ = b.can_call_tool()
    assert ok
    b.record_tool()
    ok2, reason = b.can_call_tool()
    assert not ok2
    assert reason == "tool_budget_exhausted"


def test_cache_hit_still_counts_logical(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s20c", "")
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="q",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        ledger = UsageLedger(run_id=run_id)
        ledger.add(
            conn,
            kind="local_search",
            logical_tool_call=True,
            physical_request=False,
            cache_hit=True,
        )
        conn.commit()
        assert ledger.logical_tool_calls == 1
        assert ledger.physical_requests == 0
        assert ledger.cache_hits == 1
        s = ledger.summary()
        assert s["logical_tool_calls"] == 1
    finally:
        conn.close()


def test_t16_billing_unknown_conservative():
    ledger = UsageLedger(run_id="run_y")
    ledger.add(
        None,
        kind="web_search",
        logical_tool_call=True,
        physical_request=True,
        billing_status="billing_unknown",
        credits=1.0,  # conservative reserve
        persist=False,
    )
    assert ledger.billing_unknown_count == 1
    assert ledger.api_credits == 1.0


def test_budget_snapshot_summable():
    b = BudgetState()
    b.record_tool()
    b.record_tokens(input_tokens=10, output_tokens=5)
    snap = b.snapshot()
    assert snap["tool_calls_used"] == 1
    assert snap["input_tokens_used"] == 10
    assert snap["output_tokens_used"] == 5
