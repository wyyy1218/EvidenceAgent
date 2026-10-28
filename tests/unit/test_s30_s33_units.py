"""S30/S33 unit checks that do not require a GPU or vLLM."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "src", ROOT / "scripts", ROOT / "training" / "sft"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from training.data.build_sft_dataset import _answer_in_text, _completion_text  # noqa: E402
from dev_eval import select_subset  # noqa: E402


def test_short_gold_answer_is_not_a_metadata_leak():
    assert not _answer_in_text("no", "no_new_evidence_streak")
    assert not _answer_in_text("2", "tool_calls_left 2")


def test_long_gold_answer_is_detected():
    assert _answer_in_text("Oberndorf bei Salzburg", "town: Oberndorf bei Salzburg")
    assert not _answer_in_text("Oberndorf bei Salzburg", "town: Oberndorf")


def test_completion_is_single_ordered_action_json():
    text = _completion_text(
        {"action": "finish", "query": None, "candidate_id": None, "reason_code": "evidence_sufficient"}
    )
    assert text == '{"action":"finish","query":null,"candidate_id":null,"reason_code":"evidence_sufficient"}'


def test_dev40_subset_is_deterministic_and_stratified():
    root = ROOT.parent
    cases, rule = select_subset(root, 40)
    assert len(cases) == 40
    assert rule["actual"]["chinese"] == 24
    assert rule["actual"]["hotpotqa"] == 16
    cases2, _ = select_subset(root, 40)
    assert [c.task_id for c in cases] == [c.task_id for c in cases2]