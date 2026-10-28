#!/usr/bin/env python3
"""S28: Validate offline scorer with fixed fixtures (before final test)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evaluation.metrics.chinese_q import score_task  # noqa: E402
from evaluation.metrics.english_em_f1 import exact_match, f1_score  # noqa: E402


def fixtures() -> list[dict]:
    """Hand-authored cases with expected Q / EM."""
    base_online = {
        "task_id": "fix_direct",
        "category": "direct_fact",
        "answerability": "answerable",
        "expected_status": "answered",
    }
    gold_direct = {
        "category": "direct_fact",
        "gold_claims": [
            {"claim_id": "c1", "text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@0.115.0"}
        ],
        "rubric": {"must_retain_scopes": ["fastapi@0.115.0"]},
    }
    cases = []

    # 1 correct
    cases.append(
        {
            "name": "correct",
            "online": dict(base_online),
            "gold": gold_direct,
            "prediction": {
                "status": "answered",
                "claims": [{"text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@0.115.0"}],
            },
            "expect_q_min": 0.9,
        }
    )
    # 2 答非所问
    cases.append(
        {
            "name": "irrelevant",
            "online": dict(base_online, task_id="fix_irrel"),
            "gold": gold_direct,
            "prediction": {"status": "answered", "claims": [{"text": "今天天气晴朗。", "scope": ""}]},
            "expect_q_max": 0.4,
        }
    )
    # 3 局部遗漏 (multi)
    multi_gold = {
        "category": "multi_source",
        "gold_claims": [
            {"claim_id": "a", "text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@0.115.0"},
            {"claim_id": "b", "text": "依赖注入通过 Depends 声明。", "scope": "fastapi@0.115.0"},
        ],
        "rubric": {},
    }
    cases.append(
        {
            "name": "partial_omit",
            "online": {
                "task_id": "fix_partial",
                "category": "multi_source",
                "answerability": "answerable",
                "expected_status": "answered",
            },
            "gold": multi_gold,
            "prediction": {
                "status": "answered",
                "claims": [{"text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@0.115.0"}],
            },
            "expect_q_min": 0.2,
            "expect_q_max": 0.85,
        }
    )
    # 4 范围错误
    cases.append(
        {
            "name": "scope_error",
            "online": {
                "task_id": "fix_scope",
                "category": "version_conflict",
                "answerability": "answerable",
                "expected_status": "conflicting_evidence",
            },
            "gold": {
                "category": "version_conflict",
                "gold_claims": [
                    {"claim_id": "o", "text": "旧版使用 A API。", "scope": "lib@1.0"},
                    {"claim_id": "n", "text": "新版使用 B API。", "scope": "lib@2.0"},
                ],
                "rubric": {"must_retain_scopes": ["lib@1.0", "lib@2.0"]},
            },
            "prediction": {
                "status": "answered",
                "claims": [{"text": "统一使用 B API。", "scope": "lib@2.0"}],
            },
            "expect_q_max": 0.7,
        }
    )
    # 5 多段联合支持 — both facts present
    cases.append(
        {
            "name": "multi_joint",
            "online": {
                "task_id": "fix_multi",
                "category": "multi_source",
                "answerability": "answerable",
                "expected_status": "answered",
            },
            "gold": multi_gold,
            "prediction": {
                "status": "answered",
                "claims": [
                    {"text": "FastAPI 的 Web 部分基于 Starlette。", "scope": "fastapi@0.115.0"},
                    {"text": "依赖注入通过 Depends 声明。", "scope": "fastapi@0.115.0"},
                ],
            },
            "expect_q_min": 0.85,
        }
    )
    # 6 空 claim
    cases.append(
        {
            "name": "empty_claims",
            "online": dict(base_online, task_id="fix_empty"),
            "gold": gold_direct,
            "prediction": {"status": "answered", "claims": []},
            "expect_q_max": 0.35,
        }
    )
    # 7 伪造引用 / 伪造不足题事实
    cases.append(
        {
            "name": "fabricated_on_insufficient",
            "online": {
                "task_id": "fix_fab",
                "category": "insufficient_evidence",
                "answerability": "unanswerable",
                "expected_status": "insufficient_evidence",
            },
            "gold": {
                "category": "insufficient_evidence",
                "gold_claims": [],
                "rubric": {"forbidden_fabrications": ["门店地址位于上海市南京路100号"]},
            },
            "prediction": {
                "status": "answered",
                "claims": [{"text": "门店地址位于上海市南京路100号"}],
            },
            "expect_q_max": 0.0,
        }
    )
    # 8 正确拒答
    cases.append(
        {
            "name": "correct_abstain",
            "online": {
                "task_id": "fix_abs",
                "category": "insufficient_evidence",
                "answerability": "unanswerable",
                "expected_status": "insufficient_evidence",
            },
            "gold": {
                "category": "insufficient_evidence",
                "gold_claims": [],
                "rubric": {"forbidden_fabrications": ["门店地址位于上海市南京路100号"]},
            },
            "prediction": {"status": "insufficient_evidence", "claims": []},
            "expect_q_min": 1.0,
            "expect_q_max": 1.0,
        }
    )
    return cases


def run(root: Path) -> dict:
    results = []
    failures = []
    for case in fixtures():
        scored = score_task(online=case["online"], gold=case["gold"], prediction=case["prediction"])
        q = scored["Q"]
        ok = True
        if "expect_q_min" in case and q < case["expect_q_min"] - 1e-9:
            ok = False
        if "expect_q_max" in case and q > case["expect_q_max"] + 1e-9:
            ok = False
        row = {"name": case["name"], "Q": q, "ok": ok, "detail": scored}
        results.append(row)
        if not ok:
            failures.append(row)

    # English EM/F1 smoke
    em = exact_match("The United States", "united states")
    f1 = f1_score("the cat sat", "cat sat here")
    eng = {"em_fixture": em, "f1_fixture": f1, "em_ok": em == 1.0, "f1_ok": 0.0 < f1 < 1.0}

    out_dir = root / "runs" / "evaluation" / "metrics" / "s28_fixtures_a001"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "passed": len(failures) == 0 and eng["em_ok"] and eng["f1_ok"],
        "cases": results,
        "english": eng,
        "failures": failures,
    }
    (out_dir / "fixture_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    summary = run(args.root.resolve())
    print(json.dumps({"passed": summary["passed"], "n": len(summary["cases"])}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
