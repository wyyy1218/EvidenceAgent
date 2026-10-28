#!/usr/bin/env bash
# S44: budget curve b4/b12 + stability seed43/44 @ temp 0.3 for B1+E0 on budget_stability60.
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
STEP_DIR="$ROOT/runs/steps/S44/a001"
EVAL_BUDGET="$ROOT/runs/evaluation/eval_budget_s44_0001"
EVAL_STAB="$ROOT/runs/evaluation/eval_stability_s44_0001"
LOG="$ROOT/runs/system/logs/s44_run.log"
IDS="$ROOT/runs/work/s41_subset_ids/budget_stability60.json"
REPORT="$ROOT/artifacts/reports/rpt_s44_0001"

mkdir -p "$STEP_DIR" "$EVAL_BUDGET" "$EVAL_STAB" "$(dirname "$LOG")" "$REPORT/tables" "$REPORT/figures"
exec > >(tee -a "$LOG") 2>&1
echo "=== S44 start $(date -Is) ==="

"$APP_PY" - <<'PY'
import json
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
acc = json.loads((root / "runs/steps/S42/a001/acceptance.json").read_text())
assert acc.get("result") == "PASS", acc
print("s42_ok")
PY

"$APP_PY" "$ROOT/repo/scripts/export_s41_task_ids.py" --root "$ROOT" --subset budget_stability60 --out "$IDS"

"$APP_PY" "$SERVE" status >/dev/null 2>&1 || true
"$APP_PY" "$SERVE" stop || true
sleep 2
"$APP_PY" "$SERVE" start --vllm-only

for B in 4 12; do
  echo "=== budget curve tool_budget=$B ==="
  "$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
    --root "$ROOT" --mode tasks --subset all --split test \
    --systems b1,e0 \
    --task-ids-file "$IDS" \
    --tool-budget "$B" --temperature 0.0 \
    --out "$EVAL_BUDGET" --resume
done

echo "=== reuse b8 from main for budget_stability60 ==="
"$APP_PY" - <<PY
import json
from pathlib import Path
root = Path("$ROOT")
ids = set(json.loads(Path("$IDS").read_text(encoding="utf-8")))
out = Path("$EVAL_BUDGET")
for sys in ("b1", "e0"):
    src = root / f"runs/evaluation/eval_main_s42_0001/results_{sys}.jsonl"
    dst = out / f"results_{sys}_b8_reuse.jsonl"
    rows = []
    for ln in src.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        row = json.loads(ln)
        if row.get("task_id") in ids:
            row = dict(row)
            row.setdefault("result", {})
            if isinstance(row["result"], dict):
                row["result"]["tool_budget"] = 8
                row["result"]["reused_from"] = "eval_main_s42_0001"
            rows.append(row)
    dst.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(sys, len(rows))
PY

for SEED in 43 44; do
  echo "=== stability seed=$SEED temp=0.3 ==="
  "$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
    --root "$ROOT" --mode tasks --subset all --split test \
    --systems b1,e0 \
    --task-ids-file "$IDS" \
    --tool-budget 8 --temperature 0.3 --seed "$SEED" \
    --out "$EVAL_STAB" --resume
done

"$APP_PY" "$ROOT/repo/scripts/build_s44_report.py" --root "$ROOT" --out "$REPORT"

"$APP_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
budget = root / "runs/evaluation/eval_budget_s44_0001"
stab = root / "runs/evaluation/eval_stability_s44_0001"
step = root / "runs/steps/S44/a001"
counts = {}
for p in list(budget.glob("results_*.jsonl")) + list(stab.glob("results_*.jsonl")):
    counts[p.name] = sum(1 for ln in p.open(encoding="utf-8") if ln.strip())
# expected new runs: b4/b12 * 2 systems * 60 = 240; stability 2 seeds * 2 * 60 = 240
new_budget = sum(v for k, v in counts.items() if "_b4" in k or "_b12" in k)
new_stab = sum(v for k, v in counts.items() if "seed" in k)
reuse = sum(v for k, v in counts.items() if "b8_reuse" in k)
complete = new_budget == 240 and new_stab == 240 and reuse == 120
acc = {
    "step": "S44",
    "attempt": "a001",
    "result": "PASS" if complete else "PARTIAL",
    "n_new_budget": new_budget,
    "n_new_stability": new_stab,
    "n_b8_reuse": reuse,
    "file_counts": counts,
    "evaluation_ids": ["eval_budget_s44_0001", "eval_stability_s44_0001"],
    "report": "artifacts/reports/rpt_s44_0001",
    "time": datetime.now(timezone.utc).isoformat(),
}
step.mkdir(parents=True, exist_ok=True)
(step / "acceptance.json").write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    f"# S44 a001\n\n- result: **{acc['result']}**\n- budget new: {new_budget}/240\n- stability new: {new_stab}/240\n- b8 reuse: {reuse}/120\n",
    encoding="utf-8",
)
(step / "evidence_index.json").write_text(json.dumps({"counts": counts, "report": str(root / "artifacts/reports/rpt_s44_0001")}, indent=2) + "\n")
print(json.dumps(acc, ensure_ascii=False)[:2000])
PY
echo "=== S44 end $(date -Is) ==="
