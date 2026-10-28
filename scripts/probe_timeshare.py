#!/usr/bin/env python3
"""S07: confirm GPU free after stop, then vLLM can restart."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env, work_root  # noqa: E402


def gpu_used_mib() -> int:
    out = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    )
    return int(out.strip().splitlines()[0])


def vllm_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/v1/models", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    root = ensure_cache_env()
    probe_id = "probe_s07_timeshare_a001"
    out_dir = root / "runs" / "probes" / probe_id
    out_dir.mkdir(parents=True, exist_ok=True)

    serve = root / "repo" / "scripts" / "serve.py"
    py = sys.executable
    # stop
    subprocess.run([py, str(serve), "stop"], check=False)
    time.sleep(5)
    # kill stray train python cuda if any — only our serve targets
    used_after_stop = gpu_used_mib()
    # start again
    subprocess.run([py, str(serve), "start", "--with-vllm"], check=True)
    # wait
    ok = False
    for _ in range(200):
        if vllm_up():
            ok = True
            break
        time.sleep(3)
    used_after_start = gpu_used_mib()
    report = {
        "probe_id": probe_id,
        "gpu_mib_after_stop": used_after_stop,
        "gpu_mib_after_start": used_after_start,
        "vllm_restart_ok": ok,
        "pass": ok and used_after_stop < 2000,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("TIMESHARE_OK" if report["pass"] else "TIMESHARE_FAIL")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
