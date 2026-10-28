"""Controller action validation (five actions, four fields)."""
from __future__ import annotations

from typing import Any

ALLOWED_ACTIONS = frozenset(
    {"local_search", "web_search", "read_evidence", "finish", "abstain"}
)
REASON_CODES = frozenset(
    {
        "evidence_sufficient",
        "missing_source",
        "conflicting_sources",
        "low_information_gain",
        "budget_exhausted",
        "tool_unavailable",
    }
)
REQUIRED_FIELDS = ("action", "query", "candidate_id", "reason_code")

_FINISH_REASON_ALIASES = {
    "finish": "evidence_sufficient",
    "done": "evidence_sufficient",
    "complete": "evidence_sufficient",
    "sufficient": "evidence_sufficient",
    "evidence_sufficient": "evidence_sufficient",
    "abstain": "missing_source",
    "insufficient": "missing_source",
    "missing": "missing_source",
    "missing_source": "missing_source",
    "conflict": "conflicting_sources",
    "conflicting_sources": "conflicting_sources",
    "budget": "budget_exhausted",
    "budget_exhausted": "budget_exhausted",
    "low_information_gain": "low_information_gain",
    "tool_unavailable": "tool_unavailable",
}


class ActionValidationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_action(obj: dict[str, Any]) -> dict[str, Any]:
    """Ensure four fields present; fill missing with null."""
    out = {
        "action": obj.get("action"),
        "query": obj.get("query", None),
        "candidate_id": obj.get("candidate_id", None),
        "reason_code": obj.get("reason_code", None),
    }
    return out


def coerce_policy_action(
    obj: Any,
    *,
    allow_web: bool = False,
    known_candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Product robustness for untrained base: strip free-text misplaced in null-only fields.

    Keeps validate_action strict. Only drops reason_code / query when they are clearly
    free-form text on actions that require null (not a valid reason_code enum value).
    Also fills omitted keys via normalize_action and remaps web_search→local_search when
    web is disabled but a query is present.
    """
    if not isinstance(obj, dict):
        return obj
    # Drop unknown keys before validate (base models sometimes omit required nulls
    # or add commentary fields). Keep only the four protocol fields.
    slim = {k: obj.get(k) for k in REQUIRED_FIELDS}
    act = normalize_action(slim)
    name = act.get("action")
    rc = act.get("reason_code")
    q = act.get("query")
    known = known_candidate_ids
    if name == "web_search" and not allow_web and isinstance(q, str) and q.strip():
        act["action"] = "local_search"
        name = "local_search"
        act["candidate_id"] = None
    if name in {"local_search", "web_search"}:
        # Search: models often put prose in reason_code.
        if rc is not None and rc not in REASON_CODES:
            act["reason_code"] = None
        act["candidate_id"] = None
    elif name == "read_evidence":
        if rc is not None and rc not in REASON_CODES:
            act["reason_code"] = None
        # read_evidence requires query=null; drop free-text queries so reads can proceed.
        if q is not None:
            act["query"] = None
        # Empty candidate list: remap a query-bearing read into local_search when possible.
        cid = act.get("candidate_id")
        if (not known) and (not cid) and isinstance(obj.get("query"), str) and str(obj.get("query")).strip():
            act = {
                "action": "local_search",
                "query": str(obj.get("query")).strip(),
                "candidate_id": None,
                "reason_code": None,
            }
    elif name in {"finish", "abstain"}:
        act["query"] = None
        act["candidate_id"] = None
        if rc not in REASON_CODES:
            key = str(rc or "").strip().lower().replace(" ", "_")
            mapped = _FINISH_REASON_ALIASES.get(key)
            if mapped is None:
                mapped = "evidence_sufficient" if name == "finish" else "missing_source"
            act["reason_code"] = mapped
    return act


def validate_action(
    obj: Any,
    *,
    allow_web: bool = False,
    known_candidate_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ActionValidationError("not_object", "action must be a JSON object")
    extra = set(obj) - set(REQUIRED_FIELDS)
    # Allow ignoring unknown keys by rejecting them
    if extra:
        raise ActionValidationError("extra_fields", f"forbidden fields: {sorted(extra)}")
    act = normalize_action(obj)
    name = act["action"]
    if name not in ALLOWED_ACTIONS:
        raise ActionValidationError("unknown_action", f"unknown action: {name}")

    q, cid, rc = act["query"], act["candidate_id"], act["reason_code"]

    if name in {"local_search", "web_search"}:
        if not isinstance(q, str) or not q.strip():
            raise ActionValidationError("missing_query", "query required")
        if len(q) > 256:
            raise ActionValidationError("query_too_long", "query max 256")
        if cid is not None:
            raise ActionValidationError("unexpected_candidate_id", "must be null")
        if rc is not None:
            raise ActionValidationError("unexpected_reason_code", "must be null")
        if name == "web_search" and not allow_web:
            raise ActionValidationError("web_disabled", "web_search not allowed")
        act["query"] = q.strip()
        act["candidate_id"] = None
        act["reason_code"] = None

    elif name == "read_evidence":
        if not isinstance(cid, str) or not cid.strip():
            raise ActionValidationError("missing_candidate_id", "candidate_id required")
        if len(cid) > 128:
            raise ActionValidationError("candidate_id_too_long", "max 128")
        if q is not None:
            raise ActionValidationError("unexpected_query", "must be null")
        if rc is not None:
            raise ActionValidationError("unexpected_reason_code", "must be null")
        if known_candidate_ids is not None and cid not in known_candidate_ids:
            raise ActionValidationError("unknown_candidate", "candidate not registered")
        act["query"] = None
        act["candidate_id"] = cid.strip()
        act["reason_code"] = None

    else:  # finish / abstain
        if q is not None or cid is not None:
            raise ActionValidationError("unexpected_fields", "query/candidate_id must be null")
        if rc not in REASON_CODES:
            raise ActionValidationError("invalid_reason_code", f"reason_code required enum")
        act["query"] = None
        act["candidate_id"] = None
        act["reason_code"] = rc

    return act


def normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())
