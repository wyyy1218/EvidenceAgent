"""Run create/query/cancel/SSE/evidence/export."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from evidence_agent.api.deps import get_conn, require_bearer
from evidence_agent.api.schemas import (
    CancelResponse,
    RunCreate,
    RunCreateResponse,
    RunStatusResponse,
)
from evidence_agent.storage import repositories as repo

router = APIRouter(prefix="/v1/runs", tags=["runs"])

MAX_QUEUE = 10
ALLOWED_BUDGET_PROFILES = frozenset({"standard"})


def _canonical_hash(body: dict[str, Any]) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_budget(profile: str) -> dict[str, Any]:
    # Fixed standard profile from project.yaml — values mirrored for API visibility.
    return {
        "profile": profile,
        "tool_calls": 8,
        "input_tokens": 48000,
        "output_tokens": 4096,
        "wall_seconds": 240,
    }


@router.post("", response_model=RunCreateResponse, dependencies=[Depends(require_bearer)])
def create_run(
    body: RunCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunCreateResponse:
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_question", "message": "question must be non-empty"},
        )
    if body.budget_profile not in ALLOWED_BUDGET_PROFILES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_budget_profile",
                "message": "external clients may only use budget_profile=standard",
            },
        )

    conn = get_conn()
    try:
        proj = repo.get_project(conn, body.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="project not found")

        payload = {
            "project_id": body.project_id,
            "question": q,
            "allow_web": body.allow_web,
            "budget_profile": body.budget_profile,
        }
        req_hash = _canonical_hash(payload)
        version_set = repo.list_project_version_ids(conn, body.project_id)

        conn.execute("BEGIN")
        try:
            run_id, _created = repo.create_run(
                conn,
                project_id=body.project_id,
                question=q,
                allow_web=body.allow_web,
                budget_profile=body.budget_profile,
                budget=_parse_budget(body.budget_profile),
                idempotency_key=idempotency_key,
                request_hash=req_hash,
                version_set=version_set,
                max_queue=MAX_QUEUE,
            )
            conn.execute("COMMIT")
        except repo.IdempotencyConflict as exc:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except repo.QueueFull as exc:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=429,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        except Exception:
            conn.execute("ROLLBACK")
            raise

        run = repo.get_run(conn, run_id)
        assert run is not None
        return RunCreateResponse(run_id=run_id, status=run["status"])
    finally:
        conn.close()


@router.get("/{run_id}", response_model=RunStatusResponse, dependencies=[Depends(require_bearer)])
def get_run(run_id: str) -> RunStatusResponse:
    conn = get_conn()
    try:
        run = repo.get_run(conn, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        budget = json.loads(run["budget"]) if run["budget"] else None
        result = json.loads(run["result_json"]) if run["result_json"] else None
        vset = json.loads(run["version_set_json"]) if run["version_set_json"] else []
        return RunStatusResponse(
            run_id=run["id"],
            project_id=run["project_id"],
            question=run["question"],
            status=run["status"],
            budget=budget,
            cancel_requested=bool(run["cancel_requested"]),
            failure_reason=run["failure_reason"],
            error_code=run["error_code"],
            result=result,
            version_set=vset,
        )
    finally:
        conn.close()


@router.post("/{run_id}/cancel", response_model=CancelResponse, dependencies=[Depends(require_bearer)])
def cancel_run(run_id: str) -> CancelResponse:
    conn = get_conn()
    try:
        conn.execute("BEGIN")
        run = repo.get_run(conn, run_id)
        if not run:
            conn.execute("ROLLBACK")
            raise HTTPException(status_code=404, detail="run not found")
        repo.request_cancel(conn, run_id)
        # If still queued, finalize immediately as cancelled
        run2 = repo.get_run(conn, run_id)
        if run2 and run2["status"] == "queued" and run2["cancel_requested"]:
            repo.finalize_run(conn, run_id, status="cancelled", failure_reason="cancelled")
        conn.execute("COMMIT")
        run3 = repo.get_run(conn, run_id)
        assert run3
        return CancelResponse(
            run_id=run_id,
            cancel_requested=bool(run3["cancel_requested"]) or run3["status"] == "cancelled",
            status=run3["status"],
        )
    except HTTPException:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@router.get("/{run_id}/events", dependencies=[Depends(require_bearer)])
def run_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    conn = get_conn()
    run = repo.get_run(conn, run_id)
    if not run:
        conn.close()
        raise HTTPException(status_code=404, detail="run not found")
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    conn.close()

    def gen() -> Iterator[str]:
        cursor = after
        idle = 0
        while idle < 30:
            c = get_conn()
            try:
                events = repo.list_audit_events(c, run_id, after_id=cursor, limit=50)
                run_row = repo.get_run(c, run_id)
            finally:
                c.close()
            if not events:
                idle += 1
                yield ": keepalive\n\n"
                time.sleep(0.5)
                if run_row and run_row["status"] in repo.TERMINAL_STATUSES:
                    break
                continue
            idle = 0
            for ev in events:
                cursor = int(ev["id"])
                data = json.dumps(
                    {"event_type": ev["event_type"], "payload": json.loads(ev["payload"] or "{}")},
                    ensure_ascii=False,
                )
                yield f"id: {cursor}\nevent: {ev['event_type']}\ndata: {data}\n\n"
            if run_row and run_row["status"] in repo.TERMINAL_STATUSES:
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{run_id}/evidence/{evidence_id}", dependencies=[Depends(require_bearer)])
def get_evidence(run_id: str, evidence_id: str) -> dict[str, Any]:
    conn = get_conn()
    try:
        run = repo.get_run(conn, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        ev = repo.get_evidence(conn, run_id, evidence_id)
        if not ev:
            # Do not reveal whether evidence exists in another project/run
            raise HTTPException(
                status_code=404,
                detail={"code": "evidence_not_found", "message": "evidence not found for this run"},
            )
        return {
            "evidence_id": ev["id"],
            "run_id": run_id,
            "source_version_id": ev["source_version_id"],
            "span": ev["span"],
            "quote": ev["quote"],
            "page": ev["page"],
            "title": ev["title"],
            "line_start": ev["line_start"],
            "char_start": ev["char_start"],
            "char_end": ev["char_end"],
        }
    finally:
        conn.close()


@router.get("/{run_id}/export", dependencies=[Depends(require_bearer)])
def export_run(run_id: str) -> dict[str, Any]:
    """U10: answer.json + citation list + readable Markdown (+ zip)."""
    from evidence_agent.api.deps import get_root
    from evidence_agent.export.package import build_export_package

    conn = get_conn()
    try:
        run = repo.get_run(conn, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        pkg = build_export_package(conn, root=get_root(), run_id=run_id)
        result = json.loads(run["result_json"]) if run["result_json"] else None
        return {
            "run_id": run_id,
            "status": run["status"],
            "question": run["question"],
            "result": result,
            "version_set": json.loads(run["version_set_json"] or "[]"),
            "export": pkg,
        }
    finally:
        conn.close()
