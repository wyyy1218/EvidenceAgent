#!/usr/bin/env bash
# S43: E0 ablations on frozen ablation100 (no_source_anchor + hide_visible_budget).
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo/scripts:$ROOT/repo:$ROOT/repo/training/sft:${PYTHONPATH:-}"
# shellcheck disable=SC1091
set -a; source "$ROOT/runs/system/private.env" 2>/dev/null || true; set +a

APP_PY="$ROOT/envs/app/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S43/a001"
EVAL="$ROOT/runs/evaluation/eval_ablation_s43_0001"
LOG="$ROOT/runs/system/logs/s43_run.log"
IDS="$ROOT/runs/work/s41_subset_ids/ablation100.json"
MAIN_E0="$ROOT/runs/evaluation/eval_main_s42_0001/results_e0.jsonl"

mkdir -p "$STEP_DIR" "$EVAL" "$(dirname "$LOG")" "$(dirname "$IDS")"
exec > >(tee -a "$LOG") 2>&1
echo "=== S43 start $(date -Is) ==="

test -f "$ROOT/runs/steps/S42/a001/acceptance.json"
"$APP_PY" - <<'PY'
import json
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
acc = json.loads((root / "runs/steps/S42/a001/acceptance.json").read_text())
assert acc.get("result") == "PASS", acc
assert (root / "runs/evaluation/eval_main_s42_0001/results_e0.jsonl").is_file()
print("s42_ok", acc.get("n_runs_observed"))
PY

"$APP_PY" "$ROOT/repo/scripts/export_s41_task_ids.py" --root "$ROOT" --subset ablation100 --out "$IDS"

"$APP_PY" "$SERVE" status >/dev/null 2>&1 || true
"$APP_PY" "$SERVE" stop || true
sleep 2
"$APP_PY" "$SERVE" start --vllm-only

for VARIANT in no_source_anchor hide_visible_budget; do
  echo "=== variant $VARIANT ==="
  "$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
    --root "$ROOT" --mode tasks --subset all --split test \
    --systems e0 \
    --task-ids-file "$IDS" \
    --variant "$VARIANT" \
    --tool-budget 8 --temperature 0.0 \
    --out "$EVAL" --resume
done

echo "=== control index from main e0 ==="
"$APP_PY" - <<PY
import json
from pathlib import Path
root = Path("$ROOT")
ids = set(json.loads(Path("$IDS").read_text(encoding="utf-8")))
main = Path("$MAIN_E0")
ctrl = []
for ln in main.read_text(encoding="utf-8").splitlines():
    if not ln.strip():
        continue
    row = json.loads(ln)
    if row.get("task_id") in ids:
        ctrl.append({"task_id": row["task_id"], "system": "e0", "source": "eval_main_s42_0001", "score": row.get("score")})
out = Path("$EVAL") / "control_e0_ablation100.jsonl"
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ctrl) + "\n", encoding="utf-8")
print({"control_n": len(ctrl)})
PY

"$APP_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
eval_dir = root / "runs/evaluation/eval_ablation_s43_0001"
step = root / "runs/steps/S43/a001"
counts = {}
for v in ("no_source_anchor", "hide_visible_budget"):
    p = eval_dir / f"results_e0_{v}.jsonl"
    n = sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) if p.is_file() else 0
    counts[v] = n
ctrl = eval_dir / "control_e0_ablation100.jsonl"
ctrl_n = sum(1 for ln in ctrl.open(encoding="utf-8") if ln.strip()) if ctrl.is_file() else 0
complete = counts.get("no_source_anchor") == 100 and counts.get("hide_visible_budget") == 100 and ctrl_n == 100
acc = {
    "step": "S43",
    "attempt": "a001",
    "result": "PASS" if complete else "PARTIAL",
    "n_runs_planned": 200,
    "n_runs_observed": sum(counts.values()),
    "per_variant_n": counts,
    "control_e0_n": ctrl_n,
    "ablation_base": "e0",
    "hard_budget_unchanged": True,
    "evaluation_id": "eval_ablation_s43_0001",
    "time": datetime.now(timezone.utc).isoformat(),
}
step.mkdir(parents=True, exist_ok=True)
(step / "acceptance.json").write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    f"# S43 a001 — ablations\n\n- result: **{acc['result']}**\n- variants: {counts}\n- control_e0: {ctrl_n}\n",
    encoding="utf-8",
)
(step / "evidence_index.json").write_text(
    json.dumps(
        {
            "evaluation": str(eval_dir),
            "control": str(ctrl),
            "limitations": "repo/docs/evaluation/limitations.md",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps(acc, ensure_ascii=False))
PY
echo "=== S43 end $(date -Is) ==="
