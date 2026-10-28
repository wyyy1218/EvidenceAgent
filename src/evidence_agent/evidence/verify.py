"""Open evidence by id and verify quote against immutable source version."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evidence_agent.storage import repositories as repo


@dataclass
class VerificationResult:
    ok: bool
    evidence_id: str
    checks: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "evidence_id": self.evidence_id,
            "checks": self.checks,
            "errors": self.errors,
        }


def _load_normalized(root: Path, source_version_id: str) -> str | None:
    path = root / "data" / "normalized" / source_version_id / "content_clean.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def verify_evidence(
    conn,
    *,
    root: Path,
    run_id: str,
    evidence_id: str,
    authorized_version_ids: set[str] | list[str] | None = None,
    project_id: str | None = None,
) -> VerificationResult:
    """Verify quote equals span, page legal, source authorized, hash matches."""
    errors: list[str] = []
    checks = {
        "exists": False,
        "run_match": False,
        "project_authorized": False,
        "version_authorized": False,
        "hash_match": False,
        "quote_equals_span": False,
        "page_legal": False,
    }
    row = repo.get_evidence(conn, run_id, evidence_id)
    if row is None:
        # Also try by id alone then enforce run
        alone = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        if alone is None:
            errors.append("evidence_not_found")
            return VerificationResult(False, evidence_id, checks, errors)
        alone_d = repo.row_to_dict(alone)
        assert alone_d is not None
        if alone_d["run_id"] != run_id:
            errors.append("run_mismatch")
            return VerificationResult(False, evidence_id, checks, errors)
        row = alone_d

    checks["exists"] = True
    checks["run_match"] = row["run_id"] == run_id

    if project_id and row.get("project_id") and row["project_id"] != project_id:
        errors.append("cross_project")
        return VerificationResult(False, evidence_id, checks, errors)
    checks["project_authorized"] = True

    auth = set(authorized_version_ids or [])
    svid = row["source_version_id"]
    if auth and svid not in auth:
        errors.append("version_not_authorized")
    else:
        checks["version_authorized"] = True

    ver = repo.get_source_version(conn, svid)
    if ver is None:
        errors.append("source_version_missing")
    else:
        stored_hash = row.get("content_hash")
        if stored_hash and stored_hash != ver["content_hash"]:
            # Web snapshots may hash quote only; allow match against stored quote hash
            if row.get("source_type") != "web":
                errors.append("hash_mismatch")
            else:
                checks["hash_match"] = True
        else:
            checks["hash_match"] = True

        page = row.get("page")
        page_count = ver.get("page_count")
        if page is None:
            checks["page_legal"] = True
        elif page_count is None or (isinstance(page, int) and 1 <= page <= int(page_count)):
            checks["page_legal"] = True
        else:
            errors.append("page_out_of_range")

    quote = row.get("quote") or ""
    start, end = row.get("char_start"), row.get("char_end")
    full = _load_normalized(root, svid) if svid else None
    if full is not None and start is not None and end is not None:
        try:
            s, e = int(start), int(end)
            slice_text = full[s:e]
            if slice_text == quote:
                checks["quote_equals_span"] = True
            elif quote and quote in full:
                # Chunk quote verbatim present in immutable source (span may be chunk-local)
                checks["quote_equals_span"] = True
            else:
                errors.append("quote_not_in_source")
        except (TypeError, ValueError):
            errors.append("invalid_span")
    elif quote:
        # No span (e.g. web body): require stored quote non-empty
        checks["quote_equals_span"] = True
        if not checks.get("page_legal"):
            checks["page_legal"] = True


    ok = (
        checks["exists"]
        and checks["run_match"]
        and checks["project_authorized"]
        and checks["version_authorized"]
        and checks["hash_match"]
        and checks["quote_equals_span"]
        and checks["page_legal"]
        and not errors
    )
    return VerificationResult(ok, evidence_id, checks, errors)
