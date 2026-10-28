"""Persist raw + normalized artifacts under data/raw and data/normalized."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_raw(
    root: Path, version_id: str, data: bytes, *, suffix: str
) -> tuple[Path, str]:
    dest_dir = root / "data" / "raw" / version_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_suf = suffix if suffix.startswith(".") else f".{suffix}"
    if safe_suf.lower() not in {".pdf", ".md", ".txt"}:
        safe_suf = ".bin"
    path = dest_dir / f"content{safe_suf}"
    path.write_bytes(data)
    rel = str(path.relative_to(root)).replace("\\", "/")
    return path, rel


def save_normalized(
    root: Path,
    version_id: str,
    *,
    raw_text: str,
    clean_text: str,
    mapping: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[str, str, str]:
    dest = root / "data" / "normalized" / version_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "content_raw.txt").write_text(raw_text, encoding="utf-8")
    (dest / "content_clean.txt").write_text(clean_text, encoding="utf-8")
    (dest / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    base = f"data/normalized/{version_id}"
    return f"{base}/content_clean.txt", f"{base}/mapping.json", base
