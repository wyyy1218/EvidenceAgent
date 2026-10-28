"""Scope-aware conflict expression — different conditions are not contradictions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCOPE_KEYS = ("entity", "version", "time", "region", "negation", "condition")


@dataclass
class ConflictAssessment:
    status: str  # compatible | scoped_difference | conflicting | unresolved
    reason: str
    scopes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "scopes": self.scopes,
        }


def _norm_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    if not scope:
        return {}
    out: dict[str, Any] = {}
    for k in SCOPE_KEYS:
        if k in scope and scope[k] not in (None, ""):
            out[k] = scope[k]
    # Also accept free-form extras that matter for equality
    for k, v in scope.items():
        if k not in out and v not in (None, ""):
            out[k] = v
    return out


def scopes_comparable(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when both scopes share enough keys that a factual conflict is meaningful."""
    na, nb = _norm_scope(a), _norm_scope(b)
    if not na or not nb:
        return False
    shared = set(na) & set(nb)
    if not shared:
        return False
    # If any shared key differs, they are different conditions → not same-condition conflict
    for k in shared:
        if na[k] != nb[k]:
            return False
    return True


def assess_scopes(
    claim_a: dict[str, Any],
    claim_b: dict[str, Any],
    *,
    texts_differ: bool | None = None,
) -> ConflictAssessment:
    """
    Two differing texts are not automatically contradictory.
    - Different version/time/region/condition → scoped_difference (report both ranges)
    - Same condition and incompatible claims → conflicting
    - Cannot tell → unresolved
    """
    sa = _norm_scope(claim_a.get("scope") if isinstance(claim_a.get("scope"), dict) else None)
    sb = _norm_scope(claim_b.get("scope") if isinstance(claim_b.get("scope"), dict) else None)
    # Allow scope_json string already parsed by caller
    if not sa and isinstance(claim_a.get("scope_json"), dict):
        sa = _norm_scope(claim_a["scope_json"])
    if not sb and isinstance(claim_b.get("scope_json"), dict):
        sb = _norm_scope(claim_b["scope_json"])

    text_a = (claim_a.get("text") or "").strip()
    text_b = (claim_b.get("text") or "").strip()
    differ = texts_differ if texts_differ is not None else (text_a != text_b and bool(text_a) and bool(text_b))

    if not differ:
        return ConflictAssessment(
            status="compatible",
            reason="texts_agree_or_empty",
            scopes=[sa, sb],
        )

    if not sa or not sb:
        return ConflictAssessment(
            status="unresolved",
            reason="insufficient_scope_to_judge_conflict",
            scopes=[sa, sb],
        )

    shared = set(sa) & set(sb)
    differing_keys = [k for k in shared if sa[k] != sb[k]]
    if differing_keys:
        return ConflictAssessment(
            status="scoped_difference",
            reason=f"different_conditions:{','.join(sorted(differing_keys))}",
            scopes=[sa, sb],
        )

    # Same condition keys match — check if all condition-bearing keys align
    condition_keys = ("version", "time", "region", "condition", "negation", "entity")
    a_cond = {k: sa[k] for k in condition_keys if k in sa}
    b_cond = {k: sb[k] for k in condition_keys if k in sb}
    if a_cond and b_cond and a_cond == b_cond:
        return ConflictAssessment(
            status="conflicting",
            reason="same_condition_irreconcilable",
            scopes=[sa, sb],
        )

    if a_cond != b_cond and (a_cond or b_cond):
        # Partially overlapping or one-sided conditions
        only_a = set(a_cond) - set(b_cond)
        only_b = set(b_cond) - set(a_cond)
        if only_a or only_b:
            return ConflictAssessment(
                status="scoped_difference",
                reason="non_overlapping_scope_keys",
                scopes=[sa, sb],
            )

    return ConflictAssessment(
        status="unresolved",
        reason="cannot_determine_conflict",
        scopes=[sa, sb],
    )


def assess_claim_pair_list(claims: list[dict[str, Any]]) -> list[ConflictAssessment]:
    """Pairwise assess; does not auto-resolve or pick a winner."""
    out: list[ConflictAssessment] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            out.append(assess_scopes(claims[i], claims[j]))
    return out
