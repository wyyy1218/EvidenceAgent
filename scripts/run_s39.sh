#!/usr/bin/env bash
# S39 remote: start vLLM with sft_e1+dpo_e2 → route probe → dev40 → select → dev160
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo/scripts:$ROOT/repo:$ROOT/repo/training/sft:${PYTHONPATH:-}"

APP_PY="$ROOT/envs/app/bin/python"
INFER_PY="$ROOT/envs/infer/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S39/a001"
EVAL40="$ROOT/runs/evaluation/eval_dev40_s39_0001"
EVAL160="$ROOT/runs/evaluation/eval_dev160_s39_0001"
PROBE_ID="probe_s39_vllm_route_a001"
LOG="$ROOT/runs/system/logs/s39_run.log"
mkdir -p "$STEP_DIR" "$EVAL40" "$EVAL160" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== S39 start $(date -Is) ==="

echo "=== require S38 PASS ==="
"$APP_PY" - <<'PY'
import json
from pathlib import Path
acc = Path("/root/autodl-tmp/evidence-agent/runs/steps/S38/a001/acceptance.json")
assert acc.is_file(), "missing S38"
rec = json.loads(acc.read_text())
assert rec.get("result") == "PASS", rec
adapter = Path("/root/autodl-tmp/evidence-agent/artifacts/adapters/dpo/exp_dpo_0001/adapter_model.safetensors")
assert adapter.is_file(), adapter
print("s38_ok", adapter)
PY

LORA_MODULES="sft_e1=$ROOT/artifacts/adapters/sft/exp_sft_0001,dpo_e2=$ROOT/artifacts/adapters/dpo/exp_dpo_0001"

echo "=== start vLLM with SFT + DPO LoRAs ==="
"$APP_PY" "$SERVE" stop || true
sleep 2
"$APP_PY" "$SERVE" start --vllm-only --lora-modules "$LORA_MODULES"

echo "=== T24 route probe (dpo_e2) ==="
"$INFER_PY" "$ROOT/repo/scripts/probe_vllm_route.py" --lora-name dpo_e2 --probe-id "$PROBE_ID"

echo "=== 40-task screening (e0, e1_final, e2_final) ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset 40 \
  --systems e0,e1_final,e2_final \
  --out "$EVAL40" --resume

echo "=== select E2 candidate on 40 ==="
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode select \
  --systems e0,e1_final,e2_final \
  --out "$EVAL40"

CHOSEN=$("$APP_PY" -c "import json; print(json.load(open('$EVAL40/selection.json'))['chosen_system'])")
echo "chosen40=$CHOSEN"
# Force E2 onto 160 if selection picked another for screening; plan: 选出 E2 + 同条件对照
RUN160="e0,e1_final,e2_final"

echo "=== 160-task full dev (same-condition) ==="
# dev_eval --subset choices are {40, all}; "all" == full 160-dev pack.
"$APP_PY" "$ROOT/repo/training/sft/dev_eval.py" \
  --root "$ROOT" --mode tasks --subset all \
  --systems "$RUN160" \
  --out "$EVAL160" --resume

echo "=== note E0/E1 reuse from S33 if identical ==="
"$APP_PY" - <<'PY'
import json, hashlib
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
s39 = root / "runs/evaluation/eval_dev160_s39_0001/summary.json"
s33 = root / "runs/evaluation/eval_dev160_s33_0001/summary.json"
note = {
    "s33_path": str(s33),
    "s39_path": str(s39),
    "e0_e1_reuse_policy": "same_snapshot_may_cite_s33; s39 re-ran same systems for same-batch record",
    "meets_target_scale": False,
}
(root / "runs/evaluation/eval_dev160_s39_0001/reuse_note.json").write_text(
    json.dumps(note, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps(note, ensure_ascii=False))
PY

echo "=== write S39 step record ==="
"$APP_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
step = root / "runs/steps/S39/a001"
step.mkdir(parents=True, exist_ok=True)
route = json.loads((root / f"runs/probes/probe_s39_vllm_route_a001/summary.json").read_text())
s40 = json.loads((root / "runs/evaluation/eval_dev40_s39_0001/selection.json").read_text())
s160 = json.loads((root / "runs/evaluation/eval_dev160_s39_0001/summary.json").read_text())
ok = bool(route.get("t24_pass") or (route.get("checks") or {}).get("t24_pass")) and "e2_final" in (s160.get("systems") or {})
rec = {
    "step": "S39",
    "attempt": "a001",
    "result": "PASS" if ok else "FAIL",
    "time": datetime.now(timezone.utc).isoformat(),
    "t24_pass": ok,
    "chosen40": s40.get("chosen_system"),
    "systems160": sorted((s160.get("systems") or {})),
    "meets_target_scale": False,
    "e2_metrics": (s160.get("systems") or {}).get("e2_final"),
}
(step / "acceptance.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    "\n".join([
        "# S39 a001",
        "",
        f"- result: {rec['result']}",
        f"- t24/route: ok={ok}",
        f"- chosen40: {rec['chosen40']}",
        f"- systems160: {rec['systems160']}",
        f"- meets_target_scale: false",
        "- note: E2 callable + same-condition dev required; not required to beat E1",
        "",
    ]),
    encoding="utf-8",
)
print(json.dumps({k: rec[k] for k in ("result", "chosen40", "systems160")}, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
PY

echo "=== S39 done $(date -Is) ==="
