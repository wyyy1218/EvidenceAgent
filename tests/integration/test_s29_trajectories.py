"""S29: Trajectory collection excludes test; no gold in packed state."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
_SRC = _REPO / "src"
for p in (_SCRIPTS, _SRC, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from freeze_chinese_sources import freeze  # noqa: E402
from build_chinese_tasks import build_tasks  # noqa: E402
from collect_trajectories import collect  # noqa: E402
from evidence_agent.data.chinese_catalog import COLLECTION_ID  # noqa: E402


def test_collect_small(tmp_path: Path):
    freeze(tmp_path)
    build_tasks(tmp_path)
    summary = collect(tmp_path, limit=8, max_per_task=1)
    assert summary["test_excluded"]
    assert summary["gold_hidden_from_policy"]
    assert summary["accepted_trajectories"] + summary["rejected_trajectories"] == 8
    assert summary["unique_state_actions"] >= 1
    out = tmp_path / "runs" / "trajectories" / COLLECTION_ID
    # Inspect one raw traj for gold leak
    raws = list((out / "raw").glob("*.json"))
    assert raws
    traj = json.loads(raws[0].read_text(encoding="utf-8"))
    assert traj["split"] in {"train", "dev"}
    for sa in traj["state_actions"]:
        blob = json.dumps(sa["packed_state"], ensure_ascii=False)
        assert "gold_claims" not in blob
        assert "gold_support_spans" not in blob
