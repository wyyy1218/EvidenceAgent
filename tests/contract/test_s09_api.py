"""S09 contract tests: T01, T17, queue full, auth, T20, transaction integrity."""
from __future__ import annotations

import pytest

from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo


def test_healthz_no_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_requires_auth(client):
    r = client.get("/readyz")
    assert r.status_code == 401


def test_t01_empty_question(client, auth_headers):
    pr = client.post(
        "/v1/projects",
        headers=auth_headers,
        json={"name": "p1", "description": ""},
    )
    assert pr.status_code == 200
    pid = pr.json()["project_id"]
    r = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={"project_id": pid, "question": "   ", "allow_web": False, "budget_profile": "standard"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_question"


def test_t17_idempotency(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "p2", "description": ""}
    ).json()["project_id"]
    body = {
        "project_id": pid,
        "question": "比较方案是否可离线部署？",
        "allow_web": False,
        "budget_profile": "standard",
    }
    h = {**auth_headers, "Idempotency-Key": "idem-key-001"}
    r1 = client.post("/v1/runs", headers=h, json=body)
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]
    r2 = client.post("/v1/runs", headers=h, json=body)
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id
    body2 = dict(body)
    body2["question"] = "不同问题体"
    r3 = client.post("/v1/runs", headers=h, json=body2)
    assert r3.status_code == 409
    assert r3.json()["detail"]["code"] == "idempotency_conflict"


def test_queue_full_429(client, auth_headers, work_tmp):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "pq", "description": ""}
    ).json()["project_id"]
    # Fill queue to 10 without worker consuming
    for i in range(10):
        r = client.post(
            "/v1/runs",
            headers=auth_headers,
            json={
                "project_id": pid,
                "question": f"q{i}",
                "allow_web": False,
                "budget_profile": "standard",
            },
        )
        assert r.status_code == 200, r.text
    r = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={
            "project_id": pid,
            "question": "overflow",
            "allow_web": False,
            "budget_profile": "standard",
        },
    )
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "queue_full"


def test_t20_evidence_missing(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "pe", "description": ""}
    ).json()["project_id"]
    run_id = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={
            "project_id": pid,
            "question": "有证据吗",
            "allow_web": False,
            "budget_profile": "standard",
        },
    ).json()["run_id"]
    r = client.get(f"/v1/runs/{run_id}/evidence/ev_nonexistent", headers=auth_headers)
    assert r.status_code == 404


def test_cross_project_document_404(client, auth_headers):
    r = client.get("/v1/documents/doc_does_not_exist", headers=auth_headers)
    assert r.status_code == 404


def test_action_transaction_no_half_row(work_tmp):
    conn = connect(work_tmp)
    try:
        conn.execute("BEGIN")
        pid = repo.create_project(conn, "tx", "")
        rid, _ = repo.create_run(
            conn,
            project_id=pid,
            question="tx test",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
            max_queue=10,
        )
        conn.execute("COMMIT")
        with pytest.raises(RuntimeError):
            repo.register_action_then_fail(
                conn, run_id=rid, step_no=1, action={"action": "local_search"}
            )
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM actions WHERE run_id = ?", (rid,)
        ).fetchone()["c"]
        assert n == 0
        # successful atomic write
        aid = repo.register_action_and_result(
            conn,
            run_id=rid,
            step_no=1,
            action={"action": "local_search", "query": "x"},
            result_status="ok",
            result={"hits": []},
        )
        assert aid
        n2 = conn.execute(
            "SELECT COUNT(*) AS c FROM actions WHERE run_id = ? AND result_status IS NOT NULL",
            (rid,),
        ).fetchone()["c"]
        assert n2 == 1
    finally:
        conn.close()


def test_cancel_queued(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "pc", "description": ""}
    ).json()["project_id"]
    run_id = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={
            "project_id": pid,
            "question": "cancel me",
            "allow_web": False,
            "budget_profile": "standard",
        },
    ).json()["run_id"]
    r = client.post(f"/v1/runs/{run_id}/cancel", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_failed_policy_maps_externally(work_tmp):
    conn = connect(work_tmp)
    try:
        conn.execute("BEGIN")
        pid = repo.create_project(conn, "fp", "")
        rid, _ = repo.create_run(
            conn,
            project_id=pid,
            question="policy",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        repo.finalize_run(
            conn, rid, status="failed", failure_reason="failed_policy"
        )
        conn.execute("COMMIT")
        row = repo.get_run(conn, rid)
        assert row["status"] == "failed"
        assert row["failure_reason"] == "failed_policy"
        assert row["error_code"] == "failed_policy"
    finally:
        conn.close()
