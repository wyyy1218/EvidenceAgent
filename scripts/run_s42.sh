#!/usr/bin/env bash
# S42: six-system main experiment on frozen test300 (temperature 0); failures kept.
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo/scripts:$ROOT/repo:$ROOT/repo/training/sft:${PYTHONPATH:-}"

APP_PY="$ROOT/envs/app/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S42/a001"
EVAL="$ROOT/runs/evaluation/eval_main_s42_0001"
LOG="$ROOT/runs/system/logs/s42_run.log"
MANIFEST="$ROOT/data/manifests/mf_s41_freeze_0001.json"
SYSTEMS="b0,b1,b2,e0,e1,e2"
LORA_MODULES="sft_e1=$ROOT/artifacts/adapters/sft/exp_sft_0001,dpo_e2=$ROOT/artifacts/adapters/dpo/exp_dpo_0001"

mkdir -p "$STEP_DIR" "$EVAL" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== S42 start $(date -Is) ==="

echo "=== require S41 freeze ==="
"$APP_PY" - <<'PY'
import json
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
man = json.loads((root / "data/manifests/mf_s41_freeze_0001.json").read_text())
acc = json.loads((root / "runs/steps/S41/a001/acceptance.json").read_text())
assert acc.get("result") == "PASS", acc
assert man.get("release_system") == "e0", man.get("release_system")
assert man.get("looked_at_test_scores") is False
assert (root / "data/tasks/chinese/zh_tech_s27_v1/test.jsonl").is_file()
assert (root / "data/tasks/hotpotqa/hotpotqa_distractor_s25_v1/test.jsonl").is_file()
print("s41_ok", man.get("manifest_id"), man.get("config_bundle_hash")[:16])
PY

echo "=== ensure vLLM with SFT+DPO LoRAs ==="
"$APP_PY" "$SERVE" status >/dev/null 2>&1 || true
"$APP_PY" "$SERVE" stop || true
sleep 2
"$APP_PY" "$SERVE" start --vllm-only --lora-modules "$LORA_MODULES"

echo "=== write run meta (no score peek) ==="
"$APP_PY" - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("$ROOT")
eval_dir = root / "runs/evaluation/eval_main_s42_0001"
step = root / "runs/steps/S42/a001"
man = json.loads((root / "data/manifests/mf_s41_freeze_0001.json").read_text())
meta = {
    "evaluation_id": "eval_main_s42_0001",
    "step": "S42",
    "attempt": "a001",
    "systems": ["b0", "b1", "b2", "e0", "e1", "e2"],
    "split": "test",
    "n_tasks_planned": 300,
    "n_runs_planned": 1800,
    "temperature": 0.0,
    "web_mode": "off_or_replay",
    "freeze_manifest": "mf_s41_freeze_0001",
    "release_system": man.get("release_system"),
    "config_bundle_hash": man.get("config_bundle_hash"),
    "looked_at_test_for_selection": False,
    "started_at": datetime.now(timezone.utc).isoformat(),
}
eval_dir.mkdir(parents=True, exist_ok=True)
step.mkdir(parents=True, exist_ok=True)
(eval_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
(step / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"ok": True, "evaluation_id": meta["evaluation_id"]}, ensure_ascii=False))
PY

echo "=== main test300 × six systems (resume-safe) ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset all --split test \
  --systems "$SYSTEMS" \
  --out "$EVAL" --resume

echo "=== write S42 acceptance ==="
"$APP_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
eval_dir = root / "runs/evaluation/eval_main_s42_0001"
step = root / "runs/steps/S42/a001"
summary = json.loads((eval_dir / "summary.json").read_text()) if (eval_dir / "summary.json").is_file() else {}
systems = ["b0", "b1", "b2", "e0", "e1", "e2"]
counts = {}
for s in systems:
    p = eval_dir / f"results_{s}.jsonl"
    n = sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) if p.is_file() else 0
    counts[s] = n
complete = all(counts.get(s, 0) == 300 for s in systems)
acc = {
    "step": "S42",
    "attempt": "a001",
    "result": "PASS" if complete else "PARTIAL",
    "n_runs_planned": 1800,
    "n_runs_observed": sum(counts.values()),
    "per_system_n": counts,
    "complete_300_each": complete,
    "looked_at_test_for_selection": False,
    "evaluation_id": "eval_main_s42_0001",
    "time": datetime.now(timezone.utc).isoformat(),
}
(step / "acceptance.json").write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n")
lines = [
    f"# S42 a001 — main experiment",
    "",
    f"- result: **{acc['result']}**",
    f"- observed runs: {acc['n_runs_observed']}/1800",
    f"- per_system: {counts}",
    f"- summary systems: {list((summary.get('systems') or {}).keys())}",
    "",
]
(step / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(acc, ensure_ascii=False))
PY

echo "=== S42 end $(date -Is) ==="
