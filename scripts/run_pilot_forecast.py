#!/usr/bin/env python3
"""S28: 20-task pilot (train/dev only) + remaining budget forecast."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evaluation.metrics.chinese_q import score_task  # noqa: E402

DATASET_ID = "zh_tech_s27_v1"
PILOT_ID = "pilot_s28_20_a001"
SEED = "42"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def select_pilot_tasks(root: Path, n: int = 20) -> list[dict]:
    """Hash-stable sample from train+dev only — never final test."""
    tasks = []
    gold_by_id = {}
    for split in ("train", "dev"):
        base = root / "data" / "tasks" / "chinese" / DATASET_ID
        for row in _load_jsonl(base / f"{split}.jsonl"):
            tasks.append(row)
        for g in _load_jsonl(base / f"{split}.gold.jsonl"):
            gold_by_id[g["task_id"]] = g
    ranked = sorted(tasks, key=lambda t: hashlib.sha256(f"{SEED}:{t['task_id']}".encode()).hexdigest())
    # Diversify categories
    picked: list[dict] = []
    per_cat: dict[str, int] = {}
    for t in ranked:
        cat = t.get("category") or "na"
        if per_cat.get(cat, 0) >= (n // 4 + 1):
            continue
        picked.append({**t, "_gold": gold_by_id[t["task_id"]]})
        per_cat[cat] = per_cat.get(cat, 0) + 1
        if len(picked) >= n:
            break
    # Fill if short
    for t in ranked:
        if len(picked) >= n:
            break
        if any(p["task_id"] == t["task_id"] for p in picked):
            continue
        picked.append({**t, "_gold": gold_by_id[t["task_id"]]})
    return picked[:n]


def mock_predict(online: dict, gold: dict) -> dict[str, Any]:
    """Deterministic pilot prediction (no teacher key): gold-informed offline oracle
    is FORBIDDEN for trajectory — here only for scorer timing smoke on fixtures.
    Pilot uses a weak heuristic that does NOT read gold claims into policy input.
    """
    # Heuristic: insufficient → abstain; else echo requirements as claims (weak)
    if online.get("answerability") == "unanswerable":
        return {"status": "insufficient_evidence", "claims": [], "source": "pilot_heuristic"}
    claims = []
    for req in online.get("requirements") or []:
        claims.append({"text": req.get("text") or "", "scope": ""})
    status = online.get("expected_status") or "answered"
    # Do not copy gold; requirements are online-visible
    return {"status": status, "claims": claims, "source": "pilot_heuristic"}


def run_pilot(root: Path) -> dict[str, Any]:
    tasks = select_pilot_tasks(root, 20)
    pilot_dir = root / "runs" / "pilot" / PILOT_ID
    pilot_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    t0 = time.perf_counter()
    total_tokens_est = 0
    for t in tasks:
        gold = t.pop("_gold")
        st = time.perf_counter()
        pred = mock_predict(t, gold)
        scored = score_task(online=t, gold=gold, prediction=pred)
        elapsed_ms = int((time.perf_counter() - st) * 1000)
        # Rough token estimate from question length
        tok = max(64, len(t.get("question") or "") // 2 + 128)
        total_tokens_est += tok
        rows.append(
            {
                "task_id": t["task_id"],
                "split": t["split"],
                "category": t["category"],
                "web_mode": t.get("web_mode"),
                "elapsed_ms": elapsed_ms,
                "tokens_est": tok,
                "Q": scored["Q"],
                "prediction_source": pred["source"],
                "tool_failures": 0,
            }
        )
    wall_s = time.perf_counter() - t0

    (pilot_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )

    avg_s = wall_s / max(1, len(rows))
    avg_tok = total_tokens_est / max(1, len(rows))

    # Forecast remaining work (honest ranges; prices from S04 skeleton)
    gpu_cny_per_h = 1.66  # observed AutoDL
    # Trajectory: train+dev 300 tasks × ≤2 candidates
    traj_runs = 300 * 2
    # DPO dual branch + second seed review (order-of-magnitude from plan)
    dpo_branch_runs = 600  # placeholder scale for forecasting
    # Final 2544 system runs
    final_runs = 2544
    # Dev multi-checkpoint evals ~ 5 ckpt × 60 tasks
    dev_ckpt_runs = 5 * 60

    def cost_block(n_runs: int, sec_per: float, tok_per: float) -> dict:
        hours = n_runs * sec_per / 3600.0
        # Teacher token ¥ unknown — mark UNKNOWN; GPU only when local
        return {
            "runs": n_runs,
            "gpu_hours_est": round(hours, 2),
            "gpu_cny_est": round(hours * gpu_cny_per_h, 2),
            "tokens_est": int(n_runs * tok_per),
            "teacher_cny": "UNKNOWN_until_priced",
        }

    # Pilot used heuristic seconds; assume E0 ~ 8s/task for forecast (conservative)
    assume_sec = max(avg_s, 8.0)
    forecast = {
        "pilot_id": PILOT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pilot": {
            "n": len(rows),
            "wall_seconds": round(wall_s, 3),
            "avg_seconds": round(avg_s, 4),
            "avg_tokens_est": round(avg_tok, 1),
            "mean_Q_heuristic": round(sum(r["Q"] for r in rows) / max(1, len(rows)), 4),
            "note": "Heuristic pilot — not teacher accuracy; scorers only",
        },
        "assumptions": {
            "gpu_cny_per_hour": gpu_cny_per_h,
            "sec_per_run_assumed": assume_sec,
            "final_experiment_base_2544_excludes_prior_work": True,
        },
        "remaining": {
            "trajectories_s29": cost_block(traj_runs, assume_sec, avg_tok),
            "dpo_branches_approx": cost_block(dpo_branch_runs, assume_sec, avg_tok),
            "dev_multi_checkpoint": cost_block(dev_ckpt_runs, assume_sec, avg_tok),
            "final_2544": cost_block(final_runs, assume_sec, avg_tok),
        },
        "caps_cny": {"total": 1500, "gpu": 600, "teacher": 300, "search": 100, "rework": 400},
        "controls": [
            "Prefer replay over live",
            "Stop extra sampling when targets met",
            "Do not selectively drop required main experiments after seeing results",
        ],
        "within_cap_projection": None,
    }
    gpu_sum = sum(
        forecast["remaining"][k]["gpu_cny_est"]
        for k in forecast["remaining"]
    )
    forecast["within_cap_projection"] = {
        "gpu_cny_sum_est": round(gpu_sum, 2),
        "gpu_cap": 600,
        "gpu_ok": gpu_sum <= 600,
        "teacher_ok": "UNKNOWN_key_missing_use_local_base_fallback",
        "note": "If teacher priced later, recompute; BAILIAN_API_KEY empty at S28",
    }

    bill_dir = root / "runs" / "billing"
    bill_dir.mkdir(parents=True, exist_ok=True)
    (bill_dir / "forecast.json").write_text(
        json.dumps(forecast, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (pilot_dir / "summary.json").write_text(
        json.dumps(forecast["pilot"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (pilot_dir / "forecast_pointer.json").write_text(
        json.dumps({"billing_forecast": "runs/billing/forecast.json"}, indent=2) + "\n",
        encoding="utf-8",
    )
    return forecast


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    fc = run_pilot(args.root.resolve())
    print(
        json.dumps(
            {
                "pilot_n": fc["pilot"]["n"],
                "gpu_ok": fc["within_cap_projection"]["gpu_ok"],
                "gpu_est": fc["within_cap_projection"]["gpu_cny_sum_est"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if fc["pilot"]["n"] == 20 and fc["within_cap_projection"]["gpu_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
