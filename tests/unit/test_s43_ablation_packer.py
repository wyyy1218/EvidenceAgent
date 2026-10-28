"""S43 ablation variants: policy-visible only; hard budget unchanged."""
from __future__ import annotations

import json

from evidence_agent.agent.budget import BudgetConfig, BudgetState
from evidence_agent.agent.packer import (
    ABLATION_HIDE_VISIBLE_BUDGET,
    ABLATION_NO_SOURCE_ANCHOR,
    pack_visible_state,
)
from evidence_agent.agent.state import VisibleState


def _state() -> VisibleState:
    return VisibleState(
        question="NebulaGate 离线能否运行？",
        requirements=[{"requirement_id": "req_main", "text": "NebulaGate 离线能否运行？"}],
        project_id="proj_1",
        snapshot_set_id="snap_1",
        budget={"tool_calls_left": 5, "output_tokens_left": 2000, "remaining_wall_seconds": 100},
        evidence_cards=[
            {
                "evidence_id": "ev_1",
                "source_version_id": "src_1",
                "page": 3,
                "title": "手册",
                "quote": "可在断网环境中独立运行",
                "scope": {},
            }
        ],
        candidates=[
            {
                "candidate_id": "cand_1",
                "title": "手册",
                "preview": "离线部署说明",
                "source_version_id": "src_1",
            }
        ],
        recent_actions=[],
    )


def test_no_source_anchor_strips_ids_keeps_summary():
    packed = pack_visible_state(_state(), ablation_variant=ABLATION_NO_SOURCE_ANCHOR)
    body = json.loads(packed.messages[1]["content"])
    assert "budget" in body
    ev = body["evidence_cards"][0]
    assert "evidence_id" not in ev
    assert "page" not in ev
    assert "source_version_id" not in ev
    assert ev.get("anchor_removed") is True
    assert "独立运行" in (ev.get("summary") or "")
    cand = body["candidates"][0]
    assert "candidate_id" not in cand
    assert cand.get("anchor_removed") is True


def test_hide_visible_budget_omits_budget_field():
    packed = pack_visible_state(_state(), ablation_variant=ABLATION_HIDE_VISIBLE_BUDGET)
    body = json.loads(packed.messages[1]["content"])
    assert "budget" not in body
    assert body.get("budget_hidden") is True
    # Anchors remain for this variant
    assert body["evidence_cards"][0].get("evidence_id") == "ev_1"


def test_hard_budget_still_enforced_with_hide_variant():
    cfg = BudgetConfig(tool_calls=2)
    st = BudgetState(cfg=cfg)
    st.tool_calls_used = 2
    ok, reason = st.can_call_tool()
    assert ok is False
    assert reason == "tool_budget_exhausted"
    # Packing without budget does not relax executor
    packed = pack_visible_state(_state(), ablation_variant=ABLATION_HIDE_VISIBLE_BUDGET)
    assert "budget" not in json.loads(packed.messages[1]["content"])
