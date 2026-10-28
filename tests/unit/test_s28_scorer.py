"""S28: Offline scorer fixture expectations."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evaluation.metrics.chinese_q import score_task  # noqa: E402
from evaluation.metrics.english_em_f1 import exact_match, f1_score  # noqa: E402


def test_correct_and_abstain():
    online = {
        "task_id": "t1",
        "category": "direct_fact",
        "answerability": "answerable",
        "expected_status": "answered",
    }
    gold = {
        "category": "direct_fact",
        "gold_claims": [{"claim_id": "c1", "text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@1"}],
        "rubric": {"must_retain_scopes": ["fastapi@1"]},
    }
    pred = {
        "status": "answered",
        "claims": [{"text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@1"}],
    }
    assert score_task(online=online, gold=gold, prediction=pred)["Q"] >= 0.9

    online_u = {
        "task_id": "t2",
        "category": "insufficient_evidence",
        "answerability": "unanswerable",
        "expected_status": "insufficient_evidence",
    }
    gold_u = {
        "category": "insufficient_evidence",
        "gold_claims": [],
        "rubric": {"forbidden_fabrications": ["秘密地址XYZ"]},
    }
    assert (
        score_task(
            online=online_u,
            gold=gold_u,
            prediction={"status": "insufficient_evidence", "claims": []},
        )["Q"]
        == 1.0
    )
    assert (
        score_task(
            online=online_u,
            gold=gold_u,
            prediction={"status": "answered", "claims": [{"text": "秘密地址XYZ在此处"}]},
        )["Q"]
        == 0.0
    )


def test_english_em_f1():
    assert exact_match("The Cat", "cat") == 1.0
    assert 0.0 < f1_score("a b c", "b c d") < 1.0
