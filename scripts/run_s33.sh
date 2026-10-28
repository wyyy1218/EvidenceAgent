#!/usr/bin/env bash
# S33 remote orchestrator: export route → quant/vLLM probe → state → 40 → select → 160
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo/scripts:$ROOT/repo:$ROOT/repo/training/sft:${PYTHONPATH:-}"

APP_PY="$ROOT/envs/app/bin/python"
INFER_PY="$ROOT/envs/infer/bin/python"
TRAIN_PY="$ROOT/envs/train/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S33/a001"
EVAL40="$ROOT/runs/evaluation/eval_dev40_s33_0001"
EVAL160="$ROOT/runs/evaluation/eval_dev160_s33_0001"
STATE_EVAL="$ROOT/runs/evaluation/eval_state_s33_0001"
QUANT="$ROOT/runs/evaluation/eval_quant_probe_s33_0001"
PROBE_ID="probe_s33_vllm_route_a001"
LOG="$ROOT/runs/system/logs/s33_run.log"
mkdir -p "$STEP_DIR" "$EVAL40" "$EVAL160" "$STATE_EVAL" "$QUANT" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== S33 start $(date -Is) ==="
echo "ROOT=$ROOT"

LORA_MODULES="sft_e1=$ROOT/artifacts/adapters/sft/exp_sft_0001,e1_ckpt_600=$ROOT/runs/training/exp_sft_0001/checkpoint-600"

echo "=== stop any prior services ==="
"$APP_PY" "$SERVE" stop || true
sleep 2

echo "=== start vLLM with SFT LoRAs ==="
"$APP_PY" "$SERVE" start --vllm-only --lora-modules "$LORA_MODULES"

echo "=== T24 route probe ==="
"$INFER_PY" "$ROOT/repo/scripts/probe_vllm_route.py" --lora-name sft_e1 --probe-id "$PROBE_ID"

echo "=== quant path probe (train env, stops after) ==="
# Quant path needs GPU; stop vLLM first for exclusive GPU, then restart for vLLM path.
"$APP_PY" "$SERVE" stop || true
sleep 3
"$TRAIN_PY" "$ROOT/repo/training/sft/quant_probe.py" \
  --root "$ROOT" --mode quant \
  --adapter-dir "$ROOT/artifacts/adapters/sft/exp_sft_0001" \
  --n 8 --out "$QUANT/quant_outputs.json"

echo "=== restart vLLM for parity + eval ==="
"$APP_PY" "$SERVE" start --vllm-only --lora-modules "$LORA_MODULES"
"$INFER_PY" "$ROOT/repo/training/sft/quant_probe.py" \
  --root "$ROOT" --mode vllm --adapter-name sft_e1 \
  --n 8 --out "$QUANT/vllm_outputs.json"
"$INFER_PY" "$ROOT/repo/training/sft/quant_probe.py" \
  --root "$ROOT" --mode compare --out "$QUANT/compare.json"

echo "=== state-level eval (dev states, capped) ==="
# Full 930 is expensive; S33 asks for rates on an independent set — use 128 stratified by hash order in file.
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode state \
  --systems e0,e1_ckpt_600,e1_final \
  --max-rows 128 \
  --out "$STATE_EVAL"

echo "=== 40-task screening ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset 40 \
  --systems e0,e1_ckpt_600,e1_final \
  --out "$EVAL40" --resume

echo "=== select E1 ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode select \
  --systems e0,e1_ckpt_600,e1_final \
  --out "$EVAL40"

CHOSEN=$("$APP_PY" -c "import json; print(json.load(open('$EVAL40/selection.json'))['chosen_system'])")
echo "chosen=$CHOSEN"

echo "=== 160-task full dev (E0 + chosen) ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset all \
  --systems "e0,$CHOSEN" \
  --out "$EVAL160" --resume

"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode report \
  --systems "e0,$CHOSEN" \
  --out "$EVAL160"

echo "=== write step acceptance stub ==="
"$APP_PY" - <<'PY'
import json, hashlib
from pathlib import Path
from datetime import datetime, timezone
root = Path("/root/autodl-tmp/evidence-agent")
step = root / "runs/steps/S33/a001"
probe = json.loads((root / "runs/probes/probe_s33_vllm_route_a001/summary.json").read_text())
cmp_ = json.loads((root / "runs/evaluation/eval_quant_probe_s33_0001/compare.json").read_text())
state = json.loads((root / "runs/evaluation/eval_state_s33_0001/state_summary.json").read_text())
sel = json.loads((root / "runs/evaluation/eval_dev40_s33_0001/selection.json").read_text())
full = json.loads((root / "runs/evaluation/eval_dev160_s33_0001/summary.json").read_text())
chosen = sel["chosen_system"]
t24 = bool(probe.get("t24_pass"))
route_ok = t24
quant_ok = float(cmp_.get("vllm_valid_rate") or 0) >= 0.5 and float(cmp_.get("quant_valid_rate") or 0) >= 0.5
state_ok = all(
    float((state.get("systems") or {}).get(s, {}).get("json_valid_rate") or 0) >= 0.5
    for s in ("e0", "e1_ckpt_600", "e1_final")
)
full_ok = "e0" in full.get("systems", {}) and chosen in full.get("systems", {})
overall = "PASS" if (route_ok and quant_ok and state_ok and full_ok) else "FAIL"
evidence = {
  "step": "S33",
  "attempt": "a001",
  "result": overall,
  "t24_pass": t24,
  "quant_compare": {k: cmp_.get(k) for k in ("n","quant_valid_rate","vllm_valid_rate","identical_rate","action_equal_rate")},
  "state_json_valid": {s: (state.get("systems") or {}).get(s, {}).get("json_valid_rate") for s in ("e0","e1_ckpt_600","e1_final")},
  "chosen_system": chosen,
  "dev40": sel,
  "dev160": full,
  "written_at": datetime.now(timezone.utc).isoformat(),
}
(step / "evidence_index.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
md = [
  "# S33 acceptance — a001",
  "",
  f"- **Date:** {datetime.now(timezone.utc).date()}",
  f"- **Result:** **{overall}**",
  f"- T24 route: {t24}",
  f"- Quant/vLLM valid rates: q={cmp_.get('quant_valid_rate')} v={cmp_.get('vllm_valid_rate')} action_eq={cmp_.get('action_equal_rate')}",
  f"- Chosen E1: `{chosen}`",
  f"- Dev160 systems: {list(full.get('systems', {}).keys())}",
  "",
  "## Notes",
  "- Effect vs E0 is recorded; loss is not used as quality proof.",
  "- Writer/Verifier remain on base; policy uses the chosen adapter.",
]
(step / "acceptance.md").write_text("\n".join(md) + "\n", encoding="utf-8")
if overall != "PASS":
    (step / "failure.md").write_text(f"# S33 failure\n\nSee evidence_index.json\n", encoding="utf-8")
print("S33_RESULT", overall)
PY

echo "=== S33 done $(date -Is) ==="
