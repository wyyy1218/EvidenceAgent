"""S40 release selection pure-function checks (no GPU)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from run_s40_select import select_release  # noqa: E402


def _row(q, g, false_a, valid, tin=1000, tout=100):
    return {
        "Q_mean": q,
        "G_gold_anchored_mean": g,
        "answered_false_rate": false_a,
        "action_valid_rate_mean": valid,
        "avg_input_tokens": tin,
        "avg_output_tokens": tout,
    }


def test_e1_research_only_falls_back_to_e0():
    systems = {
        "e0": _row(0.25, 0.40, 0.25, 0.99),
        "e1_final": _row(0.26, 0.28, 0.23, 0.99),  # G drop 0.12 > 0.02
        "e2_final": _row(0.245, 0.395, 0.25, 0.99),  # within Q/G gates vs E0
    }
    # Without research_only, e1 fails gate on G; e2 passes → choose e2
    d = select_release(systems)
    assert "e1_final" not in d["eligible"]
    assert d["chosen_system"] == "e2_final"

    d2 = select_release(systems, research_only={"e1_final", "e2_final"})
    assert d2["chosen_system"] == "e0"


def test_tie_prefers_sft_over_dpo():
    systems = {
        "e0": _row(0.20, 0.30, 0.20, 0.99, 1000, 100),
        "e1_final": _row(0.30, 0.40, 0.20, 0.99, 1000, 100),
        "e2_final": _row(0.30, 0.40, 0.20, 0.99, 1000, 100),
    }
    d = select_release(systems)
    assert d["chosen_system"] == "e1_final"
