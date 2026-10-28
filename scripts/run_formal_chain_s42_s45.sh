#!/usr/bin/env bash
# Watchdog + sequential S42 → S43 → S44 → S45. Safe with an already-running s42 tmux.
# Resume-safe; never deletes results_*.jsonl.
set -euo pipefail
ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
cd "$ROOT"
export WORK_ROOT="$ROOT"
LOG="$ROOT/runs/system/logs/formal_chain_s42_s45.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

APP_PY="$ROOT/envs/app/bin/python"
POLL_SEC="${FORMAL_CHAIN_POLL_SEC:-120}"

echo "=== formal_chain start $(date -Is) ==="

s42_complete() {
  "$APP_PY" - <<'PY'
import json
from pathlib import Path
root = Path("/root/autodl-tmp/evidence-agent")
eval_dir = root / "runs/evaluation/eval_main_s42_0001"
systems = ["b0", "b1", "b2", "e0", "e1", "e2"]
counts = {}
for s in systems:
    p = eval_dir / f"results_{s}.jsonl"
    n = sum(1 for ln in p.open(encoding="utf-8") if ln.strip()) if p.is_file() else 0
    counts[s] = n
acc_p = root / "runs/steps/S42/a001/acceptance.json"
acc_ok = False
if acc_p.is_file():
    try:
        acc_ok = json.loads(acc_p.read_text(encoding="utf-8")).get("result") == "PASS"
    except Exception:
        acc_ok = False
ok = all(counts.get(s, 0) == 300 for s in systems) and acc_ok
print("COMPLETE" if ok else "INCOMPLETE")
print(json.dumps(counts, ensure_ascii=False))
raise SystemExit(0 if ok else 1)
PY
}

step_pass() {
  local step="$1"
  local p="$ROOT/runs/steps/$step/a001/acceptance.json"
  [[ -f "$p" ]] || return 1
  "$APP_PY" -c "import json,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); sys.exit(0 if a.get('result')=='PASS' else 1)" "$p"
}

ensure_s42_tmux() {
  if tmux has-session -t s42 2>/dev/null; then
    echo "s42 tmux already running"
    return 0
  fi
  echo "starting s42 tmux (resume)"
  tmux new-session -d -s s42 "bash $ROOT/repo/scripts/run_s42.sh"
}

# --- S42 ---
if s42_complete; then
  echo "S42 already PASS"
else
  echo "S42 incomplete — watchdog until PASS"
  ensure_s42_tmux
  while ! s42_complete; do
    if ! tmux has-session -t s42 2>/dev/null; then
      echo "WARN: s42 tmux gone while incomplete — restart $(date -Is)"
      ensure_s42_tmux
    fi
    # light progress line
    wc -l "$ROOT"/runs/evaluation/eval_main_s42_0001/results_*.jsonl 2>/dev/null | tail -n 20 || true
    sleep "$POLL_SEC"
  done
  echo "S42 PASS $(date -Is)"
fi

# --- S43 ---
if step_pass S43; then
  echo "S43 already PASS"
else
  echo "=== launching S43 $(date -Is) ==="
  bash "$ROOT/repo/scripts/run_s43.sh"
  step_pass S43 || { echo "S43 did not PASS"; exit 1; }
fi

# --- S44 ---
if step_pass S44; then
  echo "S44 already PASS"
else
  echo "=== launching S44 $(date -Is) ==="
  bash "$ROOT/repo/scripts/run_s44.sh"
  step_pass S44 || { echo "S44 did not PASS"; exit 1; }
fi

# --- S45 ---
if step_pass S45; then
  echo "S45 already PASS"
else
  echo "=== launching S45 $(date -Is) ==="
  bash "$ROOT/repo/scripts/run_s45.sh"
  step_pass S45 || { echo "S45 did not PASS"; exit 1; }
fi

echo "=== formal_chain ALL DONE $(date -Is) ==="
