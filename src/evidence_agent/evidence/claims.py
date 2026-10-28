"""Claim records and claim↔evidence many-to-many links."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from evidence_agent.storage import repositories as repo
from evidence_agent.storage.ids import new_id


@dataclass
class ClaimRecord:
    claim_id: str
    run_id: str
    text: str
    requirement_id: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    verification_status: str = "unverified"
    status: str = "draft"
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "run_id": self.run_id,
            "text": self.text,
            "requirement_id": self.requirement_id,
            "scope": self.scope,
            "verification_status": self.verification_status,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
        }


def register_claim(
    conn,
    *,
    run_id: str,
    text: str,
    requirement_id: str | None = None,
    scope: dict[str, Any] | None = None,
    verification_status: str = "unverified",
    status: str = "draft",
    evidence_ids: list[str] | None = None,
) -> ClaimRecord:
    cid = new_id("cl")
    eids = list(evidence_ids or [])
    scope_obj = dict(scope or {})
    conn.execute(
        "INSERT INTO claims("
        "id, run_id, requirement_id, text, scope, verification_status, "
        "scope_json, status, evidence_ids_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            run_id,
            requirement_id,
            text,
            json.dumps(scope_obj, ensure_ascii=False),
            verification_status,
            json.dumps(scope_obj, ensure_ascii=False),
            status,
            json.dumps(eids, ensure_ascii=False),
        ),
    )
    for eid in eids:
        link_claim_evidence(conn, claim_id=cid, evidence_id=eid)
    return ClaimRecord(
        claim_id=cid,
        run_id=run_id,
        text=text,
        requirement_id=requirement_id,
        scope=scope_obj,
        verification_status=verification_status,
        status=status,
        evidence_ids=eids,
    )


def link_claim_evidence(conn, *, claim_id: str, evidence_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO claim_evidence(claim_id, evidence_id) VALUES (?, ?)",
        (claim_id, evidence_id),
    )


def get_claim_evidence_ids(conn, claim_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT evidence_id FROM claim_evidence WHERE claim_id = ?", (claim_id,)
    ).fetchall()
    return [r["evidence_id"] for r in rows]


def list_run_claims(conn, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM claims WHERE run_id = ? ORDER BY id ASC", (run_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = repo.row_to_dict(r)
        assert d is not None
        d["evidence_ids"] = get_claim_evidence_ids(conn, d["id"])
        out.append(d)
    return out
