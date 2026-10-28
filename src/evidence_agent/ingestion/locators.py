"""Original-text location mapping (Unicode code points; PDF page+char offset)."""
from __future__ import annotations

from typing import Any


def build_text_mapping(parsed: dict[str, Any]) -> dict[str, Any]:
    """MD/TXT: line map + code-point spans over clean_text."""
    clean: str = parsed["clean_text"]
    lines = clean.split("\n")
    line_spans: list[dict[str, Any]] = []
    cursor = 0
    for i, line in enumerate(lines, start=1):
        start = cursor
        end = start + len(line)  # code-point length (Python str)
        line_spans.append(
            {
                "line": i,
                "start": start,
                "end": end,
                "title": _heading_title(line),
            }
        )
        cursor = end + 1  # account for '\n' except after last — match split semantics
    # Fix: split("\n") on "a\nb" gives ends that skip newlines correctly if we add 1 between lines
    # Recalculate precisely:
    line_spans = []
    pos = 0
    for i, line in enumerate(lines, start=1):
        start = pos
        end = start + len(line)
        line_spans.append(
            {
                "line": i,
                "start": start,
                "end": end,  # [start, end) over clean_text without including newline
                "title": _heading_title(line),
            }
        )
        pos = end + 1 if i < len(lines) else end

    return {
        "coordinate_system": "unicode_code_point_half_open",
        "bom_stripped": bool(parsed.get("bom_stripped")),
        "newline_normalized_to": "\\n",
        "whitespace_collapsed": False,
        "kind": parsed.get("kind"),
        "length": len(clean),
        "lines": line_spans,
        "headings": parsed.get("headings") or [],
        "note": "Offsets refer to clean_text. PDF visual coordinates are NOT claimed.",
    }


def build_pdf_mapping(parsed: dict[str, Any]) -> dict[str, Any]:
    pages_out: list[dict[str, Any]] = []
    for p in parsed.get("pages") or []:
        pages_out.append(
            {
                "page": p["page"],
                "length": len(p["text"]),
                "coordinate_system": "page_char_offset_half_open",
                "not_visual_coordinates": True,
            }
        )
    return {
        "coordinate_system": "pdf_page_plus_char_offset",
        "not_visual_coordinates": True,
        "page_count": parsed.get("page_count"),
        "pages": pages_out,
        "tables": parsed.get("tables") or [],
        "tables_possibly_incomplete": parsed.get("tables_possibly_incomplete", False),
        "page_issues": parsed.get("page_issues") or [],
        "avg_non_ws_per_page": parsed.get("avg_non_ws_per_page"),
        "needs_ocr": parsed.get("needs_ocr", False),
        "note": "Offsets are character offsets within each page text from pypdf, not PDF visual coords.",
    }


def _heading_title(line: str) -> str | None:
    s = line.lstrip()
    if s.startswith("#"):
        return s.lstrip("#").strip() or None
    return None


def slice_clean(clean_text: str, start: int, end: int) -> str:
    """Left-closed right-open Unicode code-point slice."""
    if start < 0 or end < start or end > len(clean_text):
        raise ValueError("invalid span")
    return clean_text[start:end]


def slice_pdf_page(page_text: str, start: int, end: int) -> str:
    return slice_clean(page_text, start, end)
