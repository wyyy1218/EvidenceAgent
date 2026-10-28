"""S10 upload validation & parse tests (T02, T03)."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _upload(client, auth_headers, project_id: str, path: Path, content_type: str | None = None):
    data = path.read_bytes()
    files = {"file": (path.name, data, content_type or "application/octet-stream")}
    return client.post(
        f"/v1/projects/{project_id}/documents",
        headers=auth_headers,
        files=files,
    )


def test_t02_empty_file(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "t02", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "empty.txt", "text/plain")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_file"


def test_t02_disguised_pdf(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "t02b", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "disguised.pdf", "application/pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "disguised_or_invalid_pdf"


def test_t02_invalid_encoding(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "t02c", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "bad_encoding.txt", "text/plain")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_encoding"


def test_t02_size_boundary_accept(client, auth_headers, tmp_path):
    """Exactly 20MiB accepted; 20MiB+1 rejected."""
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "t02d", "description": ""}
    ).json()["project_id"]
    ok = tmp_path / "edge.txt"
    ok.write_bytes(b"a" * (20 * 1024 * 1024))
    r = client.post(
        f"/v1/projects/{pid}/documents",
        headers=auth_headers,
        files={"file": ("edge.txt", ok.read_bytes(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    over = tmp_path / "over.txt"
    over.write_bytes(b"a" * (20 * 1024 * 1024 + 1))
    r2 = client.post(
        f"/v1/projects/{pid}/documents",
        headers=auth_headers,
        files={"file": ("over.txt", over.read_bytes(), "text/plain")},
    )
    assert r2.status_code == 413
    assert r2.json()["detail"]["code"] == "file_too_large"


def test_legal_md_and_hash(client, auth_headers, work_tmp):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "ok", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "sample.md", "text/markdown")
    assert r.status_code == 200, r.text
    body = r.json()
    st = client.get(f"/v1/documents/{body['document_id']}", headers=auth_headers)
    assert st.status_code == 200
    js = st.json()
    assert js["status"] == "parsed"
    assert js["parse_status"] in ("parsed", "deduped")
    assert js["index_status"] == "pending"
    assert js["content_hash"]
    # hash matches file
    import hashlib

    expect = hashlib.sha256((FIXTURES / "sample.md").read_bytes()).hexdigest()
    assert js["content_hash"] == expect
    # normalized exists
    vid = body["version_id"]
    assert (work_tmp / "data" / "normalized" / vid / "content_clean.txt").is_file()
    assert (work_tmp / "data" / "normalized" / vid / "mapping.json").is_file()


def test_t03_needs_ocr(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "ocr", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "scan_like.pdf", "application/pdf")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "needs_ocr"


def test_text_pdf_ok(client, auth_headers):
    pid = client.post(
        "/v1/projects", headers=auth_headers, json={"name": "pdf", "description": ""}
    ).json()["project_id"]
    r = _upload(client, auth_headers, pid, FIXTURES / "sample_text.pdf", "application/pdf")
    assert r.status_code == 200, r.text
    st = client.get(f"/v1/documents/{r.json()['document_id']}", headers=auth_headers)
    assert st.json()["status"] == "parsed"
