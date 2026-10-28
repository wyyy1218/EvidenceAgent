#!/usr/bin/env python3
"""S40: unique release selection on the same 160-dev results (no test)."""
from __future__ import annotations

import argparse
import json
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


def _tokens(row: dict[str, Any]) -> float:
    return float(row.get("avg_input_tokens") or 0) + float(row.get("avg_output_tokens") or 0)


def _gate(
    e0: dict[str, Any],
    cand: dict[str, Any],
    *,
    max_q_drop: float,
    max_g_drop: float,
    max_false_inc: float,
    min_valid: float,
) -> dict[str, Any]:
    q0, q1 = float(e0["Q_mean"]), float(cand["Q_mean"])
    g0 = float(e0.get("G_gold_anchored_mean") or 0)
    g1 = float(cand.get("G_gold_anchored_mean") or 0)
    f0 = float(e0.get("answered_false_rate") or 0)
    f1 = float(cand.get("answered_false_rate") or 0)
    valid = float(cand.get("action_valid_rate_mean") or 0)
    q_drop = q0 - q1
    g_drop = g0 - g1
    false_inc = f1 - f0
    checks = {
        "q_drop": q_drop,
        "q_ok": q_drop <= max_q_drop,
        "g_drop": g_drop,
        "g_ok": g_drop <= max_g_drop,
        "false_answer_increase": false_inc,
        "false_ok": false_inc <= max_false_inc,
        "action_valid_rate": valid,
        "valid_ok": valid >= min_valid,
    }
    checks["pass"] = all(checks[k] for k in ("q_ok", "g_ok", "false_ok", "valid_ok"))
    return checks


def _family(name: str) -> str:
    n = name.lower()
    if n in {"e0", "base"}:
        return "e0"
    if "dpo" in n or n in {"e2", "e2_final"}:
        return "dpo"
    if "sft" in n or n.startswith("e1"):
        return "sft"
    return "other"


# Tie-break priority when metrics/tokens identical: SFT → DPO → E0
_FAMILY_RANK = {"sft": 0, "dpo": 1, "e0": 2, "other": 3}


def select_release(
    systems: dict[str, dict[str, Any]],
    *,
    e0_name: str = "e0",
    max_q_drop: float = 0.02,
    max_g_drop: float = 0.02,
    max_false_inc: float = 0.02,
    min_valid: float = 0.98,
    q_tie: float = 0.01,
    g_tie: float = 0.01,
    research_only: set[str] | None = None,
) -> dict[str, Any]:
    research_only = research_only or set()
    if e0_name not in systems:
        raise SystemExit(f"missing baseline {e0_name}")
    e0 = systems[e0_name]
    gates: dict[str, Any] = {}
    eligible: list[str] = [e0_name]
    for name, row in systems.items():
        if name == e0_name:
            gates[name] = {"pass": True, "baseline": True}
            continue
        g = _gate(
            e0,
            row,
            max_q_drop=max_q_drop,
            max_g_drop=max_g_drop,
            max_false_inc=max_false_inc,
            min_valid=min_valid,
        )
        if name in research_only:
            g["research_only"] = True
            g["pass"] = False
            g["eliminated_reason"] = "research_only_or_prior_gate_fail"
        gates[name] = g
        if g["pass"]:
            eligible.append(name)

    # Among eligible: Q within 0.01 of best → G within 0.01 of best → fewer tokens → family
    # +1e-12 absorbs float noise on stored 4-dp metrics (e.g. 0.25-0.24).
    eps = 1e-12
    best_q = max(float(systems[n]["Q_mean"]) for n in eligible)
    q_pool = [n for n in eligible if best_q - float(systems[n]["Q_mean"]) <= q_tie + eps]
    best_g = max(float(systems[n].get("G_gold_anchored_mean") or 0) for n in q_pool)
    g_pool = [
        n
        for n in q_pool
        if best_g - float(systems[n].get("G_gold_anchored_mean") or 0) <= g_tie + eps
    ]
    min_tok = min(_tokens(systems[n]) for n in g_pool)
    tok_pool = [n for n in g_pool if abs(_tokens(systems[n]) - min_tok) < 1e-6]
    chosen = sorted(tok_pool, key=lambda n: (_FAMILY_RANK.get(_family(n), 9), n))[0]

    return {
        "chosen_system": chosen,
        "eligible": eligible,
        "q_pool": q_pool,
        "g_pool": g_pool,
        "tok_pool": tok_pool,
        "gates": gates,
        "tie_rule": "Q<=0.01 of best → G<=0.01 of best → fewer tokens → SFT>DPO>E0",
        "looked_at_test": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument(
        "--dev160",
        type=Path,
        default=None,
        help="summary.json with systems.*; default prefers S39 then S33",
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    root = args.root.resolve()
    project = _load_yaml(root / "repo" / "configs" / "project.yaml")
    release = project.get("release") or {}

    if args.dev160:
        summary_path = args.dev160 if args.dev160.is_absolute() else root / args.dev160
    else:
        s39 = root / "runs" / "evaluation" / "eval_dev160_s39_0001" / "summary.json"
        s33 = root / "runs" / "evaluation" / "eval_dev160_s33_0001" / "summary.json"
        summary_path = s39 if s39.is_file() else s33

    summary = _load(summary_path) or {}
    systems = dict(summary.get("systems") or {})
    if not systems:
        raise SystemExit(f"no systems in {summary_path}")

    # Merge E0/E1 from S33 if S39 only has e2 (same-condition reuse declared).
    s33 = _load(root / "runs" / "evaluation" / "eval_dev160_s33_0001" / "summary.json") or {}
    for name, row in (s33.get("systems") or {}).items():
        systems.setdefault(name, row)

    s34 = _load(root / "runs" / "steps" / "S34" / "a001" / "acceptance.json") or {}
    research_only: set[str] = set()
    if s34.get("e1_release_status") == "research_only" or (
        isinstance(s34.get("effect_gate"), dict) and not s34["effect_gate"].get("pass")
    ):
        research_only.update({"e1_final", "e1", "sft_e1", "e1_ckpt_600"})
    # Also read S34 acceptance.md fallback
    s34_md = root / "runs" / "steps" / "S34" / "a001" / "acceptance.md"
    if s34_md.is_file() and "research_only" in s34_md.read_text(encoding="utf-8"):
        research_only.update({"e1_final", "e1", "sft_e1", "e1_ckpt_600"})

    decision = select_release(
        systems,
        max_q_drop=float(release.get("maximum_quality_drop", 0.02)),
        max_g_drop=float(release.get("maximum_support_drop", 0.02)),
        max_false_inc=float(release.get("maximum_false_answer_increase", 0.02)),
        min_valid=float(release.get("minimum_valid_action_rate", 0.98)),
        q_tie=float(release.get("quality_tie_margin", 0.01)),
        g_tie=float(release.get("support_tie_margin", 0.01)),
        research_only=research_only,
    )
    decision["source_summary"] = str(summary_path)
    decision["systems_present"] = sorted(systems)
    decision["research_only"] = sorted(research_only)
    decision["time"] = datetime.now(timezone.utc).isoformat()
    # Snapshot metrics used
    decision["metrics"] = {
        n: {
            "Q_mean": systems[n].get("Q_mean"),
            "G_gold_anchored_mean": systems[n].get("G_gold_anchored_mean"),
            "answered_false_rate": systems[n].get("answered_false_rate"),
            "action_valid_rate_mean": systems[n].get("action_valid_rate_mean"),
            "tokens": _tokens(systems[n]),
        }
        for n in systems
    }

    out = args.out or (root / "runs" / "steps" / "S40" / "a001")
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    (out / "selection.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# S40 a001 — release selection",
        "",
        f"- time: {decision['time']}",
        f"- chosen_system: **{decision['chosen_system']}**",
        f"- eligible: {decision['eligible']}",
        f"- research_only eliminated: {decision['research_only']}",
        f"- looked_at_test: false",
        f"- source: {decision['source_summary']}",
        "",
        "## Gates vs E0",
        "",
    ]
    for name, g in decision["gates"].items():
        lines.append(f"- `{name}`: {json.dumps(g, ensure_ascii=False)}")
    lines.extend(["", "## Tie pools", ""])
    lines.append(f"- q_pool: {decision['q_pool']}")
    lines.append(f"- g_pool: {decision['g_pool']}")
    lines.append(f"- tok_pool: {decision['tok_pool']}")
    lines.append("")
    (out / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "acceptance.json").write_text(
        json.dumps(
            {
                "step": "S40",
                "attempt": "a001",
                "result": "PASS",
                "chosen_system": decision["chosen_system"],
                "eligible": decision["eligible"],
                "looked_at_test": False,
                "time": decision["time"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"chosen": decision["chosen_system"], "eligible": decision["eligible"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
