#!/usr/bin/env python3
"""Build S44 budget-curve / stability tables (no single weighted score)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    qs = [float((r.get("score") or {}).get("Q") or 0.0) for r in rows]
    fails = sum(1 for r in rows if (r.get("score") or {}).get("status") == "failed")
    tools = [float(((r.get("score") or {}).get("usage") or {}).get("tool_calls") or 0) for r in rows]
    tin = [float(((r.get("score") or {}).get("usage") or {}).get("input_tokens") or 0) for r in rows]
    tout = [float(((r.get("score") or {}).get("usage") or {}).get("output_tokens") or 0) for r in rows]
    wall = [float((r.get("score") or {}).get("wall_seconds") or 0) for r in rows]
    n = len(rows)
    return {
        "n": n,
        "Q_mean": round(sum(qs) / n, 4),
        "fail_rate": round(fails / n, 4),
        "avg_tool_calls": round(sum(tools) / n, 4),
        "avg_total_tokens": round((sum(tin) + sum(tout)) / n, 2),
        "avg_wall_seconds": round(sum(wall) / n, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    root = args.root
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)

    budget_dir = root / "runs/evaluation/eval_budget_s44_0001"
    stab_dir = root / "runs/evaluation/eval_stability_s44_0001"
    curve_rows = []
    for sys in ("b1", "e0"):
        for label, path in (
            ("b4", budget_dir / f"results_{sys}_b4.jsonl"),
            ("b8_reuse", budget_dir / f"results_{sys}_b8_reuse.jsonl"),
            ("b12", budget_dir / f"results_{sys}_b12.jsonl"),
        ):
            rows = _read(path)
            curve_rows.append({"system": sys, "budget": label, **_agg(rows)})
    (out / "tables" / "budget_curve.json").write_text(
        json.dumps(curve_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # CSV for plotting quality vs tools/tokens/wall
    lines = ["system,budget,n,Q_mean,fail_rate,avg_tool_calls,avg_total_tokens,avg_wall_seconds"]
    for r in curve_rows:
        lines.append(
            f"{r['system']},{r['budget']},{r['n']},{r.get('Q_mean')},{r.get('fail_rate')},"
            f"{r.get('avg_tool_calls')},{r.get('avg_total_tokens')},{r.get('avg_wall_seconds')}"
        )
    (out / "tables" / "budget_curve.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    stab_rows = []
    for sys in ("b1", "e0"):
        for seed in (43, 44):
            path = stab_dir / f"results_{sys}_t0.3_seed{seed}.jsonl"
            stab_rows.append({"system": sys, "seed": seed, "temperature": 0.3, **_agg(_read(path))})
    (out / "tables" / "stability.json").write_text(
        json.dumps(stab_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "figures" / "README.md").write_text(
        "# S44 figures\n\nTables are authoritative. Plot quality vs tool_calls / tokens / wall from "
        "`tables/budget_curve.csv`. Do not collapse into one weighted score. "
        "Stability rows are temperature 0.3 and are not same-distribution replicates of main temp0.\n",
        encoding="utf-8",
    )
    (out / "report.md").write_text(
        "# S44 budget curve and stability\n\n"
        f"- curve rows: {len(curve_rows)}\n"
        f"- stability rows: {len(stab_rows)}\n"
        "- see tables/\n",
        encoding="utf-8",
    )
    print(json.dumps({"curve": len(curve_rows), "stability": len(stab_rows), "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
