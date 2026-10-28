"""Visible controller state (§10.1) and state_hash."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from evidence_agent.agent.requirements import FORBIDDEN_KEYS


@dataclass
class VisibleState:
    question: str
    requirements: list[dict[str, Any]] = field(default_factory=list)
    project_id: str = ""
    snapshot_set_id: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence_cards: list[dict[str, Any]] = field(default_factory=list)
    open_gaps: list[dict[str, Any]] = field(default_factory=list)  # model suggestion, not truth
    recent_actions: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    source_failures: list[dict[str, Any]] = field(default_factory=list)
    no_new_evidence_streak: int = 0
    truncated: bool = False

    def visible_dict(self) -> dict[str, Any]:
        """Only controller-visible fields — never gold or full raw history."""
        return {
            "question": self.question,
            "requirements": self.requirements,
            "project_id": self.project_id,
            "snapshot_set_id": self.snapshot_set_id,
            "candidates": self.candidates,
            "evidence_cards": self.evidence_cards,
            "open_gaps": self.open_gaps,
            "open_gaps_is_suggestion_not_truth": True,
            "recent_actions": self.recent_actions,
            "budget": self.budget,
            "source_failures": self.source_failures,
            "no_new_evidence_streak": self.no_new_evidence_streak,
            "truncated": self.truncated,
        }

    def state_hash(self) -> str:
        blob = json.dumps(self.visible_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def assert_no_gold(obj: Any, path: str = "root") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS or str(k).startswith("gold_"):
                raise ValueError(f"gold_leak_forbidden:{path}.{k}")
            assert_no_gold(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_gold(v, f"{path}[{i}]")
