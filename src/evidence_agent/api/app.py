"""EvidenceAgent FastAPI application (S08 ask + S09 projects/runs/documents)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from evidence_agent.api.deps import require_bearer
from evidence_agent.api import documents as documents_routes
from evidence_agent.api import indexes as indexes_routes
from evidence_agent.api import projects as projects_routes
from evidence_agent.api import runs as runs_routes
from evidence_agent.storage.migrate import ensure_db

WORK_ROOT = Path(os.environ.get("WORK_ROOT", "/root/autodl-tmp/evidence-agent"))
STATE_PATH = WORK_ROOT / "runs" / "system" / "service_state.json"
VLLM_BASE = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
BASE_MODEL_ID = os.environ.get("EVIDENCE_AGENT_BASE_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")

app = FastAPI(title="EvidenceAgent API", version="0.1.0")
app.include_router(projects_routes.router)
app.include_router(documents_routes.router)
app.include_router(runs_routes.router)
app.include_router(indexes_routes.router)


@app.on_event("startup")
def _startup() -> None:
    ensure_db(WORK_ROOT)


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {"services": {}, "updated": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"services": {}, "updated": None, "error": "state_corrupt"}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    answer: str
    model: str
    route: str
    latency_ms: int
    error: str | None = None


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "evidence-agent-api", "ts": time.time()}


@app.get("/readyz")
def readyz(_: None = Depends(require_bearer)) -> dict[str, Any]:
    not_ready: list[str] = []
    checks: dict[str, Any] = {}

    model_ok = False
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{VLLM_BASE}/models")
            checks["vllm_status_code"] = r.status_code
            if r.status_code == 200:
                data = r.json()
                ids = [m.get("id") for m in data.get("data", [])]
                checks["vllm_models"] = ids
                model_ok = len(ids) > 0
            else:
                not_ready.append("model")
    except Exception as exc:  # noqa: BLE001
        checks["vllm_error"] = type(exc).__name__
        not_ready.append("model")
    if not model_ok and "model" not in not_ready:
        not_ready.append("model")

    index_dir = WORK_ROOT / "data" / "indexes"
    has_index = index_dir.is_dir() and any(index_dir.iterdir())
    checks["index_present"] = has_index
    if not has_index:
        not_ready.append("index")

    state = _load_state()
    worker = state.get("services", {}).get("worker", {})
    worker_running = bool(worker.get("running"))
    checks["worker_running"] = worker_running
    if not worker_running:
        not_ready.append("worker")

    return {
        "ready": len(not_ready) == 0,
        "not_ready": not_ready,
        "checks": checks,
    }


@app.post("/v1/ask", response_model=AskResponse)
def ask(body: AskRequest, _: None = Depends(require_bearer)) -> AskResponse:
    t0 = time.perf_counter()
    payload = {
        "model": BASE_MODEL_ID,
        "messages": [
            {
                "role": "system",
                "content": "You are a concise assistant. Answer briefly in the user's language.",
            },
            {"role": "user", "content": body.question},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(f"{VLLM_BASE}/chat/completions", json=payload)
            latency = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return AskResponse(
                    answer="",
                    model=BASE_MODEL_ID,
                    route="base",
                    latency_ms=latency,
                    error=f"vllm_http_{r.status_code}: {r.text[:500]}",
                )
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            used = data.get("model") or BASE_MODEL_ID
            return AskResponse(
                answer=answer,
                model=used,
                route="base",
                latency_ms=latency,
                error=None,
            )
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - t0) * 1000)
        return AskResponse(
            answer="",
            model=BASE_MODEL_ID,
            route="base",
            latency_ms=latency,
            error=f"{type(exc).__name__}: {exc}",
        )


@app.get("/v1/meta/schema")
def schema_meta(_: None = Depends(require_bearer)) -> dict[str, Any]:
    return {
        "api_version": "0.1.0",
        "terminal_statuses": sorted(repo_terminal()),
        "failed_policy_maps_to": "failed",
    }


def repo_terminal() -> frozenset:
    from evidence_agent.storage.repositories import TERMINAL_STATUSES

    return TERMINAL_STATUSES
