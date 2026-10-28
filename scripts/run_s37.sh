#!/usr/bin/env bash
# S37 remote: stop vLLM → validate-cache → t23 → probe
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
STEP_DIR="$ROOT/runs/steps/S37/a001"
PROBE_DIR="$ROOT/runs/probes"
LOG="$ROOT/runs/system/logs/s37_run.log"
mkdir -p "$STEP_DIR" "$PROBE_DIR" "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "=== S37 start $(date -Is) ==="
echo "ROOT=$ROOT"

echo "=== stop vLLM / free GPU ==="
"$APP_PY" "$SERVE" stop || true
sleep 3
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader || true

echo "=== unit tests (no pytest dependency) ==="
"$TRAIN_PY" - <<'PY'
import importlib.util
from pathlib import Path
path = Path("/root/autodl-tmp/evidence-agent/repo/tests/unit/test_dpo_reference.py")
spec = importlib.util.spec_from_file_location("test_dpo_reference", path)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
failed = []
for name in sorted(n for n in dir(mod) if n.startswith("test_")):
    try:
        getattr(mod, name)()
        print("PASS", name)
    except Exception as exc:  # noqa: BLE001
        failed.append((name, f"{type(exc).__name__}: {exc}"))
        print("FAIL", name, failed[-1][1])
if failed:
    raise SystemExit(f"unit failures: {failed}")
print("unit_ok", sum(1 for n in dir(mod) if n.startswith("test_")))
PY

echo "=== verify SFT + DPO data ==="
"$TRAIN_PY" - <<'PY'
import hashlib, json
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
sft = root / "artifacts/adapters/sft/exp_sft_0001/adapter_model.safetensors"
h = hashlib.sha256(sft.read_bytes()).hexdigest()
print("sft_sha", h[:16], "full", h)
assert h.startswith("4e8b60a0"), h
train = root / "data/dpo/dpo_s36_v1/train.jsonl"
dev = root / "data/dpo/dpo_s36_v1/dev.jsonl"
nt = sum(1 for ln in train.open() if ln.strip())
nd = sum(1 for ln in dev.open() if ln.strip())
print("dpo train", nt, "dev", nd)
assert nt == 315 and nd == 89
print("data_ok")
PY

echo "=== validate-cache (builds reference_cache if needed) ==="
"$TRAIN_PY" "$ROOT/repo/training/dpo/train_dpo.py" \
  --root "$ROOT" --mode validate-cache \
  --output-dir "$PROBE_DIR/dpo_validate_cache_s37"

echo "=== T23 fault injection (expect non-zero / blocked) ==="
set +e
"$TRAIN_PY" "$ROOT/repo/training/dpo/train_dpo.py" \
  --root "$ROOT" --mode t23 \
  --output-dir "$PROBE_DIR/dpo_t23_s37"
T23_RC=$?
set -e
echo "t23_exit=$T23_RC"
test "$T23_RC" -eq 4

echo "=== DPO probe ==="
"$TRAIN_PY" "$ROOT/repo/training/dpo/train_dpo.py" \
  --root "$ROOT" --mode probe \
  --experiment-id probe_dpo_s37_0001 \
  --output-dir "$PROBE_DIR/probe_dpo_s37_0001"

echo "=== write S37 step record ==="
"$TRAIN_PY" - <<'PY'
import json, shutil
from pathlib import Path
from datetime import datetime, timezone
root = Path("/root/autodl-tmp/evidence-agent")
step = root / "runs/steps/S37/a001"
step.mkdir(parents=True, exist_ok=True)
val = json.loads((root / "runs/probes/dpo_validate_cache_s37/validate_cache.json").read_text())
t23 = json.loads((root / "runs/probes/dpo_t23_s37/t23.json").read_text())
probe = json.loads((root / "runs/probes/probe_dpo_s37_0001/summary.json").read_text())
ok = bool(val.get("ok") and t23.get("t23_blocked") and probe.get("ok"))
rec = {
    "step": "S37",
    "attempt": "a001",
    "result": "PASS" if ok else "FAIL",
    "time": datetime.now(timezone.utc).isoformat(),
    "validate_cache": {k: val.get(k) for k in ("ok", "atol", "cache_key", "rebuilt", "failures")},
    "t23": {k: t23.get(k) for k in ("t23_blocked", "misconfigured", "message")},
    "probe": {
        k: probe.get(k)
        for k in (
            "ok", "experiment_id", "train_samples", "global_step",
            "peak_vram_mib", "reference_unchanged", "train_changed", "adapter_hash",
        )
    },
}
(step / "acceptance.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
(step / "acceptance.md").write_text(
    "\n".join([
        "# S37 a001",
        "",
        f"- result: {rec['result']}",
        f"- validate_cache.ok: {val.get('ok')}",
        f"- t23_blocked: {t23.get('t23_blocked')}",
        f"- probe.ok: {probe.get('ok')}",
        f"- peak_vram_mib: {probe.get('peak_vram_mib')}",
        f"- reference_unchanged: {probe.get('reference_unchanged')}",
        "",
    ]),
    encoding="utf-8",
)
print(json.dumps(rec, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
PY

echo "=== S37 done $(date -Is) ==="
