#!/usr/bin/env python3
"""Export frozen S41 subset task_ids to a JSON list for --task-ids-file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--subset", required=True, choices=["ablation100", "budget_stability60", "blind60"])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    data = json.loads((args.root / "data/splits/s41_test_subsets.json").read_text(encoding="utf-8"))
    ids = data["subsets"][args.subset]["task_ids"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"subset": args.subset, "n": len(ids), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
