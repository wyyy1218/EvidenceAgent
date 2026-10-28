#!/usr/bin/env bash
# S06: create four Python 3.11 envs and freeze locks. Run on AutoDL data disk.
set -euo pipefail

WORK_ROOT="${WORK_ROOT:-/root/autodl-tmp/evidence-agent}"
REPO="$WORK_ROOT/repo"
LOCKS="$REPO/locks"
LOG_DIR="$WORK_ROOT/runs/work/setup_envs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR" "$LOCKS" \
  "$WORK_ROOT/envs/cache/"{uv,pip,huggingface,torch,xdg} \
  "$WORK_ROOT/envs/"{app,infer,train,judge}

export UV_CACHE_DIR="$WORK_ROOT/envs/cache/uv"
export PIP_CACHE_DIR="$WORK_ROOT/envs/cache/pip"
export HF_HOME="$WORK_ROOT/envs/cache/huggingface"
export TORCH_HOME="$WORK_ROOT/envs/cache/torch"
export XDG_CACHE_HOME="$WORK_ROOT/envs/cache/xdg"

# Use the locally provisioned CPython 3.11 (conda) instead of uv's GitHub download.
PYTHON_311="${PYTHON_311:-$WORK_ROOT/envs/py311/bin/python}"
if [ ! -x "$PYTHON_311" ]; then
  echo "Python 3.11 interpreter missing: $PYTHON_311" >&2
  echo "Create it first: conda create -y -p $WORK_ROOT/envs/py311 python=3.11" >&2
  exit 3
fi
"$PYTHON_311" -V

# Capacity gate
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo /root/miniconda3/bin/python)}"
"$PYTHON_BIN" - <<'PY'
import os, sys
from pathlib import Path
p = Path("/root/autodl-tmp")
st = os.statvfs(p)
gib = st.f_frsize * st.f_blocks / (1024**3)
print(f"data_disk_total_gib={gib:.2f}")
if gib < 100:
    print("CAPACITY_GATE_FAIL", file=sys.stderr)
    sys.exit(2)
print("CAPACITY_GATE_PASS")
PY

# Ensure uv
if ! command -v uv >/dev/null 2>&1; then
  export PATH="/root/miniconda3/bin:$PATH"
fi
uv --version | tee "$LOG_DIR/uv_version.txt"

install_env() {
  local name="$1"
  shift
  local venv="$WORK_ROOT/envs/$name"
  echo "=== setup $name ===" | tee -a "$LOG_DIR/setup.log"
  if [ "${CLEAN_ENVS:-0}" = "1" ]; then rm -rf "$venv"; fi
  if [ ! -x "$venv/bin/python" ]; then
    uv venv --python "$PYTHON_311" "$venv"
  fi
  # shellcheck disable=SC1090
  source "$venv/bin/activate"
  uv pip install "$@" 2>&1 | tee "$LOG_DIR/${name}_install.log"
  uv pip freeze | tee "$LOCKS/${name}.txt"
  python -V | tee "$LOG_DIR/${name}_python.txt"
  deactivate || true
}

# app: CPU-only torch (embedding/reranker are CPU by design; do not pull CUDA twice)
if [ ! -x "$WORK_ROOT/envs/app/bin/python" ]; then
  uv venv --python "$PYTHON_311" "$WORK_ROOT/envs/app"
fi
source "$WORK_ROOT/envs/app/bin/activate"
uv pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0" 2>&1 | tee "$LOG_DIR/app_torch_cpu.log"
deactivate || true
install_env app \
  "deepagents==0.7.32" \
  "fastapi" "uvicorn[standard]" "httpx" "pydantic" "streamlit" \
  "langgraph" "faiss-cpu" "sentence-transformers" "huggingface-hub" \
  "numpy" "pyyaml" "python-dotenv" "openai"

# infer: do NOT pin torch separately (vLLM decides its torch/CUDA wheels)
install_env infer "vllm==0.10.2"

# train: explicit torch CUDA 12.8 wheel index
install_env train \
  --index-url https://download.pytorch.org/whl/cu128 \
  --extra-index-url https://pypi.org/simple \
  "torch==2.8.0" \
  "transformers==4.56.2" \
  "peft==0.17.1" \
  "trl==0.23.1" \
  "bitsandbytes==0.47.0" \
  "accelerate" "datasets" "sentencepiece" "protobuf"

# judge: MiniCheck official packaging; CPU torch is sufficient for offline English checks
if [ ! -x "$WORK_ROOT/envs/judge/bin/python" ]; then
  uv venv --python "$PYTHON_311" "$WORK_ROOT/envs/judge"
fi
source "$WORK_ROOT/envs/judge/bin/activate"
uv pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.8.0" 2>&1 | tee "$LOG_DIR/judge_torch_cpu.log"
deactivate || true
install_env judge \
  "git+https://github.com/Liyan06/MiniCheck.git" \
  "transformers" "sentencepiece" "protobuf" "nltk" "openai"

# Record meta
{
  echo "uv=$(uv --version)"
  echo "when=$(date -Iseconds)"
  echo "host=$(hostname)"
  echo "work_root=$WORK_ROOT"
} | tee "$LOG_DIR/meta.txt" "$LOCKS/resolve_meta.txt"

echo "SETUP_ENVS_OK log=$LOG_DIR"
