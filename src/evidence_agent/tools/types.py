"""Unified tool result contract (S15)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"  # no results
    INACCESSIBLE = "inaccessible"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    UNSUPPORTED = "unsupported"
    BILLING_UNKNOWN = "billing_unknown"
    ERROR = "error"


# Failures must remain failures — never look like successful empty evidence.
FAILURE_STATUSES = frozenset(
    {
        ToolStatus.INACCESSIBLE,
        ToolStatus.TIMEOUT,
        ToolStatus.PERMISSION_DENIED,
        ToolStatus.UNSUPPORTED,
        ToolStatus.BILLING_UNKNOWN,
        ToolStatus.ERROR,
    }
)


@dataclass
class ToolResult:
    tool: str
    status: ToolStatus
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    billing_status: str | None = None  # charged | free | unknown | n/a
    usage: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == ToolStatus.OK

    @property
    def is_failure(self) -> bool:
        return self.status in FAILURE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status.value,
            "data": self.data,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "billing_status": self.billing_status,
            "usage": self.usage,
            "meta": self.meta,
            "is_failure": self.is_failure,
            # Explicit: never upgrade failure/empty search into evidence
            "evidence": None if self.is_failure or self.status == ToolStatus.EMPTY else self.data.get("evidence"),
        }


def fail(
    tool: str,
    status: ToolStatus,
    *,
    error_code: str,
    error_message: str,
    billing_status: str | None = "n/a",
    meta: dict[str, Any] | None = None,
) -> ToolResult:
    if status not in FAILURE_STATUSES and status != ToolStatus.EMPTY:
        status = ToolStatus.ERROR
    return ToolResult(
        tool=tool,
        status=status,
        error_code=error_code,
        error_message=error_message,
        billing_status=billing_status,
        meta=meta or {},
        data={},  # no fake evidence payload
    )
