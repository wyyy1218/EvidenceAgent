"""TXT/MD parse — UTF-8 only; preserve structure for locators."""
from __future__ import annotations

import re
from typing import Any

from evidence_agent.ingestion.validate import ensure_utf8_text

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def parse_text_bytes(data: bytes, *, kind: str) -> dict[str, Any]:
    raw_text, bom_stripped = ensure_utf8_text(data)
    # Cleaning: strip BOM already; normalize newlines to \n; do not collapse whitespace.
    clean = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = clean.split("\n")
    headings: list[dict[str, Any]] = []
    for i, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line)
        if m:
            headings.append(
                {
                    "line": i,
                    "level": len(m.group(1)),
                    "title": m.group(2).strip(),
                }
            )
    return {
        "kind": kind,
        "raw_text": raw_text,
        "clean_text": clean,
        "bom_stripped": bom_stripped,
        "line_count": len(lines),
        "headings": headings,
        "pages": None,
        "tables": [],
    }
