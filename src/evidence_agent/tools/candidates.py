"""Per-run candidate registry — read_evidence only accepts registered IDs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CandidateRecord:
    candidate_id: str
    kind: str  # local_chunk | web_url
    project_id: str
    run_id: str
    source_version_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    title: str | None = None
    snippet: str | None = None  # search summary — NOT evidence
    authorized: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


class CandidateRegistry:
    def __init__(self) -> None:
        self._by_run: dict[str, dict[str, CandidateRecord]] = {}

    def register(self, record: CandidateRecord) -> None:
        bucket = self._by_run.setdefault(record.run_id, {})
        bucket[record.candidate_id] = record

    def register_many(self, records: list[CandidateRecord]) -> None:
        for r in records:
            self.register(r)

    def get(self, run_id: str, candidate_id: str) -> CandidateRecord | None:
        return self._by_run.get(run_id, {}).get(candidate_id)

    def list_for_run(self, run_id: str) -> list[CandidateRecord]:
        return list(self._by_run.get(run_id, {}).values())

    def clear_run(self, run_id: str) -> None:
        self._by_run.pop(run_id, None)


# Process-local default registry (worker / tests)
GLOBAL_CANDIDATES = CandidateRegistry()
