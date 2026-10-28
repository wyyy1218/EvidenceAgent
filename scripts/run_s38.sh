#!/usr/bin/env bash
# S38 remote: formal DPO exp_dpo_0001 (requires S37 PASS, GPU free)
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$ROOT/repo/src:$ROOT/repo:$ROOT/repo/training/dpo:${PYTHONPATH:-}"

APP_PY="$ROOT/envs/app/bin/python"
TRAIN_PY="$ROOT/envs/train/bin/python"
SERVE="$ROOT/repo/scripts/serve.py"
STEP_DIR="$ROOT/runs/steps/S38/a001"
OUT="$ROOT/runs/training/exp_dpo_0001"
ADAPTER="$ROOT/artifacts/adapters/dpo/exp_dpo_0001"
LOG="$ROOT/runs/system/logs/s38_run.log"
mkdir -p "$STEP_DIR" "$OUT" "$ADAPTER" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== S38 start $(date -Is) ==="
echo "ROOT=$ROOT"

echo "=== ensure GPU free ==="
"$APP_PY" "$SERVE" stop || true
sleep 2
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader || true

echo "=== require S37 PASS ==="
"$TRAIN_PY" - <<'PY'
import json
from pathlib import Path
acc = Path("/root/autodl-tmp/evidence-agent/runs/steps/S37/a001/acceptance.json")
assert acc.is_file(), "missing S37 acceptance"
rec = json.loads(acc.read_text())
assert rec.get("result") == "PASS", rec
print("s37_ok")
PY

echo "=== freeze formal DPO manifest ==="
"$TRAIN_PY" - <<'PY'
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
out = root / "runs/training/exp_dpo_0001"
out.mkdir(parents=True, exist_ok=True)
sft = root / "artifacts/adapters/sft/exp_sft_0001/adapter_model.safetensors"
sft_sha = hashlib.sha256(sft.read_bytes()).hexdigest()
cache_man = json.loads((root / "data/dpo/dpo_s36_v1/reference_cache/manifest.json").read_text())
import yaml
dpo = (yaml.safe_load((root / "repo/configs/project.yaml").read_text()) or {}).get("training", {}).get("dpo") or {}
man = {
    "experiment_id": "exp_dpo_0001",
    "dataset_id": "dpo_s36_v1",
    "train_pairs": 315,
    "dev_pairs": 89,
    "meets_target_scale": False,
    "preference_scope": "action_json_only_not_full_trajectory",
    "sft_adapter_sha": sft_sha,
    "sft_adapter_dir": "artifacts/adapters/sft/exp_sft_0001",
    "reference_cache_key": cache_man.get("cache_key"),
    "reference_definition": "frozen_sft_adapter_not_base",
    "hyperparams": dpo,
    "seed": 42,
    "frozen_at": datetime.now(timezone.utc).isoformat(),
}
(out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"cache_key": man["reference_cache_key"], "sft_sha": sft_sha[:16]}, ensure_ascii=False))
PY

echo "=== formal DPO train ==="
"$TRAIN_PY" "$ROOT/repo/training/dpo/train_dpo.py" \
  --root "$ROOT" --mode formal \
  --experiment-id exp_dpo_0001 \
  --output-dir "$OUT" \
  --adapter-dir "$ADAPTER"

echo "=== write S38 step record ==="
"$TRAIN_PY" - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
step = root / "runs/steps/S38/a001"
step.mkdir(parents=True, exist_ok=True)
summary = json.loads((root / "runs/training/exp_dpo_0001/summary.json").read_text())
man = json.loads((root / "runs/training/exp_dpo_0001/manifest.json").read_text())
ok = bool(summary.get("ok")) and summary.get("reference_unchanged") and bool(summary.get("adapter_hash"))
rec = {
    "step": "S38",
    "attempt": "a001",
    "result": "PASS" if ok else "FAIL",
    "time": datetime.now(timezone.utc).isoformat(),
    "experiment_id": "exp_dpo_0001",
    "meets_target_scale": False,
    "train_pairs": summary.get("train_samples"),
    "updates_estimated": summary.get("updates_estimated"),
    "global_step": summary.get("global_step"),
    "peak_vram_mib": summary.get("peak_vram_mib"),
    "nan_detected": summary.get("nan_detected"),
    "reference_unchanged": summary.get("reference_unchanged"),
    "adapter_hash": summary.get("adapter_hash"),
    "reference_cache_key": man.get("reference_cache_key"),
    "preference_scope": man.get("preference_scope"),
}
(step / "acceptance.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    "\n".join([
        "# S38 a001",
        "",
        f"- result: {rec['result']}",
        f"- experiment_id: exp_dpo_0001",
        f"- meets_target_scale: false (315 != 600)",
        f"- train_pairs: {rec['train_pairs']}",
        f"- updates_estimated: {rec['updates_estimated']}",
        f"- global_step: {rec['global_step']}",
        f"- reference_unchanged: {rec['reference_unchanged']}",
        f"- nan_detected: {rec['nan_detected']}",
        f"- adapter_hash: {rec['adapter_hash']}",
        "",
    ]),
    encoding="utf-8",
)
print(json.dumps(rec, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
PY

echo "=== S38 done $(date -Is) ==="
