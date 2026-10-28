"""S36 preference labeling unit checks (no GPU)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training" / "preferences"))

from label_rules import decide_preference, normalized_cost, review_agreement  # noqa: E402


def test_quality_rule_prefers_higher_q():
    r = decide_preference(
        {"q": 0.8, "g": 0.9, "c": 1.0},
        {"q": 0.6, "g": 0.9, "c": 0.5},
    )
    assert r["status"] == "keep" and r["chosen"] == "a" and r["reason"] == "quality"


def test_g_drop_blocks_quality_win():
    r = decide_preference(
        {"q": 0.9, "g": 0.5, "c": 1.0},
        {"q": 0.7, "g": 0.9, "c": 1.0},
    )
    assert r["status"] == "discard"


def test_cost_rule_requires_close_qg():
    r = decide_preference(
        {"q": 0.50, "g": 0.80, "c": 0.50},
        {"q": 0.51, "g": 0.81, "c": 0.80},
    )
    assert r["status"] == "keep" and r["chosen"] == "a" and r["reason"] == "cost"


def test_forged_cannot_win_on_cost():
    r = decide_preference(
        {"q": 0.50, "g": 0.80, "c": 0.40, "forged_confident_on_insufficient": True},
        {"q": 0.50, "g": 0.80, "c": 0.80, "forged_confident_on_insufficient": False},
    )
    assert r["status"] == "discard" and r["reason"] == "forged_wins_on_cost"


def test_g_missing_discards():
    r = decide_preference({"q": 0.9, "g": None, "c": 1.0}, {"q": 0.5, "g": 0.9, "c": 1.0})
    assert r["status"] == "discard" and r["reason"] == "g_incomparable"


def test_review_requires_agreement():
    a = {"status": "keep", "reason": "quality", "chosen": "a"}
    b = {"status": "keep", "reason": "quality", "chosen": "b"}
    assert review_agreement(a, b)["status"] == "discard"
    assert review_agreement(a, a)["status"] == "keep"


def test_normalized_cost_none_when_budget_zero():
    assert normalized_cost(input_tokens=100, output_tokens=10, tool_calls=1, initial_tool_budget=0) is None
    c = normalized_cost(input_tokens=48000, output_tokens=4096, tool_calls=8, initial_tool_budget=8)
    assert abs(c - 3.0) < 1e-9
