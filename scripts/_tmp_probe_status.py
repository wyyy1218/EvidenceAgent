#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

root = Path("/root/autodl-tmp/evidence-agent")
out = root / "runs/branches/br_probe_s35_0001"
disc = out / "discarded.jsonl"
pairs = out / "pairs.jsonl"
print("pairs_exists", pairs.is_file(), "size", pairs.stat().st_size if pairs.is_file() else 0)
print("disc_exists", disc.is_file(), "size", disc.stat().st_size if disc.is_file() else 0)
if disc.is_file():
    rows = [json.loads(l) for l in disc.read_text(encoding="utf-8").splitlines() if l.strip()]
    print("discarded_n", len(rows))
    print("reasons", Counter(r.get("reason") for r in rows))
    if rows:
        print("last", json.dumps(rows[-1], ensure_ascii=False)[:1200])
if pairs.is_file():
    rows = [json.loads(l) for l in pairs.read_text(encoding="utf-8").splitlines() if l.strip()]
    print("kept_n", len(rows))
    if rows:
        print("last_keep", json.dumps({k: rows[-1].get(k) for k in ("task_id","state_hash","final","run_id_a","run_id_b")}, ensure_ascii=False))
