#!/usr/bin/env bash
# S45: DRBench12 (B1/E0) + live20 (B1/E0 AB/BA). External; not mixed into main aggregates.
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo/scripts:$ROOT/repo:$ROOT/repo/training/sft:${PYTHONPATH:-}"
set -a; source "$ROOT/runs/system/private.env" 2>/dev/null || true; set +a

APP_PY="$ROOT/envs/app/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S45/a001"
EVAL_DR="$ROOT/runs/evaluation/eval_drbench_s45_0001"
EVAL_LIVE="$ROOT/runs/evaluation/eval_live_s45_0001"
LOG="$ROOT/runs/system/logs/s45_run.log"
IDS_DR="$ROOT/runs/work/s41_subset_ids/drbench12.json"
IDS_LIVE="$ROOT/runs/work/s41_subset_ids/live20.json"

mkdir -p "$STEP_DIR" "$EVAL_DR" "$EVAL_LIVE" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== S45 start $(date -Is) ==="

test -n "${TAVILY_API_KEY:-}" || { echo "TAVILY_API_KEY missing"; exit 1; }
test -f "$ROOT/data/external/drbench/question_ids.json"
test -f "$ROOT/data/tasks/drbench/drbench_s45_v1/test.jsonl"
test -f "$ROOT/data/tasks/live/live_s41_v1/test.jsonl"

"$APP_PY" "$SERVE" status >/dev/null 2>&1 || true
"$APP_PY" "$SERVE" stop || true
sleep 2
"$APP_PY" "$SERVE" start --vllm-only

echo "=== DRBench 12 × B1/E0 ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset all --split test \
  --systems b1,e0 \
  --datasets drbench \
  --task-ids-file "$IDS_DR" \
  --tool-budget 8 --temperature 0.0 --web-mode replay \
  --out "$EVAL_DR" --resume

echo "=== live20 adjacent AB/BA ==="
"$APP_PY" - <<'PY'
import json, subprocess, os, sys
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
app = root / "envs/app/bin/python"
dev = root / "repo/training/sft/dev_eval.py"
eval_live = root / "runs/evaluation/eval_live_s45_0001"
slots = json.loads((root / "data/splits/s41_test_subsets.json").read_text())["subsets"]["live20"]["slots"]
env = os.environ.copy()
env["PYTHONPATH"] = f"{root}/repo/src:{root}/repo/scripts:{root}/repo:{root}/repo/training/sft"
for slot in slots:
    tid = slot["slot_id"]
    order = slot["run_order"]
    ids_path = eval_live / f"_tmp_{tid}.json"
    ids_path.write_text(json.dumps([tid]) + "\n", encoding="utf-8")
    for sys in order:
        cmd = [
            str(app), str(dev),
            "--root", str(root), "--mode", "tasks", "--subset", "all", "--split", "test",
            "--systems", sys, "--datasets", "live",
            "--task-ids-file", str(ids_path),
            "--tool-budget", "8", "--temperature", "0.0", "--web-mode", "live",
            "--out", str(eval_live), "--resume",
        ]
        print("RUN", tid, sys, flush=True)
        subprocess.check_call(cmd, env=env, cwd=str(root))
print("live_done", len(slots))
PY

"$APP_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
dr = root / "runs/evaluation/eval_drbench_s45_0001"
live = root / "runs/evaluation/eval_live_s45_0001"
step = root / "runs/steps/S45/a001"
dr_n = sum(sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) for p in dr.glob("results_*.jsonl"))
live_n = sum(sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) for p in live.glob("results_*.jsonl"))
complete = dr_n == 24 and live_n == 40
acc = {
    "step": "S45",
    "attempt": "a001",
    "result": "PASS" if complete else "PARTIAL",
    "drbench_runs": dr_n,
    "live_runs": live_n,
    "planned": {"drbench": 24, "live": 40},
    "mixed_into_main": False,
    "official_leaderboard_claim": False,
    "evaluation_ids": ["eval_drbench_s45_0001", "eval_live_s45_0001"],
    "time": datetime.now(timezone.utc).isoformat(),
}
step.mkdir(parents=True, exist_ok=True)
(step / "acceptance.json").write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    f"# S45 a001\n\n- result: **{acc['result']}**\n- drbench: {dr_n}/24\n- live: {live_n}/40\n- not mixed into main\n",
    encoding="utf-8",
)
(step / "evidence_index.json").write_text(
    json.dumps({"drbench": str(dr), "live": str(live), "snapshots": "data/snapshots/live"}, indent=2) + "\n"
)
print(json.dumps(acc, ensure_ascii=False))
PY
echo "=== S45 end $(date -Is) ==="
