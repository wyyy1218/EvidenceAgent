"""Smoke: formal system dispatch imports and B0 static path on a tiny fake case."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training" / "sft"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from formal_systems import run_formal_case  # noqa: E402
from dev_harness import TaskCase  # noqa: E402


class _FakeUsage:
    def __init__(self):
        self.model = "mock"
        self.input_tokens = 1
        self.output_tokens = 1
        self.route = "mock"


class _FakeClient:
    def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
        # Writer path: requirements present → empty claims
        blob = messages[-1]["content"] if messages else ""
        if "claims" in blob and "requirements" not in blob:
            content = '{"results":[]}'
        elif '"requirements"' in blob or "evidence" in blob.lower():
            content = '{"status_hint":"insufficient_evidence","claims":[],"unresolved":["none"]}'
        else:
            content = (
                '{"action":"finish","query":null,"candidate_id":null,"reason_code":"enough"}'
            )
        return SimpleNamespace(content=content, usage=_FakeUsage())


def test_dispatch_b0_empty_sections(tmp_path: Path):
    case = TaskCase(
        dataset="chinese",
        task={
            "task_id": "zh_fake_001",
            "question": "测试问题？",
            "requirements": [{"requirement_id": "req_main", "text": "测试"}],
            "allowed_snapshot_ids": ["doc_a"],
            "project": "fake",
            "web_mode": "off",
        },
        gold={"task_id": "zh_fake_001", "gold_support_spans": []},
        sections=[],
        allow_web=False,
    )
    out = run_formal_case(
        root=tmp_path,
        case=case,
        client=_FakeClient(),
        system="b0",
        policy_adapter_id=None,
    )
    assert out["system"] == "b0"
    assert out["task_id"] == "zh_fake_001"
    assert "status" in out
