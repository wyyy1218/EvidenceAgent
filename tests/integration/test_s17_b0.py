"""S17: Writer/Verifier shared path + B0 static RAG (mock LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from baselines.static_rag import run_b0  # noqa: E402
from evidence_agent.agent.llm import MockLLMClient, load_prompt  # noqa: E402
from evidence_agent.agent.requirements import extract_requirements  # noqa: E402
from evidence_agent.agent.result import decide_status  # noqa: E402
from evidence_agent.ingestion.pipeline import ingest_upload  # noqa: E402
from evidence_agent.retrieval.dense import HashEmbedder  # noqa: E402
from evidence_agent.retrieval.index_store import build_project_index  # noqa: E402
from evidence_agent.storage.db import connect  # noqa: E402
from evidence_agent.storage import repositories as repo  # noqa: E402


def _setup_project(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s17", "")
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


def test_prompts_match_appendix_c():
    w = load_prompt("writer")
    v = load_prompt("verifier")
    assert "evidence_ids" in w
    assert "insufficient_evidence" in w
    assert "supported" in v
    assert "参数记忆" in v or "记忆" in v


def test_requirements_reject_gold():
    import pytest

    with pytest.raises(ValueError, match="gold_leak"):
        extract_requirements("q?", extra_context={"gold_answer": "secret"})


def test_b0_answered_with_mock(work_tmp):
    pid = _setup_project(work_tmp)
    # First call Writer, second Verifier — but we need evidence_id from registration.
    # Use a two-phase mock: Writer returns claim with placeholder; we'll patch after...
    # Simpler: custom client that inspects messages.

    class SmartMock(MockLLMClient):
        def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
            from evidence_agent.agent.llm import LLMResponse, LLMUsage

            blob = messages[-1]["content"]
            # Writer payload always includes requirements; verifier does not.
            if '"requirements"' in blob:
                data = json.loads(blob)
                eids = [e["evidence_id"] for e in data.get("evidence") or []]
                if eids:
                    content = json.dumps(
                        {
                            "status_hint": "answered",
                            "claims": [
                                {
                                    "claim_id": "cl_1",
                                    "requirement_id": "req_main",
                                    "text": "NebulaGate 可在断网环境独立运行",
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
                        {
                            "status_hint": "insufficient_evidence",
                            "claims": [],
                            "unresolved": ["no_evidence"],
                        }
                    )
            else:
                data = json.loads(blob)
                cid = (data.get("claims") or [{}])[0].get("claim_id", "cl_1")
                content = json.dumps(
                    {
                        "results": [
                            {
                                "claim_id": cid,
                                "label": "supported",
                                "reason": "quote supports claim",
                            }
                        ]
                    }
                )
            self.calls.append(messages)
            return LLMResponse(
                content=content,
                usage=LLMUsage(
                    input_tokens=10, output_tokens=20, latency_ms=1, model="mock-base", route="base"
                ),
            )

    out = run_b0(
        root=work_tmp,
        project_id=pid,
        question="方案甲能否断网运行？",
        client=SmartMock(),
        embedder=HashEmbedder(dim=32),
        reranker=None,
    )
    assert out["system"] == "B0"
    assert out["route"] == "base"
    assert out["status"] in {"answered", "partial"}
    assert out["evidence_ids"]
    assert out["usage"]["tool_calls"] >= 1


def test_b0_u05_insufficient(work_tmp):
    pid = _setup_project(work_tmp)

    class EmptyWriter(MockLLMClient):
        def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
            from evidence_agent.agent.llm import LLMResponse, LLMUsage

            blob = messages[-1]["content"]
            if '"requirements"' in blob:
                content = json.dumps(
                    {
                        "status_hint": "insufficient_evidence",
                        "claims": [],
                        "unresolved": ["资料中无此信息"],
                    },
                    ensure_ascii=False,
                )
            else:
                content = json.dumps({"results": []})
            self.calls.append(messages)
            return LLMResponse(
                content=content,
                usage=LLMUsage(
                    input_tokens=5, output_tokens=5, latency_ms=1, model="mock-base", route="base"
                ),
            )

    out = run_b0(
        root=work_tmp,
        project_id=pid,
        question="火星上的NebulaGate门店地址是什么？",
        client=EmptyWriter(),
    )
    assert out["status"] == "insufficient_evidence"
    assert "不存在" not in (out.get("answer") or "") or "不等于不存在" in (out.get("answer") or "")


def test_decide_status_conflict():
    st = decide_status(
        claims=[{"claim_id": "a", "text": "x"}],
        unresolved=[],
        verification=[{"claim_id": "a", "label": "conflicting"}],
    )
    assert st == "conflicting_evidence"


def test_schema_files_exist():
    assert (REPO / "configs" / "schemas" / "writer_output.json").is_file()
    assert (REPO / "configs" / "schemas" / "verifier_output.json").is_file()
    assert (REPO / "baselines" / "static_rag.py").is_file()
