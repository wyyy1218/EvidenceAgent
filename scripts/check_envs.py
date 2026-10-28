#!/usr/bin/env python3
"""S06: verify the four Python 3.11 environments are isolated and importable."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env  # noqa: E402

CHECKS = {
    "app": """
import importlib.metadata as m
import deepagents, fastapi, streamlit, langgraph, faiss, sentence_transformers, torch
print("python", __import__("sys").version.split()[0])
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
for p in ["deepagents","fastapi","streamlit","langgraph","faiss-cpu","sentence-transformers","transformers","huggingface-hub"]:
    try:
        print(p, m.version(p))
    except Exception as exc:
        print(p, "MISSING", type(exc).__name__)
print("ENV_OK")
""",
    "infer": """
import importlib.metadata as m
import torch, vllm
print("python", __import__("sys").version.split()[0])
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("vllm", m.version("vllm"))
print("transformers", m.version("transformers"))
print("ENV_OK")
""",
    "train": """
import importlib.metadata as m
import torch, transformers, peft, trl, bitsandbytes
print("python", __import__("sys").version.split()[0])
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
for p in ["transformers","peft","trl","bitsandbytes","accelerate","datasets"]:
    try:
        print(p, m.version(p))
    except Exception as exc:
        print(p, "MISSING", type(exc).__name__)
print("ENV_OK")
""",
    "judge": """
import importlib.metadata as m
import torch, transformers
print("python", __import__("sys").version.split()[0])
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("transformers", m.version("transformers"))
try:
    import minicheck
    print("minicheck", getattr(minicheck, "__version__", "imported"))
except Exception as exc:
    print("minicheck", "IMPORT_FAIL", type(exc).__name__, str(exc)[:200])
print("ENV_OK")
""",
}


def main() -> int:
    root = ensure_cache_env()
    out_dir = root / "runs" / "probes" / "probe_s06_envs_a001"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    all_ok = True
    for name, code in CHECKS.items():
        py = root / "envs" / name / "bin" / "python"
        rec = {"python_path": str(py), "exists": py.is_file()}
        if not py.is_file():
            rec["ok"] = False
            rec["error"] = "python missing"
            all_ok = False
            results[name] = rec
            continue
        proc = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=600)
        out = (proc.stdout or "") + (proc.stderr or "")
        (out_dir / f"{name}.log").write_text(out, encoding="utf-8")
        rec["ok"] = proc.returncode == 0 and "ENV_OK" in out
        rec["returncode"] = proc.returncode
        rec["output"] = out[:4000]
        all_ok = all_ok and rec["ok"]
        results[name] = rec
        print(f"[{'PASS' if rec['ok'] else 'FAIL'}] {name}")

    summary = {
        "probe_id": "probe_s06_envs_a001",
        "when": datetime.now(timezone.utc).isoformat(),
        "work_root": str(root),
        "results": results,
        "all_ok": all_ok,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        "# probe_s06_envs_a001\n\n"
        + "\n".join(f"- {'PASS' if v['ok'] else 'FAIL'}: `{k}`" for k, v in results.items())
        + f"\n\nall_ok={all_ok}\n",
        encoding="utf-8",
    )
    print("ENVS_OK" if all_ok else "ENVS_FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
