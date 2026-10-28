"""Final run result semantics (项目说明 §12)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RESULT_STATUSES = frozenset(
    {
        "answered",
        "partial",
        "insufficient_evidence",
        "conflicting_evidence",
        "cancelled",
        "timeout",
        "failed",
    }
)


@dataclass
class RunResult:
    status: str
    answer: str | None = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    route: str = "base"

    def to_dict(self) -> dict[str, Any]:
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"invalid_status:{self.status}")
        return {
            "status": self.status,
            "answer": self.answer,
            "claims": self.claims,
            "unresolved": self.unresolved,
            "evidence_ids": self.evidence_ids,
            "verification": self.verification,
            "usage": self.usage,
            "note": self.note,
            "route": self.route,
            # Semantic reminders for training/UI
            "semantics": {
                "not_found_is_not_does_not_exist": True,
                "insufficient_is_not_negative_answer": True,
            },
        }


def decide_status(
    *,
    claims: list[dict[str, Any]],
    unresolved: list[str],
    verification: list[dict[str, Any]],
    cancelled: bool = False,
    timed_out: bool = False,
    failed: bool = False,
) -> str:
    if cancelled:
        return "cancelled"
    if failed:
        return "failed"
    if timed_out:
        return "timeout"
    if any(v.get("label") == "conflicting" for v in verification):
        return "conflicting_evidence"
    supported = [c for c in claims if c.get("status") in {"supported", "answered", None}]
    # After verifier, prefer verification labels
    supported_ids = {
        v.get("claim_id") for v in verification if v.get("label") == "supported"
    }
    if supported_ids:
        supported = [c for c in claims if c.get("claim_id") in supported_ids or c.get("id") in supported_ids]
    if not claims and unresolved:
        return "insufficient_evidence"
    if not claims:
        return "insufficient_evidence"
    if unresolved and supported:
        return "partial"
    if unresolved and not supported:
        return "insufficient_evidence"
    if supported:
        return "answered"
    uncertain = [v for v in verification if v.get("label") in {"uncertain", "unsupported"}]
    if uncertain and not supported_ids:
        return "insufficient_evidence"
    return "partial"
