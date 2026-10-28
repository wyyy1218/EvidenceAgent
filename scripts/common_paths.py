"""Shared WORK_ROOT / cache helpers for CLI scripts."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_WORK_ROOT = Path("/root/autodl-tmp/evidence-agent")


def work_root() -> Path:
    return Path(os.environ.get("WORK_ROOT", str(DEFAULT_WORK_ROOT)))


def ensure_cache_env(root: Path | None = None) -> Path:
    root = root or work_root()
    cache = root / "envs" / "cache"
    mapping = {
        "UV_CACHE_DIR": cache / "uv",
        "PIP_CACHE_DIR": cache / "pip",
        "HF_HOME": cache / "huggingface",
        "HUGGINGFACE_HUB_CACHE": cache / "huggingface" / "hub",
        "TORCH_HOME": cache / "torch",
        "XDG_CACHE_HOME": cache / "xdg",
    }
    for key, path in mapping.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault(key, str(path))
    os.environ.setdefault("WORK_ROOT", str(root))
    return root


def capacity_bytes(path: Path | None = None) -> int:
    """Total size of filesystem containing path (bytes)."""
    import os as _os

    path = path or (work_root().parent if work_root().exists() else Path("/root/autodl-tmp"))
    st = _os.statvfs(str(path))
    return int(st.f_frsize * st.f_blocks)


def capacity_gate(min_gib: float = 100.0) -> tuple[bool, float]:
    total = capacity_bytes()
    gib = total / (1024**3)
    return gib + 1e-9 >= min_gib, gib
