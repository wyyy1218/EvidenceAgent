"""Apply SQL migrations."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from evidence_agent.storage.db import connect, db_path, work_root

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def applied_versions(conn) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r["version"] for r in rows}


def apply_migrations(root: Path | None = None, *, path: Path | None = None) -> list[str]:
    root = root or work_root()
    conn = connect(root, path=path)
    applied: list[str] = []
    try:
        done = applied_versions(conn)
        files = sorted(
            p for p in MIGRATIONS_DIR.glob("*.sql") if not p.name.endswith("_down.sql")
        )
        for sql_path in files:
            version = sql_path.name.split("_")[0]
            if version in done:
                continue
            script = sql_path.read_text(encoding="utf-8")
            # executescript issues implicit commits; apply then record
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, _utc_now()),
            )
            applied.append(version)
        return applied
    finally:
        conn.close()


def ensure_db(root: Path | None = None) -> Path:
    root = root or work_root()
    p = db_path(root)
    apply_migrations(root, path=p)
    return p
