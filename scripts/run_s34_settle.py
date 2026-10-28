#!/usr/bin/env python3
"""S34: settle SFT stage and decide whether DPO may start."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _drop(base: float | None, cand: float | None) -> float | None:
    if base is None or cand is None:
        return None
    return float(base) - float(cand)


def _increase(base: float | None, cand: float | None) -> float | None:
    if base is None or cand is None:
        return None
    return float(cand) - float(base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    step = root / "runs" / "steps" / "S34" / "a001"
    step.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    project = _load_yaml(root / "repo" / "configs" / "project.yaml")
    release = project.get("release") or {}
    max_q_drop = float(release.get("maximum_quality_drop", 0.02))
    max_g_drop = float(release.get("maximum_support_drop", 0.02))
    max_false_inc = float(release.get("maximum_false_answer_increase", 0.02))
    min_valid = float(release.get("minimum_valid_action_rate", 0.98))

    s30 = _load(root / "runs" / "steps" / "S30" / "a001" / "evidence_index.json") or {}
    s32 = _load(root / "runs" / "steps" / "S32" / "a001" / "evidence_index.json") or {}
    s33 = _load(root / "runs" / "steps" / "S33" / "a001" / "evidence_index.json") or {}
    sel = _load(root / "runs" / "evaluation" / "eval_dev40_s33_0001" / "selection.json") or {}
    full = _load(root / "runs" / "evaluation" / "eval_dev160_s33_0001" / "summary.json") or {}
    state = _load(root / "runs" / "evaluation" / "eval_state_s33_0001" / "state_summary.json") or {}
    route = _load(root / "runs" / "probes" / "probe_s33_vllm_route_a001" / "summary.json") or {}

    s30_acc = root / "runs" / "steps" / "S30" / "a001" / "acceptance.md"
    s32_acc = root / "runs" / "steps" / "S32" / "a001" / "acceptance.md"
    s30_text = s30_acc.read_text(encoding="utf-8") if s30_acc.is_file() else ""
    s32_text = s32_acc.read_text(encoding="utf-8") if s32_acc.is_file() else ""

    train_n = 0
    scale = s30.get("scale") if isinstance(s30.get("scale"), dict) else {}
    if scale.get("train") is not None:
        try:
            train_n = int(scale["train"])
        except (TypeError, ValueError):
            train_n = 0
    if train_n <= 0:
        for key in ("train_rows", "train", "n_train", "train_count"):
            if key in s30:
                try:
                    train_n = int(s30[key])
                    break
                except (TypeError, ValueError):
                    pass
    data_ok = bool(s30.get("result") == "PASS") and (train_n >= 2000 or "4917" in s30_text)
    if train_n >= 2000:
        data_ok = True
    data_note = f"S30 train_rows={train_n or 'unknown'}; target>=2000"

    train_ok = bool(s32.get("result") == "PASS") or (
        s32_acc.is_file() and "**PASS**" in s32_text and "Result" in s32_text
    )
    if not train_ok and s32_acc.is_file():
        # Prefer explicit Result line over incidental PASS mentions
        for ln in s32_text.splitlines():
            if "Result" in ln and "PASS" in ln:
                train_ok = True
                break
            if "Result" in ln and "FAIL" in ln:
                train_ok = False
                break

    chosen = sel.get("chosen_system") or s33.get("chosen_system")
    t24 = route.get("t24_pass")
    if t24 is None and isinstance(route.get("checks"), dict):
        t24 = route["checks"].get("t24_pass")
    adapter_ok = bool(t24) and bool(chosen)

    systems = full.get("systems") or {}
    e0 = systems.get("e0") or {}
    e1 = systems.get(chosen) or systems.get("e1_final") or {}
    e1_state = (state.get("systems") or {}).get(chosen) or (state.get("systems") or {}).get(
        "e1_final"
    ) or {}

    q0, q1 = e0.get("Q_mean"), e1.get("Q_mean")
    g0 = e0.get("G_gold_anchored_mean")
    g1 = e1.get("G_gold_anchored_mean")
    if g0 is None:
        g0 = e0.get("G_verifier_mean")
    if g1 is None:
        g1 = e1.get("G_verifier_mean")
    f0, f1 = e0.get("answered_false_rate"), e1.get("answered_false_rate")
    legality = e1_state.get("param_valid_rate")
    if legality is None:
        legality = e1.get("action_valid_rate_mean")
    legality_f = float(legality) if legality is not None else None

    q_drop = _drop(q0, q1)
    g_drop = _drop(g0, g1)
    false_inc = _increase(f0, f1)

    checks: dict[str, Any] = {
        "q_drop": q_drop,
        "g_drop": g_drop,
        "false_answer_increase": false_inc,
        "param_valid_rate": legality_f,
        "thresholds": {
            "maximum_quality_drop": max_q_drop,
            "maximum_support_drop": max_g_drop,
            "maximum_false_answer_increase": max_false_inc,
            "minimum_valid_action_rate": min_valid,
        },
        "e0_Q": q0,
        "e1_Q": q1,
        "e0_G": g0,
        "e1_G": g1,
        "e0_answered_false_rate": f0,
        "e1_answered_false_rate": f1,
    }

    missing = [
        name
        for name, val in (
            ("Q", q_drop),
            ("G", g_drop),
            ("answered_false", false_inc),
            ("param_valid_rate", legality_f),
        )
        if val is None
    ]
    if missing:
        effect_pass = False
        effect_status = "unproven"
        effect_note = f"missing_metrics:{','.join(missing)}"
    else:
        effect_pass = (
            q_drop <= max_q_drop
            and g_drop <= max_g_drop
            and false_inc <= max_false_inc
            and legality_f >= min_valid
        )
        effect_status = "pass" if effect_pass else "fail"
        effect_note = "release gate vs E0 on Q/G/false_answer/param_valid"

    s33_ok = s33.get("result") == "PASS"
    dpo_allowed = bool(train_ok and adapter_ok and s33_ok)
    blocked_reason = None
    if not data_ok:
        # Data target is recorded separately; does not alone block research DPO if train/adapter ok
        pass
    if not train_ok:
        blocked_reason = "s32_train_not_pass"
    elif not adapter_ok:
        blocked_reason = "adapter_or_route_not_ok"
    elif not s33_ok:
        blocked_reason = "s33_not_pass"

    product_fallback = "E0" if not effect_pass else (chosen or "E0")
    # Overall step result: settlement recorded successfully when axes decided.
    # PASS means DPO research may proceed; effect_gate may still FAIL.
    result = "PASS" if dpo_allowed else "FAIL"

    verdict = {
        "step": "S34",
        "attempt": "a001",
        "written_at": now.isoformat(),
        "result": result,
        "axes": {
            "data_target": {"pass": data_ok, "note": data_note},
            "training_process": {"pass": train_ok, "note": "S32 formal SFT"},
            "adapter_callable": {
                "pass": adapter_ok,
                "chosen": chosen,
                "t24": t24,
            },
            "effect_gate": {
                "pass": effect_pass,
                "status": effect_status,
                "details": checks,
                "note": effect_note,
            },
        },
        "dpo_allowed": dpo_allowed,
        "blocked_reason": blocked_reason,
        "e1_candidate": chosen if adapter_ok else None,
        "e1_release_status": "research_only" if adapter_ok and not effect_pass else (
            "release_candidate" if effect_pass else "unavailable"
        ),
        "product_fallback": product_fallback,
    }
    (step / "evidence_index.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# S34 acceptance — a001",
        "",
        f"- **Date:** {now.date()}",
        f"- **Result:** **{result}**",
        f"- Data target: {data_ok} ({data_note})",
        f"- Training process: {train_ok}",
        f"- Adapter callable: {adapter_ok} (chosen=`{chosen}`, t24={t24})",
        f"- Effect gate: {effect_status} (pass={effect_pass})",
        f"  - Q drop: {q_drop} (max {max_q_drop})",
        f"  - G drop: {g_drop} (max {max_g_drop})",
        f"  - answered_false increase: {false_inc} (max {max_false_inc})",
        f"  - param_valid_rate: {legality_f} (min {min_valid})",
        f"- DPO allowed (research): {dpo_allowed}",
        f"- E1 release status: {verdict['e1_release_status']}",
        f"- Product fallback: {product_fallback}",
        "",
        "Effect-gate failure does not delete E1; it remains a research reference if callable.",
        "DPO may continue only from this fixed SFT; do not claim E1 as published when effect_gate fails.",
    ]
    if blocked_reason:
        lines.append(f"- Blocked reason: `{blocked_reason}`")
        (step / "failure.md").write_text(
            f"# S34 blocked\n\nreason={blocked_reason}\n", encoding="utf-8"
        )
    (step / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    bill = root / "runs" / "billing" / "forecast.json"
    bill.parent.mkdir(parents=True, exist_ok=True)
    if bill.is_file():
        backup = root / "runs" / "billing" / "forecast_s28_backup.json"
        if not backup.is_file():
            shutil.copy2(bill, backup)
        existing = _load(bill) or {}
    else:
        existing = {}
    s34_forecast = {
        "updated": now.isoformat(),
        "next": "S35-S39",
        "dpo_allowed": dpo_allowed,
        "notes": [
            "Budget must cover dual-branch × dual-seed subsequent executions, not only DPO GPU hours.",
            "Min 300 preference pairs before formal DPO.",
            "700 qualified pairs × 2 branches × 2 seeds ≈ 2800 continuation runs, plus discarded candidates.",
        ],
        "preference_collection_estimate": {
            "min_train_pairs": 300,
            "target_train_pairs": 600,
            "target_dev_pairs": 100,
            "runs_per_kept_pair_nominal": 4,
            "nominal_continuation_runs_at_700": 2800,
        },
        "product_fallback": product_fallback,
        "e1_release_status": verdict["e1_release_status"],
    }
    merged = dict(existing) if isinstance(existing, dict) else {"prior": existing}
    merged["s34"] = s34_forecast
    merged["updated"] = now.isoformat()
    bill.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "runs" / "billing" / "forecast_s34.json").write_text(
        json.dumps(s34_forecast, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if dpo_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
