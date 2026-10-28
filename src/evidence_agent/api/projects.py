"""Project endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from evidence_agent.api.deps import get_conn, require_bearer
from evidence_agent.api.schemas import ProjectCreate, ProjectResponse
from evidence_agent.storage import repositories as repo

router = APIRouter(prefix="/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, dependencies=[Depends(require_bearer)])
def create_project(body: ProjectCreate) -> ProjectResponse:
    conn = get_conn()
    try:
        conn.execute("BEGIN")
        pid = repo.create_project(conn, body.name, body.description)
        conn.execute("COMMIT")
        return ProjectResponse(project_id=pid)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@router.get("/{project_id}", dependencies=[Depends(require_bearer)])
def get_project(project_id: str) -> dict:
    conn = get_conn()
    try:
        p = repo.get_project(conn, project_id)
        if not p:
            raise HTTPException(status_code=404, detail="project not found")
        return p
    finally:
        conn.close()
