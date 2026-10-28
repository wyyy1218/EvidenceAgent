"""PDF parse — pypdf text + pdfplumber tables; no OCR."""
from __future__ import annotations

from typing import Any

from evidence_agent.ingestion.errors import IngestError
from evidence_agent.ingestion.validate import MAX_PDF_PAGES, MIN_PDF_CHARS_PER_PAGE


def _non_ws_len(s: str) -> int:
    return sum(1 for c in s if not c.isspace())


def parse_pdf_bytes(data: bytes) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestError("missing_dependency", "pypdf not installed") from exc

    import io

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise IngestError("pdf_unreadable", f"cannot open PDF: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            ok = reader.decrypt("")  # type: ignore[attr-defined]
            if ok == 0:
                raise IngestError("encrypted_pdf", "encrypted PDF cannot be extracted")
        except IngestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IngestError("encrypted_pdf", "encrypted PDF cannot be extracted") from exc

    n_pages = len(reader.pages)
    if n_pages > MAX_PDF_PAGES:
        raise IngestError(
            "pdf_too_many_pages",
            f"PDF has {n_pages} pages (max {MAX_PDF_PAGES})",
            http_status=400,
        )

    pages: list[dict[str, Any]] = []
    page_issues: list[dict[str, Any]] = []
    total_non_ws = 0
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            text = ""
            page_issues.append({"page": i + 1, "issue": f"extract_error:{type(exc).__name__}"})
        # Normalize newlines within page; offsets are page-local char offsets on clean page text
        clean_page = text.replace("\r\n", "\n").replace("\r", "\n")
        nw = _non_ws_len(clean_page)
        total_non_ws += nw
        if nw == 0:
            page_issues.append({"page": i + 1, "issue": "blank_page"})
        pages.append(
            {
                "page": i + 1,
                "text": clean_page,
                "char_count": len(clean_page),
                "non_ws": nw,
            }
        )

    avg = (total_non_ws / n_pages) if n_pages else 0.0
    needs_ocr = avg < MIN_PDF_CHARS_PER_PAGE

    tables: list[dict[str, Any]] = []
    tables_possibly_incomplete = False
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None  # type: ignore[assignment]

    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_tables = page.extract_tables() or []
                    for t_idx, table in enumerate(page_tables):
                        if not table:
                            continue
                        headers = [str(c) if c is not None else "" for c in (table[0] or [])]
                        rows = [
                            [str(c) if c is not None else "" for c in (row or [])]
                            for row in table[1:]
                        ]
                        tables.append(
                            {
                                "page": i + 1,
                                "table_index": t_idx,
                                "columns": headers,
                                "rows": rows,
                                "possibly_incomplete": False,
                            }
                        )
        except Exception:  # noqa: BLE001
            tables_possibly_incomplete = True

    # Join pages with form-feed separators for a linear clean_text (mapping uses page-local offsets)
    clean_parts = [p["text"] for p in pages]
    clean_text = "\f".join(clean_parts)

    return {
        "kind": "pdf",
        "raw_text": clean_text,  # PDF has no separate byte-decoded raw unicode source
        "clean_text": clean_text,
        "bom_stripped": False,
        "page_count": n_pages,
        "avg_non_ws_per_page": avg,
        "needs_ocr": needs_ocr,
        "pages": pages,
        "page_issues": page_issues,
        "tables": tables,
        "tables_possibly_incomplete": tables_possibly_incomplete,
        "headings": [],
    }
