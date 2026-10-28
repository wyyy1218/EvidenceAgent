"""SQLite connection factory — WAL + foreign_keys."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def work_root() -> Path:
    return Path(os.environ.get("WORK_ROOT", "/root/autodl-tmp/evidence-agent"))


def db_path(root: Path | None = None) -> Path:
    root = root or work_root()
    return root / "data" / "app" / "evidence_agent.sqlite"


def connect(root: Path | None = None, *, path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), isolation_level=None)  # autocommit off via explicit BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
