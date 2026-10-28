"""S22: B0/B1/B2/E0 fair comparison on shared fixture (mock LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baselines.deepagents_research import deepagents_available, run_b2  # noqa: E402
from baselines.e0_runner import run_e0  # noqa: E402
from baselines.react import run_b1  # noqa: E402
from baselines.static_rag import run_b0  # noqa: E402
from evidence_agent.agent.llm import LLMResponse, LLMUsage, MockLLMClient  # noqa: E402
from evidence_agent.ingestion.pipeline import ingest_upload  # noqa: E402
from evidence_agent.retrieval.dense import HashEmbedder  # noqa: E402
from evidence_agent.retrieval.index_store import build_project_index  # noqa: E402
from evidence_agent.storage.db import connect  # noqa: E402
from evidence_agent.storage import repositories as repo  # noqa: E402


def _setup(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s22", "")
        data = (FIXTURES / "retrieval_corpus.md").read_bytes()
        ingest_upload(
            conn,
            root=work_tmp,
            project_id=pid,
            display_name="retrieval_corpus.md",
            data=data,
            content_type="text/markdown",
        )
        build_project_index(conn, root=work_tmp, project_id=pid, embedder=HashEmbedder(dim=32))
        conn.commit()
        return pid
    finally:
        conn.close()


class PolicyThenWriteMock(MockLLMClient):
    """Shared scripted client: policy search→read→finish, then writer/verifier."""

    def __init__(self):
        super().__init__()
        self.n_policy = 0

    def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
        blob = messages[-1]["content"]
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
        elif "claims" in blob and "requirements" not in blob:
            content = json.dumps(
                {"results": [{"claim_id": "cl_1", "label": "supported", "reason": "ok"}]}
            )
        else:
            self.n_policy += 1
            if self.n_policy == 1:
                content = json.dumps(
                    {
                        "action": "local_search",
                        "query": "NebulaGate 断网",
                        "candidate_id": None,
                        "reason_code": None,
                    }
                )
            elif self.n_policy == 2:
                import re

                cid = None
                for m in messages:
                    m2 = re.search(r'"candidate_id"\s*:\s*"([^"]+)"', m.get("content", ""))
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
            usage=LLMUsage(input_tokens=10, output_tokens=20, latency_ms=1, model="mock", route="base"),
        )


class B2Mock(MockLLMClient):
    def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
        blob = messages[-1]["content"]
        sys_msg = (messages[0].get("content") or "") if messages else ""
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
                            }
                        ],
                        "unresolved": [],
                    },
                    ensure_ascii=False,
                )
            else:
                content = json.dumps(
                    {"status_hint": "insufficient_evidence", "claims": [], "unresolved": ["x"]}
                )
        elif "claims" in blob and "requirements" not in blob:
            content = json.dumps(
                {"results": [{"claim_id": "cl_1", "label": "supported", "reason": "ok"}]}
            )
        elif "Synthesize" in sys_msg:
            content = json.dumps({"ok": True})
        elif "subtasks" in sys_msg or "delegate research" in sys_msg.lower() or "Plan" in sys_msg:
            content = json.dumps({"subtasks": ["NebulaGate 断网"]})
        elif "sub-agent" in sys_msg or "research sub" in sys_msg.lower():
            content = json.dumps(
                {
                    "actions": [
                        {"action": "local_search", "query": "NebulaGate 断网", "candidate_id": None}
                    ]
                }
            )
        else:
            content = json.dumps({"subtasks": ["NebulaGate 断网"]})
        self.calls.append(messages)
        return LLMResponse(
            content=content,
            usage=LLMUsage(input_tokens=8, output_tokens=12, latency_ms=1, model="mock", route="base"),
        )


def _assert_usage(out: dict):
    usage = out.get("usage") or {}
    assert "input_tokens" in usage or "logical_tool_calls" in usage
    # Must not undercount: at least some token or tool accounting present
    assert (
        usage.get("logical_tool_calls", 0) > 0
        or usage.get("tool_calls", 0) > 0
        or usage.get("input_tokens", 0) > 0
        or usage.get("event_count", 0) > 0
    )


def test_b0_system_tag(work_tmp):
    pid = _setup(work_tmp)
    out = run_b0(
        root=work_tmp,
        project_id=pid,
        question="方案甲能否断网运行？",
        client=PolicyThenWriteMock(),
        embedder=HashEmbedder(dim=32),
    )
    assert out["system"] == "B0"
    _assert_usage(out)


def test_b1_rolling_history(work_tmp):
    pid = _setup(work_tmp)
    out = run_b1(
        root=work_tmp,
        project_id=pid,
        question="方案甲能否断网运行？",
        client=PolicyThenWriteMock(),
        embedder=HashEmbedder(dim=32),
    )
    assert out["system"] == "B1"
    assert out.get("memory_mode") == "rolling_history"
    assert "source_log" in out
    # B1 must not claim packed evidence mode
    assert out.get("memory_mode") != "evidence_ledger_packed"
    _assert_usage(out)
    assert out["status"] in {"answered", "partial", "insufficient_evidence"}


def test_e0_packed(work_tmp):
    pid = _setup(work_tmp)
    out = run_e0(
        root=work_tmp,
        project_id=pid,
        question="方案甲能否断网运行？",
        client=PolicyThenWriteMock(),
        embedder=HashEmbedder(dim=32),
    )
    assert out["system"] == "E0"
    assert out.get("memory_mode") == "evidence_ledger_packed"
    _assert_usage(out)


def test_b2_adapter_metering(work_tmp):
    pid = _setup(work_tmp)
    out = run_b2(
        root=work_tmp,
        project_id=pid,
        question="方案甲能否断网运行？",
        client=B2Mock(),
        embedder=HashEmbedder(dim=32),
    )
    assert out["system"] == "B2"
    assert out["adapter"] == "deep_research_adapter"
    assert out["upstream"]["commit"]
    meter = out["b2_meter"]
    assert meter["orchestrator_llm_calls"] >= 1
    assert meter["subagent_llm_calls"] >= 1
    assert meter["subtask_count"] >= 1
    assert meter["total_llm_calls"] == meter["orchestrator_llm_calls"] + meter["subagent_llm_calls"]
    # Must not be an E0 alias
    assert out.get("memory_mode") == "deep_research_subagents"
    _assert_usage(out)


def test_four_systems_protocol_fields(work_tmp):
    """Same question → all four systems expose comparable protocol fields."""
    pid = _setup(work_tmp)
    q = "方案甲能否断网运行？"
    results = {
        "B0": run_b0(root=work_tmp, project_id=pid, question=q, client=PolicyThenWriteMock()),
        "B1": run_b1(root=work_tmp, project_id=pid, question=q, client=PolicyThenWriteMock()),
        "B2": run_b2(root=work_tmp, project_id=pid, question=q, client=B2Mock()),
        "E0": run_e0(root=work_tmp, project_id=pid, question=q, client=PolicyThenWriteMock()),
    }
    for sid, out in results.items():
        assert out["system"] == sid
        assert "status" in out
        assert "usage" in out
        assert "run_id" in out


def test_deepagents_availability_recorded():
    # Availability is informational; adapter must run either way
    assert isinstance(deepagents_available(), bool)
