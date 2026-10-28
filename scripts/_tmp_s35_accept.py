#!/usr/bin/env python3
"""Validate S35 short-probe acceptance gates."""
from __future__ import annotations

import json
from pathlib import Path

root = Path("/root/autodl-tmp/evidence-agent")
pairs = [
    json.loads(l)
    for l in (root / "runs/branches/br_probe_s35_0001/pairs.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]
dpo_dev = [
    json.loads(l)
    for l in (root / "data/dpo/dpo_probe_s36_0001/dev.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]
manifest = json.loads((root / "runs/branches/br_probe_s35_0001/manifest.json").read_text(encoding="utf-8"))
summary = json.loads((root / "runs/branches/br_probe_s35_0001/summary.json").read_text(encoding="utf-8"))

checks = []

def ok(name: str, cond: bool, detail: str = "") -> None:
    checks.append({"name": name, "pass": bool(cond), "detail": detail})
    print(("PASS" if cond else "FAIL"), name, detail)

ok("kept_ge_2", len(pairs) >= 2, f"n={len(pairs)}")
for i, r in enumerate(pairs):
    ok(f"pair{i}_same_state_hash", bool(r.get("state_hash")), r.get("state_hash", "")[:16])
    ok(f"pair{i}_actions_differ", r.get("action_a") != r.get("action_b"), "")
    ok(f"pair{i}_run_ids", bool(r.get("run_id_a") and r.get("run_id_b")), f"{r.get('run_id_a')},{r.get('run_id_b')}")
    ok(f"pair{i}_metrics", all(k in (r.get("metrics_a") or {}) for k in ("q", "g", "c")), str(r.get("metrics_a")))
    ok(f"pair{i}_label", bool((r.get("final") or {}).get("reason")), str(r.get("final")))
    ok(
        f"pair{i}_review_honest",
        (r.get("final") or {}).get("review") in {"seed43_agree", "not_independent"},
        str((r.get("final") or {}).get("review")),
    )
    ok(f"pair{i}_has_messages", isinstance(r.get("messages"), list) and len(r["messages"]) >= 2, "")
    prompt = str(r.get("prompt") or "")
    ok(f"pair{i}_prompt_not_hash_only", prompt != r.get("state_hash") and len(prompt) > 40, prompt[:40])

for i, r in enumerate(dpo_dev):
    ok(f"dpo{i}_prompt_real", len(str(r.get("prompt") or "")) > 40 and str(r.get("prompt")) != r.get("state_hash"), "")
    # chosen/rejected should be action JSON only
    for side in ("chosen", "rejected"):
        try:
            obj = json.loads(r[side])
            ok(f"dpo{i}_{side}_action_json", "action" in obj, r[side][:80])
        except Exception as exc:  # noqa: BLE001
            ok(f"dpo{i}_{side}_action_json", False, str(exc))

ok("manifest_temp", manifest.get("offline_sample_temperature") == 0.6, str(manifest.get("offline_sample_temperature")))
ok("manifest_seed_limit", manifest.get("review_mode") == "not_independent" or manifest.get("seed_supported") is True, str(manifest.get("review_mode")))
ok("summary_seed_flag", summary.get("seed_supported") is False, "honest not_independent")

failed = [c for c in checks if not c["pass"]]
print("RESULT", "PASS" if not failed else "FAIL", f"failed={len(failed)}/{len(checks)}")
(root / "runs/steps/S35/a001").mkdir(parents=True, exist_ok=True)
(root / "runs/steps/S35/a001/probe_checks.json").write_text(
    json.dumps({"checks": checks, "failed": len(failed), "result": "PASS" if not failed else "FAIL"}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
