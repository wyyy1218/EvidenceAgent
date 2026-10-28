"""S25: HotpotQA subset builder isolation (fixture mode)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_hotpotqa_subset.py"


def test_build_fixture_subset(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--fixture-only"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    base = tmp_path / "data" / "tasks" / "hotpotqa" / "hotpotqa_distractor_s25_v1"
    assert (base / "train.jsonl").is_file()
    assert (base / "dev.jsonl").is_file()
    assert (base / "test.jsonl").is_file()
    assert (base / "train.gold.jsonl").is_file()
    assert (base / "leakage_report.json").is_file()
    man = tmp_path / "data" / "manifests" / "mf_hotpotqa_s25_0001.json"
    assert man.is_file()
    manifest = json.loads(man.read_text(encoding="utf-8"))
    assert manifest["license_data"] == "CC-BY-SA-4.0"
    assert manifest["counts"]["train"] >= 1
    assert manifest["isolation_violations"] == []

    # Online packs must not contain gold fields
    for split in ("train", "dev", "test"):
        for line in (base / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            obj = json.loads(line)
            assert "answer" not in obj
            assert "gold_answer" not in obj
            assert "supporting_facts" not in obj
            assert "gold_claims" not in obj
            corp = tmp_path / "data" / "tasks" / "hotpotqa" / "hotpotqa_distractor_s25_v1" / obj["corpus_relpath"]
            assert corp.is_file()

    # Gold anchors ok
    for line in (base / "test.gold.jsonl").read_text(encoding="utf-8").splitlines():
        g = json.loads(line)
        assert g["all_anchors_ok"] is True
        assert g["gold_support_spans"]
