#!/usr/bin/env python3
"""Unified start/stop for vLLM + API + UI (S08 minimal link)."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env, work_root  # noqa: E402


def state_path(root: Path) -> Path:
    return root / "runs" / "system" / "service_state.json"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def write_state(root: Path, data: dict) -> None:
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_state(root: Path) -> dict:
    p = state_path(root)
    if not p.is_file():
        return {"services": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def find_model_dir(root: Path) -> Path:
    base = root / "models" / "base"
    if not base.is_dir():
        raise SystemExit("models/base missing — run download_models.py first")
    revs = [p for p in base.iterdir() if p.is_dir()]
    if not revs:
        raise SystemExit("no base revision directory")
    # prefer longest sha-like name
    return sorted(revs, key=lambda p: p.name)[-1]


def ensure_probe_lora(root: Path, model_dir: Path) -> Path | None:
    """Create a tiny probe-only LoRA adapter for vLLM --lora-modules (not formal SFT)."""
    adapter = root / "artifacts" / "checkpoints" / "exp_probe_s07_0001" / "adapter"
    marker = adapter.parent / "PROBE_MARKER.txt"
    if (adapter / "adapter_config.json").is_file():
        return adapter
    train_py = root / "envs" / "train" / "bin" / "python"
    if not train_py.is_file():
        return None
    adapter.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("probe_only_not_sft\n", encoding="utf-8")
    code = f"""
import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM
p={str(model_dir)!r}
out={str(adapter)!r}
m=AutoModelForCausalLM.from_pretrained(p, torch_dtype=torch.bfloat16, device_map='cpu', trust_remote_code=True)
m=get_peft_model(m, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.0, target_modules=['q_proj','v_proj'], bias='none', task_type='CAUSAL_LM'))
m.save_pretrained(out)
print('PROBE_LORA_SAVED', out)
"""
    log = root / "runs" / "system" / "logs" / "probe_lora_init.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n# init {datetime.now(timezone.utc).isoformat()}\n")
        proc = subprocess.run([str(train_py), "-c", code], stdout=f, stderr=subprocess.STDOUT, cwd=str(root))
    if proc.returncode != 0 or not (adapter / "adapter_config.json").is_file():
        return None
    return adapter


def start_vllm(
    root: Path, model_dir: Path, lora_modules: list[str] | None = None
) -> subprocess.Popen:
    infer_py = root / "envs" / "infer" / "bin" / "python"
    log = root / "runs" / "system" / "logs" / "vllm.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(infer_py),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(model_dir),
        "--host",
        "127.0.0.1",
        "--port",
        "8001",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "8192",
        "--gpu-memory-utilization",
        "0.80",
        "--max-num-seqs",
        "2",
        "--enable-lora",
        "--max-lora-rank",
        "16",
        "--served-model-name",
        "Qwen/Qwen3-4B-Instruct-2507",
    ]
    if lora_modules:
        cmd.append("--lora-modules")
        cmd.extend(lora_modules)
    else:
        probe_lora = ensure_probe_lora(root, model_dir)
        if probe_lora is not None:
            cmd.extend(["--lora-modules", f"probe_s07_tmp_lora={probe_lora}"])

    f = open(log, "a", encoding="utf-8")
    f.write(f"\n# start {datetime.now(timezone.utc).isoformat()} {' '.join(cmd)}\n")
    f.flush()
    env = os.environ.copy()
    env.setdefault("HF_HUB_OFFLINE", "1")
    env.setdefault("TRANSFORMERS_OFFLINE", "1")
    # Detach from caller session so SSH/tmux exit does not SIGHUP services.
    return subprocess.Popen(
        cmd,
        stdout=f,
        stderr=subprocess.STDOUT,
        cwd=str(root),
        env=env,
        start_new_session=True,
    )


def start_api(root: Path) -> subprocess.Popen:
    app_py = root / "envs" / "app" / "bin" / "python"
    log = root / "runs" / "system" / "logs" / "api.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "repo" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["WORK_ROOT"] = str(root)
    cmd = [
        str(app_py),
        "-m",
        "uvicorn",
        "evidence_agent.api.app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "6008",
    ]
    f = open(log, "a", encoding="utf-8")
    return subprocess.Popen(
        cmd,
        stdout=f,
        stderr=subprocess.STDOUT,
        cwd=str(root / "repo"),
        env=env,
        start_new_session=True,
    )


def start_worker(root: Path) -> subprocess.Popen:
    app_py = root / "envs" / "app" / "bin" / "python"
    if not app_py.is_file():
        app_py = Path(sys.executable)
    log = root / "runs" / "system" / "logs" / "worker.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "repo" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["WORK_ROOT"] = str(root)
    cmd = [str(app_py), "-m", "evidence_agent.worker"]
    f = open(log, "a", encoding="utf-8")
    return subprocess.Popen(
        cmd,
        stdout=f,
        stderr=subprocess.STDOUT,
        cwd=str(root / "repo"),
        env=env,
        start_new_session=True,
    )


def start_ui(root: Path) -> subprocess.Popen:
    app_py = root / "envs" / "app" / "bin" / "python"
    log = root / "runs" / "system" / "logs" / "ui.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "repo" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["WORK_ROOT"] = str(root)
    env.setdefault("EVIDENCE_AGENT_API_URL", "http://127.0.0.1:6008")
    ui = root / "repo" / "src" / "evidence_agent" / "ui" / "app.py"
    cmd = [
        str(app_py),
        "-m",
        "streamlit",
        "run",
        str(ui),
        "--server.address",
        "0.0.0.0",
        "--server.port",
        "6006",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    f = open(log, "a", encoding="utf-8")
    return subprocess.Popen(
        cmd,
        stdout=f,
        stderr=subprocess.STDOUT,
        cwd=str(root / "repo"),
        env=env,
        start_new_session=True,
    )


def wait_http(url: str, timeout: int = 60) -> None:
    import urllib.request

    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    print(f"ready {url}")
                    return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise SystemExit(f"timeout waiting for {url}")



def cmd_start(args: argparse.Namespace) -> int:
    root = ensure_cache_env()
    load_dotenv(root / "runs" / "system" / "private.env")
    # map alternate env names
    if os.environ.get("API_BEARER_TOKEN") and not os.environ.get("EVIDENCE_AGENT_API_TOKEN"):
        os.environ["EVIDENCE_AGENT_API_TOKEN"] = os.environ["API_BEARER_TOKEN"]
    if os.environ.get("UI_PASSWORD") and not os.environ.get("EVIDENCE_AGENT_UI_PASSWORD"):
        os.environ["EVIDENCE_AGENT_UI_PASSWORD"] = os.environ["UI_PASSWORD"]

    if not os.environ.get("EVIDENCE_AGENT_API_TOKEN"):
        # generate ephemeral for probe if missing
        token = "ea_dev_" + hashlib_token()
        os.environ["EVIDENCE_AGENT_API_TOKEN"] = token
        append_env(root / "runs" / "system" / "private.env", "EVIDENCE_AGENT_API_TOKEN", token)
        append_env(root / "runs" / "system" / "private.env", "API_BEARER_TOKEN", token)
    if not os.environ.get("EVIDENCE_AGENT_UI_PASSWORD"):
        pwd = "ea_ui_" + hashlib_token()[:12]
        os.environ["EVIDENCE_AGENT_UI_PASSWORD"] = pwd
        append_env(root / "runs" / "system" / "private.env", "EVIDENCE_AGENT_UI_PASSWORD", pwd)
        append_env(root / "runs" / "system" / "private.env", "UI_PASSWORD", pwd)

    model_dir = find_model_dir(root)
    procs = {}
    if args.with_vllm:
        lora_modules = (
            [x.strip() for x in args.lora_modules.split(",") if x.strip()]
            if args.lora_modules
            else None
        )
        procs["vllm"] = start_vllm(root, model_dir, lora_modules)
        # wait for models endpoint
        wait_vllm(timeout=600)
    if args.vllm_only:
        st = {
            "services": {
                name: {"pid": p.pid, "running": True}
                for name, p in procs.items()
            },
            "model_dir": str(model_dir),
            "note": "vLLM only (S07 route probe)",
        }
        write_state(root, st)
        print(json.dumps(st, indent=2))
        print("SERVE_STARTED")
        return 0
    procs["api"] = start_api(root)
    procs["ui"] = start_ui(root)
    procs["worker"] = start_worker(root)
    wait_http("http://127.0.0.1:6008/healthz", timeout=60)
    wait_http("http://127.0.0.1:6006/", timeout=60)
    st = {
        "services": {
            name: {"pid": p.pid, "running": True}
            for name, p in procs.items()
        },
        "model_dir": str(model_dir),
        "note": "S09+ API/DB/worker stub + UI upload",
    }
    write_state(root, st)
    print(json.dumps(st, indent=2))
    print("SERVE_STARTED")
    return 0


def hashlib_token() -> str:
    import secrets

    return secrets.token_hex(16)


def append_env(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = existing.splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def wait_vllm(timeout: int = 600) -> None:
    import urllib.request

    url = "http://127.0.0.1:8001/v1/models"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    print("vllm_ready")
                    return
        except Exception:  # noqa: BLE001
            time.sleep(3)
    raise SystemExit("vLLM did not become ready")


def cmd_stop(args: argparse.Namespace) -> int:
    root = work_root()
    st = read_state(root)
    for name, meta in list(st.get("services", {}).items()):
        pid = meta.get("pid")
        if not pid:
            continue
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"stopped {name} pid={pid}")
            meta["running"] = False
        except ProcessLookupError:
            print(f"gone {name} pid={pid}")
            meta["running"] = False
        except Exception as exc:  # noqa: BLE001
            print(f"stop_error {name}: {exc}")
    write_state(root, st)
    # also pkill fallback for vllm
    subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], check=False)
    print("SERVE_STOPPED")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = work_root()
    st = read_state(root)
    print(json.dumps(st, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="EvidenceAgent serve")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--with-vllm", action="store_true", default=True)
    p_start.add_argument("--no-vllm", action="store_true")
    p_start.add_argument("--vllm-only", action="store_true")
    p_start.add_argument(
        "--lora-modules",
        default="",
        help="vLLM lora modules as name=path[,name=path]; empty uses the S07 probe adapter",
    )
    p_start.set_defaults(func=cmd_start)
    p_stop = sub.add_parser("stop")
    p_stop.set_defaults(func=cmd_stop)
    p_status = sub.add_parser("status")
    p_status.set_defaults(func=cmd_status)
    args = parser.parse_args()
    if getattr(args, "no_vllm", False):
        args.with_vllm = False
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
