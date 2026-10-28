"""S23: export package (U10) + five-page UI surface checks."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.export.package import build_export_package
from evidence_agent.ingestion.pipeline import ingest_upload
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UI_APP = Path(__file__).resolve().parents[2] / "src" / "evidence_agent" / "ui" / "app.py"


def test_five_pages_in_ui_source():
    text = UI_APP.read_text(encoding="utf-8")
    for label in ("项目与文档", "研究工作台", "结论与证据", "运行记录", "实验结果"):
        assert label in text
    assert "尚未运行" in text
    assert "allow_web" in text
    assert "/export" in text


def test_export_package_u10(work_tmp):
    conn = connect(work_tmp)
    try:
        pid = repo.create_project(conn, "s23", "")
        data = (FIXTURES / "sample.md").read_bytes()
        ingest_upload(
            conn,
            root=work_tmp,
            project_id=pid,
            display_name="sample.md",
            data=data,
            content_type="text/markdown",
        )
        versions = repo.list_project_version_ids(conn, pid)
        run_id, _ = repo.create_run(
            conn,
            project_id=pid,
            question="测试导出",
            allow_web=False,
            budget_profile="standard",
            budget={"tool_calls": 8},
            idempotency_key=None,
            request_hash=None,
            version_set=versions,
        )
        # Minimal evidence row via insert if available
        result = {
            "status": "answered",
            "answer": "示例答案",
            "claims": [{"claim_id": "cl_1", "text": "事实", "evidence_ids": []}],
            "unresolved": [],
            "usage": {"logical_tool_calls": 0},
        }
        repo.finalize_run(conn, run_id, status="answered", result=result)
        conn.commit()

        pkg = build_export_package(conn, root=work_tmp, run_id=run_id)
        assert Path(pkg["files"]["answer_json"]).is_file()
        assert Path(pkg["files"]["citations_json"]).is_file()
        assert Path(pkg["files"]["report_md"]).is_file()
        assert Path(pkg["files"]["zip"]).is_file()
        answer = json.loads(Path(pkg["files"]["answer_json"]).read_text(encoding="utf-8"))
        assert answer["run_id"] == run_id
        assert answer["question"] == "测试导出"
        md = Path(pkg["files"]["report_md"]).read_text(encoding="utf-8")
        assert "示例答案" in md
        assert pkg["sha256"]["answer_json"]
    finally:
        conn.close()


def test_export_api(client, auth_headers, work_tmp):
    # create project + run via API
    r = client.post("/v1/projects", headers=auth_headers, json={"name": "s23api", "description": ""})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    r = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={"project_id": pid, "question": "导出 API", "allow_web": False, "budget_profile": "standard"},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    # finalize manually so export has content
    conn = connect(work_tmp)
    try:
        repo.finalize_run(
            conn,
            run_id,
            status="answered",
            result={"status": "answered", "answer": "api", "claims": [], "unresolved": []},
        )
        conn.commit()
    finally:
        conn.close()
    r = client.get(f"/v1/runs/{run_id}/export", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "export" in body
    assert body["export"]["files"]["answer_json"]
    assert Path(body["export"]["files"]["report_md"]).is_file()


def test_empty_question_t01(client, auth_headers):
    r = client.post("/v1/projects", headers=auth_headers, json={"name": "t01", "description": ""})
    pid = r.json()["project_id"]
    r = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={"project_id": pid, "question": "   ", "allow_web": False, "budget_profile": "standard"},
    )
    assert r.status_code == 400
