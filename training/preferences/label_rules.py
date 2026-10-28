#!/usr/bin/env python3
"""S36 preference labeling rules (pure functions, unit-testable)."""
from __future__ import annotations

from typing import Any


def normalized_cost(
    *,
    input_tokens: float,
    output_tokens: float,
    tool_calls: float,
    initial_tool_budget: float,
) -> float | None:
    if initial_tool_budget <= 0:
        return None
    return (
        float(input_tokens) / 48000.0
        + float(output_tokens) / 4096.0
        + float(tool_calls) / float(initial_tool_budget)
    )


def decide_preference(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    q_margin: float = 0.10,
    g_slack: float = 0.02,
    q_tie: float = 0.02,
    g_tie: float = 0.02,
    c_rel: float = 0.15,
    q_min: float = 0.5,
) -> dict[str, Any]:
    """Return chosen side ('a'|'b') or discard reason.

    Each side dict: {q, g, c, forged_confident_on_insufficient, action}.
    g may be None (incomparable).
    """
    qa, qb = float(a["q"]), float(b["q"])
    ga, gb = a.get("g"), b.get("g")
    ca, cb = a.get("c"), b.get("c")

    # Insufficient-evidence: forged confident answer cannot win on cost alone.
    forged_a = bool(a.get("forged_confident_on_insufficient"))
    forged_b = bool(b.get("forged_confident_on_insufficient"))

    if ga is None or gb is None:
        return {"status": "discard", "reason": "g_incomparable", "chosen": None}

    ga_f, gb_f = float(ga), float(gb)

    # Both sides wrong / too weak → discard (protocol §4).
    if max(qa, qb) < q_min:
        return {"status": "discard", "reason": "both_wrong", "chosen": None}

    # Quality rule
    if qa >= qb + q_margin and ga_f + g_slack >= gb_f:
        if forged_a and not forged_b:
            return {"status": "discard", "reason": "forged_insufficient", "chosen": None}
        return {"status": "keep", "reason": "quality", "chosen": "a"}
    if qb >= qa + q_margin and gb_f + g_slack >= ga_f:
        if forged_b and not forged_a:
            return {"status": "discard", "reason": "forged_insufficient", "chosen": None}
        return {"status": "keep", "reason": "quality", "chosen": "b"}

    # Cost rule
    if abs(qa - qb) <= q_tie and abs(ga_f - gb_f) <= g_tie:
        if ca is None or cb is None:
            return {"status": "discard", "reason": "cost_undefined", "chosen": None}
        ca_f, cb_f = float(ca), float(cb)
        higher = max(ca_f, cb_f)
        if higher <= 0:
            return {"status": "discard", "reason": "higher_cost_zero", "chosen": None}
        if ca_f <= cb_f * (1.0 - c_rel):
            if forged_a and not forged_b:
                return {"status": "discard", "reason": "forged_wins_on_cost", "chosen": None}
            return {"status": "keep", "reason": "cost", "chosen": "a"}
        if cb_f <= ca_f * (1.0 - c_rel):
            if forged_b and not forged_a:
                return {"status": "discard", "reason": "forged_wins_on_cost", "chosen": None}
            return {"status": "keep", "reason": "cost", "chosen": "b"}
        return {"status": "discard", "reason": "cost_gap_insufficient", "chosen": None}

    return {"status": "discard", "reason": "no_clear_winner", "chosen": None}


def review_agreement(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    if first.get("status") != "keep" or second.get("status") != "keep":
        return {"status": "discard", "reason": "review_not_keep", "chosen": None}
    if first.get("chosen") != second.get("chosen"):
        return {"status": "discard", "reason": "review_flip", "chosen": None}
    return {
        "status": "keep",
        "reason": first.get("reason"),
        "chosen": first.get("chosen"),
        "review": "seed43_agree",
    }
