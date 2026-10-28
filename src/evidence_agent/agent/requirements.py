"""Requirement extraction — question + explicit user constraints only; never gold."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


FORBIDDEN_KEYS = frozenset(
    {
        "gold_answer",
        "gold_support",
        "gold_claims",
        "gold_support_spans",
        "expected_status",
        "rubric",
    }
)


@dataclass
class Requirement:
    requirement_id: str
    text: str
    source: str = "question"  # question | user_constraint

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "text": self.text,
            "source": self.source,
        }


def _assert_no_gold(payload: dict[str, Any] | None) -> None:
    if not payload:
        return
    for k in payload:
        if k in FORBIDDEN_KEYS or str(k).startswith("gold_"):
            raise ValueError(f"gold_leak_forbidden:{k}")


def extract_requirements(
    question: str,
    *,
    user_constraints: list[str] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> list[Requirement]:
    """
    Derive requirements only from the question and explicit user constraints.
    Must not read evaluation gold fields.
    """
    _assert_no_gold(extra_context)
    q = (question or "").strip()
    if not q:
        raise ValueError("empty_question")

    reqs: list[Requirement] = [
        Requirement(requirement_id="req_main", text=q, source="question")
    ]
    # Split explicit multi-part questions lightly
    parts = re.split(r"[?？；;]\s*", q)
    parts = [p.strip() for p in parts if p.strip() and p.strip() != q]
    for i, p in enumerate(parts[:5]):
        if len(p) < 4:
            continue
        reqs.append(
            Requirement(requirement_id=f"req_part_{i+1}", text=p, source="question")
        )

    for i, c in enumerate(user_constraints or []):
        c = (c or "").strip()
        if not c:
            continue
        reqs.append(
            Requirement(
                requirement_id=f"req_constraint_{i+1}",
                text=c,
                source="user_constraint",
            )
        )
    # Deduplicate by text
    seen: set[str] = set()
    out: list[Requirement] = []
    for r in reqs:
        if r.text in seen:
            continue
        seen.add(r.text)
        out.append(r)
    return out
