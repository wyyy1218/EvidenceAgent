"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectResponse(BaseModel):
    project_id: str


class DocumentUploadResponse(BaseModel):
    document_id: str
    version_id: str
    ingest_job_id: str


class DocumentStatusResponse(BaseModel):
    document_id: str
    project_id: str
    display_name: str
    status: str
    version_id: str | None = None
    parse_status: str | None = None
    content_hash: str | None = None
    index_status: str = "pending"
    error_code: str | None = None


class RunCreate(BaseModel):
    project_id: str
    question: str = Field(min_length=0, max_length=8000)
    allow_web: bool = False
    budget_profile: str = "standard"


class RunCreateResponse(BaseModel):
    run_id: str
    status: str


class RunStatusResponse(BaseModel):
    run_id: str
    project_id: str
    question: str
    status: str
    budget: Any = None
    cancel_requested: bool = False
    failure_reason: str | None = None
    error_code: str | None = None
    result: Any = None
    version_set: list[str] | None = None


class CancelResponse(BaseModel):
    run_id: str
    cancel_requested: bool
    status: str


class ErrorBody(BaseModel):
    code: str
    message: str
