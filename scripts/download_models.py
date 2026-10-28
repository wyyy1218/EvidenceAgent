#!/usr/bin/env python3
"""S06: download frozen models with full revision SHA + file hashes."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo/scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import capacity_gate, ensure_cache_env, work_root  # noqa: E402

MODELS = [
    {
        "role": "base",
        "repo_id": "Qwen/Qwen3-4B-Instruct-2507",
        "subdir": "base",
        "manifest_id": "mf_model_base_0001",
        "ignore_patterns": [],
    },
    {
        "role": "embedding",
        "repo_id": "BAAI/bge-m3",
        "subdir": "embedding",
        "manifest_id": "mf_model_embedding_0001",
        # dense-only: skip the duplicated ONNX export and README images
        "ignore_patterns": ["onnx/*", "imgs/*", "*.jpg", "*.png"],
    },
    {
        "role": "reranker",
        "repo_id": "BAAI/bge-reranker-v2-m3",
        "subdir": "reranker",
        "manifest_id": "mf_model_reranker_0001",
        "ignore_patterns": ["assets/*", "*.png"],
    },
    {
        # MiniCheck official flan-t5-large checker (not generic google/flan-t5-large)
        "role": "judge",
        "repo_id": "lytang/MiniCheck-Flan-T5-Large",
        "subdir": "judge",
        "manifest_id": "mf_model_judge_0001",
        "ignore_patterns": ["*.png"],
        "notes": "MiniCheck official wrapper model; see Liyan06/MiniCheck",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        # huggingface_hub keeps download metadata under .cache/ inside local_dir
        if rel.startswith(".cache/"):
            continue
        out[rel] = sha256_file(p)
    return out


def card_license(info: object) -> str | None:
    card = getattr(info, "cardData", None)
    if card is None:
        return None
    if isinstance(card, dict):
        return card.get("license")
    to_dict = getattr(card, "to_dict", None)
    if callable(to_dict):
        try:
            return (to_dict() or {}).get("license")
        except Exception:  # noqa: BLE001
            return None
    return getattr(card, "license", None)


def main() -> int:
    root = ensure_cache_env()
    ok, gib = capacity_gate(100.0)
    print(f"capacity_gib={gib:.2f} gate={'PASS' if ok else 'FAIL'}")
    if not ok:
        print("CAPACITY_GATE_FAIL: refuse large download", file=sys.stderr)
        return 2

    # huggingface.co is not reachable from the instance; use the documented mirror endpoint.
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    # The Xet CAS backend rejects the mirror; force plain HTTP LFS downloads.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    print(f"hf_endpoint={os.environ['HF_ENDPOINT']} xet_disabled=1")

    from huggingface_hub import HfApi, snapshot_download

    api = HfApi(endpoint=os.environ["HF_ENDPOINT"])
    manifests_dir = root / "data" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    index_path = root / "repo" / "artifacts" / "artifact_index.json"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index = {"schema_version": "1.0", "description": "large artifacts index", "entries": []}

    entries = []
    for spec in MODELS:
        info = api.model_info(spec["repo_id"])
        revision = info.sha
        dest = root / "models" / spec["subdir"] / revision
        print(f"download {spec['repo_id']} @ {revision} -> {dest}")
        snapshot_download(
            repo_id=spec["repo_id"],
            revision=revision,
            local_dir=str(dest),
            ignore_patterns=spec.get("ignore_patterns") or None,
        )
        hashes = file_hashes(dest)
        size = sum((dest / rel).stat().st_size for rel in hashes)
        license_id = card_license(info)

        manifest = {
            "manifest_id": spec["manifest_id"],
            "role": spec["role"],
            "repo_id": spec["repo_id"],
            "revision_sha": revision,
            "path": str(dest),
            "size_bytes": size,
            "file_sha256": hashes,
            "license": license_id,
            "tokenizer_present": any(
                (dest / n).exists()
                for n in ("tokenizer.json", "tokenizer.model", "tokenizer_config.json")
            ),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "notes": spec.get("notes"),
        }
        mpath = manifests_dir / f"{spec['manifest_id']}.json"
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        entries.append(
            {
                "id": spec["manifest_id"],
                "kind": "model",
                "role": spec["role"],
                "repo_id": spec["repo_id"],
                "revision": revision,
                "path": str(dest),
                "size_bytes": size,
                "manifest": str(mpath),
            }
        )
        print(f"OK {spec['role']} files={len(hashes)} size_gib={size/(1024**3):.2f}")

    # merge index entries by id
    by_id = {e.get("id"): e for e in index.get("entries", []) if e.get("id")}
    for e in entries:
        by_id[e["id"]] = e
    index["entries"] = list(by_id.values())
    index["updated"] = datetime.now(timezone.utc).isoformat()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("DOWNLOAD_MODELS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
