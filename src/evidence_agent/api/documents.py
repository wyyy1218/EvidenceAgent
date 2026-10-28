"""Document upload and status endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from evidence_agent.api.deps import get_conn, get_root, require_bearer
from evidence_agent.api.schemas import DocumentStatusResponse, DocumentUploadResponse
from evidence_agent.storage import repositories as repo

router = APIRouter(tags=["documents"])


@router.post(
    "/v1/projects/{project_id}/documents",
    response_model=DocumentUploadResponse,
    dependencies=[Depends(require_bearer)],
)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
) -> DocumentUploadResponse:
    conn = get_conn()
    root = get_root()
    try:
        proj = repo.get_project(conn, project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="project not found")

        raw = await file.read()
        display_name = file.filename or "upload.bin"

        from evidence_agent.ingestion.errors import IngestError
        from evidence_agent.ingestion.pipeline import ingest_upload

        try:
            result = ingest_upload(
                conn,
                root=root,
                project_id=project_id,
                display_name=display_name,
                data=raw,
                content_type=file.content_type,
            )
        except IngestError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return DocumentUploadResponse(
            document_id=result["document_id"],
            version_id=result["version_id"],
            ingest_job_id=result["ingest_job_id"],
        )
    finally:
        conn.close()


@router.post(
    "/v1/documents/{document_id}/versions",
    response_model=DocumentUploadResponse,
    dependencies=[Depends(require_bearer)],
)
async def update_document_version(
    document_id: str,
    file: UploadFile = File(...),
) -> DocumentUploadResponse:
    """Upload a new version of an existing document (S11)."""
    conn = get_conn()
    root = get_root()
    try:
        doc = repo.get_document(conn, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="document not found")
        raw = await file.read()
        display_name = file.filename or doc["display_name"]
        from evidence_agent.ingestion.errors import IngestError
        from evidence_agent.ingestion.pipeline import update_document_file

        try:
            result = update_document_file(
                conn,
                root=root,
                project_id=doc["project_id"],
                document_id=document_id,
                display_name=display_name,
                data=raw,
                content_type=file.content_type,
            )
        except IngestError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return DocumentUploadResponse(
            document_id=result["document_id"],
            version_id=result["version_id"],
            ingest_job_id=result["ingest_job_id"],
        )
    finally:
        conn.close()


@router.get(
    "/v1/documents/{document_id}",
    response_model=DocumentStatusResponse,
    dependencies=[Depends(require_bearer)],
)
def get_document(document_id: str) -> DocumentStatusResponse:
    conn = get_conn()
    try:
        doc = repo.get_document(conn, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="document not found")
        ver = repo.latest_version_for_document(conn, document_id)
        index_status = "pending"
        if doc["status"] in ("parse_failed", "needs_ocr", "rejected"):
            index_status = "blocked"
        elif doc["status"] == "parsed":
            index_status = "pending"  # S12
        err = None
        job = conn.execute(
            "SELECT error_code FROM ingest_jobs WHERE document_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        if job and job["error_code"]:
            err = job["error_code"]
        return DocumentStatusResponse(
            document_id=doc["id"],
            project_id=doc["project_id"],
            display_name=doc["display_name"],
            status=doc["status"],
            version_id=ver["id"] if ver else None,
            parse_status=ver["parse_status"] if ver else None,
            content_hash=ver["content_hash"] if ver else None,
            index_status=index_status,
            error_code=err,
        )
    finally:
        conn.close()
