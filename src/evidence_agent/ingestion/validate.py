"""Upload validation: suffix, MIME, magic, size, count, encoding gates."""
from __future__ import annotations

from pathlib import Path

from evidence_agent.ingestion.errors import IngestError

ALLOWED_SUFFIXES = frozenset({".pdf", ".md", ".txt"})
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_PDF_PAGES = 200
MAX_PROJECT_DOCUMENTS = 50
MIN_PDF_CHARS_PER_PAGE = 30

# Magic signatures
PDF_MAGIC = b"%PDF"
# UTF-8 BOM
UTF8_BOM = b"\xef\xbb\xbf"


def suffix_of(display_name: str) -> str:
    return Path(display_name).suffix.lower()


def detect_kind(data: bytes, display_name: str, content_type: str | None) -> str:
    """Return 'pdf' | 'md' | 'txt'. Raises IngestError on reject."""
    if not data:
        raise IngestError("empty_file", "empty file rejected")

    if len(data) > MAX_FILE_BYTES:
        raise IngestError(
            "file_too_large",
            f"file exceeds {MAX_FILE_BYTES} bytes",
            http_status=413,
        )

    suf = suffix_of(display_name)
    if suf not in ALLOWED_SUFFIXES:
        raise IngestError(
            "unsupported_suffix",
            f"suffix {suf!r} not in pdf/md/txt",
        )

    head = data[:16]
    is_pdf_magic = head.startswith(PDF_MAGIC)
    ct = (content_type or "").split(";")[0].strip().lower()

    if suf == ".pdf":
        if not is_pdf_magic:
            raise IngestError("disguised_or_invalid_pdf", "PDF suffix but missing %PDF signature")
        if ct and ct not in ("application/pdf", "application/octet-stream", ""):
            # soft: allow octet-stream; reject obvious mismatches like text/plain for pdf suffix with magic ok
            if ct.startswith("text/"):
                raise IngestError("mime_mismatch", f"PDF declared as {ct}")
        return "pdf"

    # text types must not be PDF masquerading
    if is_pdf_magic:
        raise IngestError("disguised_pdf", "text suffix but PDF signature")

    if suf in (".md", ".txt"):
        if ct and ct not in (
            "",
            "text/plain",
            "text/markdown",
            "application/octet-stream",
            "text/x-markdown",
        ):
            if ct == "application/pdf":
                raise IngestError("mime_mismatch", f"text file declared as {ct}")
        return "md" if suf == ".md" else "txt"

    raise IngestError("unsupported_type", "unsupported file type")


def ensure_utf8_text(data: bytes) -> tuple[str, bool]:
    """Decode TXT/MD as UTF-8 or UTF-8 BOM only. Returns (text, bom_stripped)."""
    bom = data.startswith(UTF8_BOM)
    payload = data[3:] if bom else data
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(
            "invalid_encoding",
            "TXT/MD must be UTF-8 or UTF-8 BOM; encoding guess disabled",
        ) from exc
    return text, bom


def check_project_document_limit(count: int) -> None:
    if count >= MAX_PROJECT_DOCUMENTS:
        raise IngestError(
            "project_document_limit",
            f"project already has {count} documents (max {MAX_PROJECT_DOCUMENTS})",
            http_status=400,
        )
