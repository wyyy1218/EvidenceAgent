"""S26/S27: Chinese sources freeze + task scale/isolation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from freeze_chinese_sources import freeze  # noqa: E402
from build_chinese_tasks import build_tasks  # noqa: E402
from evidence_agent.data.chinese_catalog import DATASET_ID, SPLIT_TARGETS  # noqa: E402


def test_s26_freeze_isolation(tmp_path: Path):
    man = freeze(tmp_path)
    assert man["isolation_ok"]
    assert man["doc_count"] >= 20
    for split in ("train", "dev", "test"):
        lib = tmp_path / "data" / "snapshots" / f"chinese_replay_{split}_s26_v1" / "replay_corpus.json"
        assert lib.is_file()
        boundary = json.loads(
            (tmp_path / "data" / "snapshots" / f"chinese_replay_{split}_s26_v1" / "source_boundary.json").read_text(
                encoding="utf-8"
            )
        )
        assert boundary["forbidden_cross_split"] is True


def test_s27_scale_replay_no_gold_in_online(tmp_path: Path):
    freeze(tmp_path)
    man = build_tasks(tmp_path)
    assert man["scale_complete"]
    assert man["replay_quota_met"]
    assert man["isolation_ok"]
    assert man["counts"] == SPLIT_TARGETS
    assert man["replay_counts"]["train"] == 120
    assert man["replay_counts"]["dev"] == 30
    assert man["replay_counts"]["test"] == 50

    base = tmp_path / "data" / "tasks" / "chinese" / DATASET_ID
    for split in ("train", "dev", "test"):
        for ln in (base / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            obj = json.loads(ln)
            assert "gold_claims" not in obj
            assert "gold_support_spans" not in obj
            assert "rubric" not in obj or split == "never"
        # gold file exists
        assert (base / f"{split}.gold.jsonl").is_file()
        # corpora present for first task
        first = json.loads((base / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert (base / first["corpus_relpath"]).is_file()
