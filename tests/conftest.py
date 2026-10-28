"""Shared pytest fixtures — isolated WORK_ROOT temp DB."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def work_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("WORK_ROOT", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_AGENT_API_TOKEN", "test-token-s09")
    (tmp_path / "data" / "app").mkdir(parents=True)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "normalized").mkdir(parents=True)
    (tmp_path / "data" / "chunks").mkdir(parents=True)
    (tmp_path / "data" / "indexes").mkdir(parents=True)
    (tmp_path / "data" / "snapshots").mkdir(parents=True)
    (tmp_path / "data" / "manifests").mkdir(parents=True)
    from evidence_agent.storage.migrate import ensure_db

    ensure_db(tmp_path)
    return tmp_path


@pytest.fixture()
def client(work_tmp):
    from fastapi.testclient import TestClient
    from evidence_agent.api.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer test-token-s09"}
