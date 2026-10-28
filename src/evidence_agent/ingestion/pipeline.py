"""Ingest pipeline: validate → store → parse → map → version/dedup."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from evidence_agent.ingestion import PARSER_VERSION
from evidence_agent.ingestion.errors import IngestError
from evidence_agent.ingestion.locators import build_pdf_mapping, build_text_mapping
from evidence_agent.ingestion.parse_pdf import parse_pdf_bytes
from evidence_agent.ingestion.parse_text import parse_text_bytes
from evidence_agent.ingestion.store import save_normalized, save_raw, sha256_hex
from evidence_agent.ingestion.validate import (
    check_project_document_limit,
    detect_kind,
    suffix_of,
)
from evidence_agent.storage import repositories as repo


def ingest_upload(
    conn: sqlite3.Connection,
    *,
    root: Path,
    project_id: str,
    display_name: str,
    data: bytes,
    content_type: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Create or update a document version. Returns ids.

    If document_id is provided, creates a new source_version on that document (S11 update).
    """
    kind = detect_kind(data, display_name, content_type)
    content_hash = sha256_hex(data)
    count = repo.count_documents(conn, project_id)
    if document_id is None:
        check_project_document_limit(count)
    else:
        doc = repo.get_document(conn, document_id)
        if not doc:
            raise IngestError("document_not_found", "document not found", http_status=404)
        if doc["project_id"] != project_id:
            raise IngestError("cross_project", "document not in project", http_status=403)

    conn.execute("BEGIN")
    try:
        if document_id is None:
            did = repo.create_document(conn, project_id, display_name, status="validating")
        else:
            did = document_id
            repo.update_document_status(conn, did, "validating")
            # keep display_name as original unless empty — S11 rename-upload uses new doc

        vid = repo.create_source_version(
            conn,
            did,
            content_hash,
            PARSER_VERSION,
            byte_size=len(data),
            mime_type=content_type,
            parse_status="validating",
        )
        jid = repo.create_ingest_job(conn, did, vid, status="validating")

        # Content dedup within project: reuse normalized artifacts from prior version
        prior = repo.find_version_by_hash(conn, content_hash, project_id=project_id)
        if prior and prior["id"] != vid and prior.get("normalized_path"):
            _, rel = save_raw(root, vid, data, suffix=suffix_of(display_name))
            repo.update_source_version_parse(
                conn,
                vid,
                parse_status="deduped",
                file_path=rel,
                page_count=prior.get("page_count"),
                normalized_path=prior.get("normalized_path"),
                mapping_path=prior.get("mapping_path"),
                dedup_of_version_id=prior["id"],
            )
            repo.update_document_status(conn, did, "parsed")
            repo.update_ingest_job(conn, jid, "completed")
            conn.execute("COMMIT")
            return {
                "document_id": did,
                "version_id": vid,
                "ingest_job_id": jid,
                "deduped": True,
                "dedup_of_version_id": prior["id"],
                "content_hash": content_hash,
            }

        _, rel = save_raw(root, vid, data, suffix=suffix_of(display_name))
        repo.update_document_status(conn, did, "parsing")
        repo.update_ingest_job(conn, jid, "parsing")
        repo.update_source_version_parse(conn, vid, parse_status="parsing", file_path=rel)

        if kind in ("md", "txt"):
            parsed = parse_text_bytes(data, kind=kind)
            mapping = build_text_mapping(parsed)
        else:
            parsed = parse_pdf_bytes(data)
            if parsed.get("needs_ocr"):
                repo.update_source_version_parse(
                    conn,
                    vid,
                    parse_status="needs_ocr",
                    file_path=rel,
                    page_count=parsed.get("page_count"),
                )
                repo.update_document_status(conn, did, "needs_ocr")
                repo.update_ingest_job(
                    conn,
                    jid,
                    "failed",
                    error_code="needs_ocr",
                    error_message="average non-whitespace chars/page below threshold; OCR not in scope",
                )
                conn.execute("COMMIT")
                raise IngestError(
                    "needs_ocr",
                    "PDF appears scanned / insufficient extractable text; OCR not supported",
                    http_status=422,
                )
            mapping = build_pdf_mapping(parsed)

        meta = {
            "document_id": did,
            "version_id": vid,
            "display_name": display_name,
            "content_hash": content_hash,
            "parser_version": PARSER_VERSION,
            "kind": kind,
            "page_count": parsed.get("page_count"),
            "bom_stripped": parsed.get("bom_stripped"),
        }
        norm_clean, map_path, _base = save_normalized(
            root,
            vid,
            raw_text=parsed["raw_text"],
            clean_text=parsed["clean_text"],
            mapping=mapping,
            metadata=meta,
        )
        repo.update_source_version_parse(
            conn,
            vid,
            parse_status="parsed",
            file_path=rel,
            page_count=parsed.get("page_count"),
            normalized_path=norm_clean,
            mapping_path=map_path,
        )
        repo.update_document_status(conn, did, "parsed")
        repo.update_ingest_job(conn, jid, "completed")
        conn.execute("COMMIT")
        return {
            "document_id": did,
            "version_id": vid,
            "ingest_job_id": jid,
            "deduped": False,
            "content_hash": content_hash,
            "parse_status": "parsed",
        }
    except IngestError:
        try:
            conn.execute("COMMIT")
        except Exception:  # noqa: BLE001
            try:
                conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
        raise
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:  # noqa: BLE001
            pass
        # Best-effort mark failure if transaction still open on new connection — skip
        raise IngestError("parse_failed", f"parse failed: {exc}") from exc


def update_document_file(
    conn: sqlite3.Connection,
    *,
    root: Path,
    project_id: str,
    document_id: str,
    display_name: str,
    data: bytes,
    content_type: str | None = None,
) -> dict[str, Any]:
    """S11: new source_version_id on same document_id."""
    return ingest_upload(
        conn,
        root=root,
        project_id=project_id,
        display_name=display_name,
        data=data,
        content_type=content_type,
        document_id=document_id,
    )
