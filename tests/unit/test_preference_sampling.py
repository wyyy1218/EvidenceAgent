"""Unit checks for preference pair selection / remaining-budget steps."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training" / "preferences"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "training" / "sft"))
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_agent.agent.budget import BudgetConfig, BudgetState  # noqa: E402
from evidence_agent.agent.state import VisibleState  # noqa: E402

from collect_branches import (  # noqa: E402
    _SKIP_WHILE_FILLING,
    _branch_max_steps,
    _pair_rank,
    _preference_state_hash,
    _remaining_tool_budget,
    _select_action_pair,
    _task_cat_priority,
    _task_category,
)


def _a(action: str, **extra):
    base = {"action": action, "query": None, "candidate_id": None, "reason_code": None}
    base.update(extra)
    return base


def test_prefer_continue_vs_stop():
    search = _a("local_search", query="q")
    finish = _a("finish", reason_code="evidence_sufficient")
    other_search = _a("web_search", query="q")
    pair = _select_action_pair([search, other_search, finish])
    assert pair is not None
    types = {pair[0]["action"], pair[1]["action"]}
    assert "finish" in types
    assert "local_search" in types or "web_search" in types
    assert _pair_rank(search, finish)[0] == 0
    assert _pair_rank(search, other_search)[0] == 1


def test_remaining_tool_budget_caps_max_steps():
    b = BudgetState(cfg=BudgetConfig(tool_calls=8), tool_calls_used=5)
    assert _remaining_tool_budget(b) == 3
    assert _branch_max_steps(b) == 5  # 3 + 2 for finish/abstain


def test_pair_rank_same_type_worse_than_cross():
    a = _a("local_search", query="q")
    b = _a("local_search", query="q2")
    finish = _a("finish", reason_code="evidence_sufficient")
    assert _pair_rank(a, finish)[0] < _pair_rank(a, b)[0]


def test_preference_state_hash_ignores_wall_clock():
    base_budget = {
        "tool_calls_left": 3,
        "live_search_left": 1,
        "input_tokens_left": 1000,
        "output_tokens_left": 500,
        "final_output_reserve": 100,
        "remaining_wall_seconds": 225.0,
    }
    v1 = VisibleState(question="q", budget=dict(base_budget))
    v2 = VisibleState(question="q", budget={**base_budget, "remaining_wall_seconds": 240.0})
    assert _preference_state_hash(v1) == _preference_state_hash(v2)
    assert v1.state_hash() != v2.state_hash()


def test_task_cat_priority_prefers_mul_dir():
    assert _task_category("zh_train_mul_001_abc") == "mul"
    assert _task_category("zh_train_dir_001_abc") == "dir"
    assert _task_category("zh_train_ver_001_abc") == "ver"
    assert _task_category("hpqa_train_abc") == "hpqa"
    assert _task_cat_priority("zh_train_mul_001_abc") < _task_cat_priority("zh_train_dir_001_abc")
    assert _task_cat_priority("zh_train_dir_001_abc") < _task_cat_priority("zh_train_ver_001_abc")
    assert _task_cat_priority("zh_train_ver_001_abc") < _task_cat_priority("hpqa_train_abc")
    # Low-yield cats are deferred while filling either train or dev quota.
    assert {"ver", "ins", "hpqa"} <= _SKIP_WHILE_FILLING
    assert "mul" not in _SKIP_WHILE_FILLING and "dir" not in _SKIP_WHILE_FILLING


def test_select_pair_skips_stop_without_evidence_flag():
    search = _a("local_search", query="q")
    finish = _a("finish", reason_code="evidence_sufficient")
    read = _a("read_evidence", candidate_id="c1")
    pair = _select_action_pair([search, finish, read], allow_stop_contrast=False)
    assert pair is not None
    types = {pair[0]["action"], pair[1]["action"]}
    assert "finish" not in types
    assert types == {"local_search", "read_evidence"}
