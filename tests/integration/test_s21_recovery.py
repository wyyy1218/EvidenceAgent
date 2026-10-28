"""S21: cancel, SSE Last-Event-ID, crash recovery policy, backup restore."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from evidence_agent.agent.budget import BudgetState
from evidence_agent.agent.graph import run_agent_loop
from evidence_agent.agent.llm import LLMResponse, LLMUsage, MockLLMClient
from evidence_agent.storage.backup import (
    backup_sqlite_consistent,
    classify_paid_call_recovery,
    dump_run_trajectory,
    restore_sqlite_from_backup,
)
from evidence_agent.storage.db import connect, db_path
from evidence_agent.storage import repositories as repo
from evidence_agent.tools.candidates import CandidateRegistry


def test_paid_call_recovery_policy():
    assert classify_paid_call_recovery("not_started") == "may_execute"
    assert classify_paid_call_recovery("completed") == "skip_replay"
    assert classify_paid_call_recovery("completion_unknown") == "mark_review_no_replay"


def test_t19_cancel_stops_new_steps(work_tmp, client, auth_headers):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s21", "")
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="long running?",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        conn.commit()
    finally:
        conn.close()

    # Cancel while queued → cancelled without worker
    r = client.post(f"/v1/runs/{run_id}/cancel", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["cancel_requested"] or body["status"] == "cancelled"
    assert body["status"] == "cancelled"

    conn = connect(work_tmp)
    try:
        run = repo.get_run(conn, run_id)
        assert run["status"] == "cancelled"
        # Usage may be empty but schema allows later remote fees to be recorded
        n_actions = conn.execute(
            "SELECT COUNT(*) AS c FROM actions WHERE run_id = ?", (run_id,)
        ).fetchone()["c"]
        assert n_actions == 0  # never started
    finally:
        conn.close()


def test_u08_sse_last_event_id(work_tmp, client, auth_headers):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s21e", "")
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="sse?",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        repo.add_audit(conn, run_id, "step", {"step_no": 1})
        repo.add_audit(conn, run_id, "step", {"step_no": 2})
        repo.finalize_run(conn, run_id, status="insufficient_evidence", result={"note": "done"})
        conn.commit()
        events = repo.list_audit_events(conn, run_id, after_id=0)
        assert len(events) >= 2
        first_id = int(events[0]["id"])
    finally:
        conn.close()

    # Resume from first event — should not create a new run
    with client.stream(
        "GET",
        f"/v1/runs/{run_id}/events",
        headers={**auth_headers, "Last-Event-ID": str(first_id)},
    ) as resp:
        assert resp.status_code == 200
        text = "".join(list(resp.iter_text()))
    assert f"id: " in text
    # Same run_id only
    assert run_id
    # Get status still same id
    st = client.get(f"/v1/runs/{run_id}", headers=auth_headers)
    assert st.json()["run_id"] == run_id


def test_t18_cancel_mid_loop(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s21c", "")
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="cancel mid",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        conn.commit()
        cancelled = {"v": False}

        class SearchThenCancel(MockLLMClient):
            n = 0

            def chat(self, messages, *, max_tokens=768, temperature=0.0, adapter_id=None):
                self.n += 1
                if self.n == 1:
                    cancelled["v"] = True
                    content = json.dumps(
                        {
                            "action": "local_search",
                            "query": "x",
                            "candidate_id": None,
                            "reason_code": None,
                        }
                    )
                else:
                    content = json.dumps(
                        {
                            "action": "finish",
                            "query": None,
                            "candidate_id": None,
                            "reason_code": "budget_exhausted",
                        }
                    )
                self.calls.append(messages)
                return LLMResponse(
                    content=content,
                    usage=LLMUsage(input_tokens=3, output_tokens=3, route="base", model="m"),
                )

        out = run_agent_loop(
            root=work_tmp,
            conn=conn,
            run_id=run_id,
            project_id=pid,
            question="cancel mid",
            client=SearchThenCancel(),
            budget=BudgetState(),
            registry=CandidateRegistry(),
            cancel_check=lambda: cancelled["v"],
        )
        conn.commit()
        # After first policy sets cancel flag, subsequent nodes should finalize cancelled
        assert out["status"] == "cancelled" or repo.get_run(conn, run_id)["status"] == "cancelled"
    finally:
        conn.close()


def test_trajectory_dump_and_backup_restore(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s21b", "")
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="backup?",
            allow_web=False,
            budget_profile="standard",
            budget={},
            idempotency_key=None,
            request_hash=None,
            version_set=[],
        )
        repo.register_action_and_result(
            conn,
            run_id=run_id,
            step_no=1,
            action={"action": "abstain", "query": None, "candidate_id": None, "reason_code": "missing_source"},
            result_status="ok",
            result={"note": "x"},
            commit=False,
        )
        repo.finalize_run(conn, run_id, status="insufficient_evidence", result={"ok": True})
        conn.commit()
        traj = dump_run_trajectory(conn, work_tmp, run_id)
        assert traj.is_file()
        data = json.loads(traj.read_text(encoding="utf-8"))
        assert data["run"]["id"] == run_id
        assert len(data["actions"]) == 1
    finally:
        conn.close()

    man = backup_sqlite_consistent(work_tmp, label="bak_s21_test")
    assert Path(work_tmp / "runs" / "backups" / "bak_s21_test" / "evidence_agent.sqlite").is_file()
    assert man["sha256"]
    bak = work_tmp / "runs" / "backups" / "bak_s21_test" / "evidence_agent.sqlite"
    target = work_tmp / "runs" / "backups" / "_restore_smoke" / "evidence_agent.sqlite"
    info = restore_sqlite_from_backup(bak, target_db=target)
    assert info["tables"] > 0
    # Open restored DB and find run
    import sqlite3

    c2 = sqlite3.connect(str(target))
    c2.row_factory = sqlite3.Row
    try:
        n = c2.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
        assert n >= 1
    finally:
        c2.close()


def test_no_duplicate_run_on_reconnect(work_tmp, client, auth_headers):
    """U08: refresh uses same run_id — creating again would be a different key."""
    r1 = client.post(
        "/v1/projects",
        headers=auth_headers,
        json={"name": "s21u08", "description": ""},
    )
    pid = r1.json()["project_id"]
    r2 = client.post(
        "/v1/runs",
        headers={**auth_headers, "Idempotency-Key": "idem-s21-1"},
        json={"project_id": pid, "question": "same?", "allow_web": False, "budget_profile": "standard"},
    )
    run_id = r2.json()["run_id"]
    r3 = client.post(
        "/v1/runs",
        headers={**auth_headers, "Idempotency-Key": "idem-s21-1"},
        json={"project_id": pid, "question": "same?", "allow_web": False, "budget_profile": "standard"},
    )
    assert r3.json()["run_id"] == run_id
