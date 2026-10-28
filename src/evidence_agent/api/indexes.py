"""Project index build/status (S12)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from evidence_agent.api.deps import get_conn, get_root, require_bearer
from evidence_agent.storage import repositories as repo

router = APIRouter(tags=["indexes"])


class IndexBuildRequest(BaseModel):
    use_hash_embedder: bool = Field(
        default=False,
        description="If true, use deterministic HashEmbedder (tests). Production should leave false.",
    )


class IndexBuildResponse(BaseModel):
    index_id: str
    chunk_count: int
    version_set_hash: str
    path: str
    embedding_revision: str


def _resolve_embedder(root: Path, *, use_hash: bool):
    from evidence_agent.retrieval.dense import HashEmbedder, SentenceTransformerEmbedder

    if use_hash or os.environ.get("EVIDENCE_AGENT_FAKE_EMBEDDER") == "1":
        return HashEmbedder()
    emb_root = root / "models" / "embedding"
    if not emb_root.is_dir():
        # graceful local fallback
        return HashEmbedder(revision="hash_fallback_no_model_dir")
    revs = sorted(
        [p for p in emb_root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not revs:
        return HashEmbedder(revision="hash_fallback_empty_model_dir")
    try:
        return SentenceTransformerEmbedder(revs[0], device="cpu", threads=8)
    except Exception:  # noqa: BLE001
        return HashEmbedder(revision="hash_fallback_st_import_failed")


@router.post(
    "/v1/projects/{project_id}/indexes",
    response_model=IndexBuildResponse,
    dependencies=[Depends(require_bearer)],
)
def build_index(project_id: str, body: IndexBuildRequest | None = None) -> IndexBuildResponse:
    body = body or IndexBuildRequest()
    conn = get_conn()
    root = get_root()
    try:
        if not repo.get_project(conn, project_id):
            raise HTTPException(status_code=404, detail="project not found")
        from evidence_agent.retrieval.index_store import build_project_index

        embedder = _resolve_embedder(root, use_hash=body.use_hash_embedder)
        try:
            result = build_project_index(
                conn, root=root, project_id=project_id, embedder=embedder
            )
            conn.commit()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "index_build_failed", "message": str(exc)},
            ) from exc
        return IndexBuildResponse(
            index_id=result["index_id"],
            chunk_count=result["chunk_count"],
            version_set_hash=result["version_set_hash"],
            path=result["path"],
            embedding_revision=result["embedding_revision"],
        )
    finally:
        conn.close()


@router.get(
    "/v1/projects/{project_id}/indexes/current",
    dependencies=[Depends(require_bearer)],
)
def current_index(project_id: str) -> dict[str, Any]:
    root = get_root()
    ptr = root / "data" / "indexes" / f"current_{project_id}.json"
    if not ptr.is_file():
        raise HTTPException(status_code=404, detail={"code": "index_not_ready", "message": "no index"})
    import json

    return json.loads(ptr.read_text(encoding="utf-8"))
