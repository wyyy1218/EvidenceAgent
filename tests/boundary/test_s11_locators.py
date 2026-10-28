"""S11: T04 locators, T05 dedup, T06 version snapshot lock."""
from __future__ import annotations

import json
from pathlib import Path

from evidence_agent.ingestion.locators import build_text_mapping, slice_clean
from evidence_agent.ingestion.parse_text import parse_text_bytes
from evidence_agent.storage.db import connect
from evidence_agent.storage import repositories as repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_t04_unicode_spans_roundtrip():
    data = (FIXTURES / "sample.md").read_bytes()
    # ensure BOM case
    bom_data = b"\xef\xbb\xbf" + data
    parsed = parse_text_bytes(bom_data, kind="md")
    assert parsed["bom_stripped"] is True
    mapping = build_text_mapping(parsed)
    clean = parsed["clean_text"]
    # find a known substring
    needle = "方案甲可在断网环境中独立运行。"
    start = clean.index(needle)
    end = start + len(needle)
    assert slice_clean(clean, start, end) == needle
    # emoji and fullwidth
    for frag in ("✅🚀", "（测试）", "English"):
        s = clean.index(frag)
        e = s + len(frag)
        assert slice_clean(clean, s, e) == frag
    # line map consistency
    assert mapping["coordinate_system"] == "unicode_code_point_half_open"
    assert mapping["lines"][0]["line"] == 1
    assert mapping["headings"]


def test_t05_content_dedup_rename(client, auth_headers, work_tmp):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "dedup", "description": ""}
    ).json()["project_id"]
    raw = (FIXTURES / "sample.txt").read_bytes()
    r1 = client.post(
        f"/v1/projects/{pid}/documents",
        headers=auth_headers,
        files={"file": ("alpha.txt", raw, "text/plain")},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        f"/v1/projects/{pid}/documents",
        headers=auth_headers,
        files={"file": ("beta_renamed.txt", raw, "text/plain")},
    )
    assert r2.status_code == 200, r2.text
    d1 = client.get(f"/v1/documents/{r1.json()['document_id']}", headers=auth_headers).json()
    d2 = client.get(f"/v1/documents/{r2.json()['document_id']}", headers=auth_headers).json()
    assert d1["display_name"] == "alpha.txt"
    assert d2["display_name"] == "beta_renamed.txt"
    assert d1["content_hash"] == d2["content_hash"]
    assert d2["parse_status"] == "deduped"
    # two documents, not a version conflict
    assert d1["document_id"] != d2["document_id"]
    conn = connect(work_tmp)
    try:
        v2 = repo.latest_version_for_document(conn, d2["document_id"])
        assert v2["dedup_of_version_id"] is not None
    finally:
        conn.close()


def test_t06_old_run_keeps_version_set(client, auth_headers, work_tmp):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "ver", "description": ""}
    ).json()["project_id"]
    raw1 = b"version one content AAA\n"
    up1 = client.post(
        f"/v1/projects/{pid}/documents",
        headers=auth_headers,
        files={"file": ("doc.txt", raw1, "text/plain")},
    )
    assert up1.status_code == 200, up1.text
    doc_id = up1.json()["document_id"]
    v1 = up1.json()["version_id"]

    run = client.post(
        "/v1/runs",
        headers=auth_headers,
        json={
            "project_id": pid,
            "question": "根据资料回答",
            "allow_web": False,
            "budget_profile": "standard",
        },
    )
    assert run.status_code == 200
    run_id = run.json()["run_id"]
    st = client.get(f"/v1/runs/{run_id}", headers=auth_headers).json()
    assert v1 in st["version_set"]

    # update document → new version
    raw2 = b"version two content BBB updated\n"
    up2 = client.post(
        f"/v1/documents/{doc_id}/versions",
        headers=auth_headers,
        files={"file": ("doc.txt", raw2, "text/plain")},
    )
    assert up2.status_code == 200, up2.text
    v2 = up2.json()["version_id"]
    assert v2 != v1

    # old run still locked to v1 set
    st2 = client.get(f"/v1/runs/{run_id}", headers=auth_headers).json()
    assert v1 in st2["version_set"]
    assert v2 not in st2["version_set"]

    # normalized for v1 still intact
    clean1 = (work_tmp / "data" / "normalized" / v1 / "content_clean.txt").read_text(
        encoding="utf-8"
    )
    assert "AAA" in clean1
    clean2 = (work_tmp / "data" / "normalized" / v2 / "content_clean.txt").read_text(
        encoding="utf-8"
    )
    assert "BBB" in clean2
