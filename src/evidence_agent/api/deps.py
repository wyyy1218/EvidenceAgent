"""Shared FastAPI dependencies."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Header, HTTPException

from evidence_agent.storage.db import connect, work_root
from evidence_agent.storage.migrate import ensure_db

API_TOKEN = os.environ.get("EVIDENCE_AGENT_API_TOKEN") or os.environ.get("API_BEARER_TOKEN") or ""


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid bearer token")


def get_root() -> Path:
    return work_root()


def get_conn():
    ensure_db()
    return connect()
