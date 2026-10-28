"""S41 subset selection pure-function checks (no GPU, no scores)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from run_s41_freeze import (  # noqa: E402
    PREFIX_ABLATION,
    PREFIX_BLIND,
    PREFIX_BUDGET,
    build_run_plan,
    select_ablation100,
    select_blind60,
    select_budget_stability60,
    select_drbench12,
    _hash_rank,
)


def _fake_zh(n_per_cat: int = 25) -> list[dict]:
    cats = ("direct_fact", "multi_source", "version_conflict", "insufficient_evidence")
    rows = []
    for cat in cats:
        for i in range(n_per_cat):
            rows.append({"task_id": f"zh_{cat}_{i:03d}", "category": cat})
    return rows


def _fake_hp(n: int = 200) -> list[dict]:
    return [{"task_id": f"hpqa_{i:04d}", "difficulty": "medium"} for i in range(n)]


def test_ablation100_counts_and_determinism():
    zh, hp = _fake_zh(), _fake_hp()
    a = select_ablation100(zh, hp)
    b = select_ablation100(zh, hp)
    assert a["n"] == 100
    assert a["counts"] == {"chinese": 40, "hotpotqa": 60}
    assert all(len(v) == 10 for v in a["chinese_by_category"].values())
    assert a["task_ids"] == b["task_ids"]
    # Rank order matches prefix rule
    assert a["hotpotqa"] == sorted(
        a["hotpotqa"], key=lambda t: (_hash_rank(PREFIX_ABLATION, t), t)
    )


def test_budget60_and_blind60():
    zh, hp = _fake_zh(), _fake_hp()
    bud = select_budget_stability60(zh, hp)
    blind = select_blind60(zh, hp)
    assert bud["n"] == 60 and bud["counts"]["chinese"] == 20 and bud["counts"]["hotpotqa"] == 40
    assert blind["n"] == 60 and blind["counts"]["chinese"] == 40 and blind["counts"]["english"] == 20
    assert blind["outputs_expected"] == 120
    # Different prefixes → not forced identical sets
    assert bud["prefix"] == PREFIX_BUDGET
    assert blind["prefix"] == PREFIX_BLIND


def test_drbench_pending_and_frozen():
    pending = select_drbench12(None)
    assert pending["status"] == "IDS_PENDING_CATALOG"
    assert pending["runs"] == 24
    ids = [f"q{i}" for i in range(30)]
    frozen = select_drbench12(ids)
    assert frozen["status"] == "IDS_FROZEN"
    assert frozen["n"] == 12
    assert frozen["question_ids"] == sorted(ids, key=lambda q: (_hash_rank("s41_drbench12", q), q))[:12]


def test_run_plan_2544():
    zh, hp = _fake_zh(), _fake_hp()
    ablation = select_ablation100(zh, hp)
    budget = select_budget_stability60(zh, hp)
    blind = select_blind60(zh, hp)
    drbench = select_drbench12(None)
    live = {
        "status": "PROTOCOL_FROZEN_TASKS_PENDING",
        "n_slots": 20,
    }
    plan = build_run_plan(
        release_system="e0",
        ablation=ablation,
        budget60=budget,
        blind=blind,
        drbench=drbench,
        live=live,
    )
    assert plan["planned_formal_runs"] == 2544
    assert plan["matches_target"] is True
