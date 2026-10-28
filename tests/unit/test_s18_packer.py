"""S18: visible state packer — length, gold isolation, determinism (T21)."""
from __future__ import annotations

import pytest

from evidence_agent.agent.packer import PackRejectError, pack_visible_state
from evidence_agent.agent.state import VisibleState, assert_no_gold


def _base_state(**kwargs) -> VisibleState:
    data = dict(
        question="NebulaGate 离线能否运行？",
        requirements=[{"requirement_id": "req_main", "text": "NebulaGate 离线能否运行？"}],
        project_id="proj_1",
        snapshot_set_id="snap_1",
        budget={"tool_calls_left": 5, "output_tokens_left": 2000},
        evidence_cards=[],
        candidates=[],
        recent_actions=[],
    )
    data.update(kwargs)
    return VisibleState(**data)


def test_determinism():
    st = _base_state(
        evidence_cards=[
            {"evidence_id": "ev_1", "quote": "可在断网环境中独立运行", "source_version_id": "src_1"}
        ]
    )
    a = pack_visible_state(st)
    b = pack_visible_state(st)
    assert a.messages == b.messages
    assert a.state_hash == b.state_hash
    assert a.prompt_tokens == b.prompt_tokens


def test_gold_leak_blocked():
    with pytest.raises(ValueError, match="gold_leak"):
        assert_no_gold({"question": "q", "gold_answer": "secret"})
    st = _base_state()
    # Inject gold into candidates — pack must refuse
    st.candidates = [{"candidate_id": "c1", "gold_support": "x"}]
    with pytest.raises(ValueError, match="gold_leak"):
        pack_visible_state(st)


def test_t21_truncate_keeps_question_and_ids():
    cards = [
        {
            "evidence_id": f"ev_{i}",
            "quote": ("精确版本 v2.4.1 与数字 60 " * 40),
            "source_version_id": f"src_{i}",
        }
        for i in range(20)
    ]
    cands = [{"candidate_id": f"cand_{i}", "preview": "x" * 200} for i in range(30)]
    acts = [{"step_no": i, "action": "local_search", "query": f"q{i}"} for i in range(20)]
    st = _base_state(evidence_cards=cards, candidates=cands, recent_actions=acts)
    packed = pack_visible_state(st, prompt_max=800)
    assert packed.truncated is True
    user = packed.messages[1]["content"]
    assert "NebulaGate" in user
    assert "tool_calls_left" in user or "budget" in user
    # IDs retained somehow (in body or dropped_ids)
    assert packed.dropped_ids["evidence_ids"] or packed.dropped_ids["candidate_ids"]
    assert packed.prompt_tokens <= 800


def test_reject_oversized_negation_question():
    huge = "不要使用外网。" + ("详细背景。" * 5000)
    st = _base_state(question=huge, requirements=[{"requirement_id": "req_main", "text": huge}])
    with pytest.raises(PackRejectError):
        pack_visible_state(st, prompt_max=200)


def test_open_gaps_marked_suggestion():
    st = _base_state(open_gaps=[{"requirement_id": "req_main", "note": "maybe missing"}])
    packed = pack_visible_state(st)
    assert "open_gaps_is_suggestion_not_truth" in packed.messages[1]["content"]
