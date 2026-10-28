#!/usr/bin/env python3
"""S26: Freeze Chinese tech-doc sources, versions, and per-split replay libraries.

Usage:
  python scripts/freeze_chinese_sources.py --root <WORK_ROOT>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from evidence_agent.data.chinese_catalog import (  # noqa: E402
    CUTOFF_DATE,
    PROJECTS,
    SOURCES_MANIFEST_ID,
    projects_for_split,
)
from evidence_agent.data.chinese_corpus import build_all_docs  # noqa: E402


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def freeze(root: Path) -> dict[str, Any]:
    docs = build_all_docs()
    raw_root = root / "data" / "raw" / "chinese_docs"
    snap_root = root / "data" / "snapshots"
    norm_root = root / "data" / "normalized" / "chinese_docs"
    raw_root.mkdir(parents=True, exist_ok=True)
    norm_root.mkdir(parents=True, exist_ok=True)

    by_split: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    license_notices: list[str] = []
    file_records: list[dict[str, Any]] = []

    for d in docs:
        proj_dir = raw_root / d["project"] / d["version"]
        proj_dir.mkdir(parents=True, exist_ok=True)
        # Flatten path to safe filename
        safe = d["path"].replace("/", "__").replace("\\", "__")
        out_md = proj_dir / safe
        header = (
            f"<!-- freeze_cutoff={CUTOFF_DATE} repo={d['repo']} version={d['version']} "
            f"path={d['path']} license={d['license']} capture={d['capture_mode']} -->\n\n"
        )
        out_md.write_text(header + d["text"], encoding="utf-8")
        meta_path = proj_dir / (safe + ".meta.json")
        meta = {k: v for k, v in d.items() if k != "text"}
        _write_json(meta_path, meta)

        # Normalized copy (same body, for indexing later)
        n_dir = norm_root / d["project"] / d["version"]
        n_dir.mkdir(parents=True, exist_ok=True)
        (n_dir / safe).write_text(d["text"], encoding="utf-8")

        rec = {
            "doc_id": d["doc_id"],
            "project": d["project"],
            "split": d["split"],
            "repo": d["repo"],
            "version": d["version"],
            "path": d["path"],
            "license": d["license"],
            "text_sha256": d["text_sha256"],
            "raw_relpath": str(out_md.relative_to(root)).replace("\\", "/"),
            "source_url": d["source_url"],
            "capture_mode": d["capture_mode"],
            "redistribute": PROJECTS[d["project"]]["redistribute"],
        }
        file_records.append(rec)
        by_split[d["split"]].append(d)
        notice = (
            f"- {d['repo']}@{d['version']} `{d['path']}` license={d['license']} "
            f"sha256={d['text_sha256'][:16]}…"
        )
        if notice not in license_notices:
            license_notices.append(notice)

    # Per-split replay libraries (independent; no cross-split docs)
    replay_libs: dict[str, str] = {}
    for split in ("train", "dev", "test"):
        lib_id = f"chinese_replay_{split}_s26_v1"
        lib_dir = snap_root / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = lib_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        entries = []
        for d in by_split[split]:
            page_name = f"{d['doc_id']}.md"
            (pages_dir / page_name).write_text(d["text"], encoding="utf-8")
            # Synthetic frozen URL — replay is not live SERP
            url = f"https://frozen.local/{split}/{d['project']}/{d['version']}/{d['path']}"
            entries.append(
                {
                    "url": url,
                    "title": f"{d['title']} ({d['project']}@{d['version']})",
                    "snippet": d["text"][:200].replace("\n", " "),
                    "text": d["text"],
                    "tags": [d["project"], d["version"], split, "chinese_docs"],
                    "snapshot_id": d["doc_id"],
                    "license": d["license"],
                    "source_url": d["source_url"],
                }
            )
        corpus = {
            "library_id": lib_id,
            "split": split,
            "projects": projects_for_split(split),
            "note": "replay_is_not_live_serp; frozen before writing test questions",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "cutoff_date": CUTOFF_DATE,
            "entries": entries,
        }
        corpus_path = lib_dir / "replay_corpus.json"
        _write_json(corpus_path, corpus)
        # Boundary file: which projects are authorized
        _write_json(
            lib_dir / "source_boundary.json",
            {
                "split": split,
                "allowed_projects": projects_for_split(split),
                "forbidden_cross_split": True,
                "doc_ids": [d["doc_id"] for d in by_split[split]],
            },
        )
        replay_libs[split] = str(corpus_path.relative_to(root)).replace("\\", "/")

    # Cross-split leakage check on doc_ids / project sets
    train_p = set(projects_for_split("train"))
    dev_p = set(projects_for_split("dev"))
    test_p = set(projects_for_split("test"))
    cross = {
        "train_dev_overlap": sorted(train_p & dev_p),
        "train_test_overlap": sorted(train_p & test_p),
        "dev_test_overlap": sorted(dev_p & test_p),
    }
    isolation_ok = not any(cross.values())

    notices_path = raw_root / "LICENSE_NOTICES.md"
    notices_path.write_text(
        "# Chinese docs freeze — license notices\n\n"
        f"Cutoff: {CUTOFF_DATE}\n\n"
        "Local-use excerpts with provenance. Do not treat as redistributable full "
        "upstream trees inside the public Git tree. Keep per-project licenses.\n\n"
        + "\n".join(license_notices)
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "manifest_id": SOURCES_MANIFEST_ID,
        "step": "S26",
        "cutoff_date": CUTOFF_DATE,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "projects": {
            k: {
                "split": v["split"],
                "repo": v["repo"],
                "license": v["license"],
                "versions": v["versions"],
                "redistribute": v["redistribute"],
            }
            for k, v in PROJECTS.items()
        },
        "doc_count": len(docs),
        "docs_per_split": {s: len(by_split[s]) for s in by_split},
        "files": file_records,
        "replay_libraries": replay_libs,
        "cross_split_project_check": cross,
        "isolation_ok": isolation_ok,
        "live_fetch": "skipped_network_timeout_use_authored_excerpts",
        "notes": [
            "Test replay library frozen before writing test tasks (S27).",
            "Runtime must only authorize the task's registered snapshot set.",
            "capture_mode=authored_local_use_excerpt when Hub/GitHub raw fetch unavailable.",
        ],
    }
    man_path = root / "data" / "manifests" / f"{SOURCES_MANIFEST_ID}.json"
    _write_json(man_path, manifest)

    # Pointer for docs
    index = {
        "manifest": str(man_path.relative_to(root)).replace("\\", "/"),
        "raw": "data/raw/chinese_docs/",
        "snapshots": replay_libs,
        "isolation_ok": isolation_ok,
    }
    _write_json(raw_root / "freeze_index.json", index)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    man = freeze(root)
    print(json.dumps({"ok": man["isolation_ok"], "docs": man["doc_count"], "manifest": man["manifest_id"]}, ensure_ascii=False))
    return 0 if man["isolation_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
