"""Consistent SQLite backup (VACUUM INTO) + optional artifact copy (S21)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidence_agent.storage.db import connect, db_path, work_root


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_sqlite_consistent(
    root: Path | None = None,
    *,
    dest_dir: Path | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """
    Create a consistent DB snapshot via VACUUM INTO.
    Do NOT copy only the live .sqlite while ignoring WAL — VACUUM INTO is preferred.
    """
    root = root or work_root()
    src = db_path(root)
    if not src.is_file():
        raise FileNotFoundError(str(src))

    stamp = label or f"bak_s21_{_utc_stamp()}"
    out = dest_dir or (root / "runs" / "backups" / stamp)
    out.mkdir(parents=True, exist_ok=True)
    dest_db = out / "evidence_agent.sqlite"
    # VACUUM INTO refuses an existing path; allow re-backup under same label.
    if dest_db.is_file():
        dest_db.unlink()

    # Checkpoint WAL into main DB first for cleanliness, then VACUUM INTO
    conn = connect(root)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # VACUUM INTO must run outside an explicit transaction in some builds;
        # isolation_level=None means autocommit — OK.
        conn.execute(f"VACUUM INTO '{dest_db.as_posix()}'")
    finally:
        conn.close()

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(src.relative_to(root)).replace("\\", "/"),
        "backup_db": str(dest_db.relative_to(root)).replace("\\", "/")
        if dest_db.is_relative_to(root)
        else str(dest_db),
        "sha256": sha256_file(dest_db),
        "method": "VACUUM INTO after wal_checkpoint(TRUNCATE)",
        "note": "Do not restore by copying live sqlite without WAL/SHM handling",
    }

    # Copy lightweight manifests if present
    for rel in (
        "data/manifests",
        "runs/system/service_state.json",
    ):
        p = root / rel
        if p.is_file():
            target = out / rel.replace("/", "_")
            shutil.copy2(p, target)
            manifest.setdefault("extra_files", []).append(rel)
        elif p.is_dir():
            target = out / "manifests"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(p, target)
            manifest.setdefault("extra_files", []).append(rel)

    (out / "backup_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "SHA256SUMS.txt").write_text(
        f"{manifest['sha256']}  evidence_agent.sqlite\n", encoding="utf-8"
    )
    return manifest


def restore_sqlite_from_backup(
    backup_db: Path,
    *,
    target_db: Path,
) -> dict[str, Any]:
    """Restore by copying a VACUUM snapshot into place (after stopping writers)."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    # Remove stale WAL/SHM so restored main file is authoritative
    for suffix in ("-wal", "-shm"):
        p = Path(str(target_db) + suffix)
        if p.is_file():
            p.unlink()
    shutil.copy2(backup_db, target_db)
    # Verify openable
    conn = sqlite3.connect(str(target_db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"target": str(target_db), "tables": int(n), "sha256": sha256_file(target_db)}


def dump_run_trajectory(conn, root: Path, run_id: str) -> Path:
    """Persist full trajectory to disk — SSE window ≠ complete history."""
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    actions = conn.execute(
        "SELECT * FROM actions WHERE run_id = ? ORDER BY step_no", (run_id,)
    ).fetchall()
    audits = conn.execute(
        "SELECT * FROM audit_events WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    usage = conn.execute(
        "SELECT * FROM usage_events WHERE run_id = ? ORDER BY created_at", (run_id,)
    ).fetchall()
    out_dir = root / "runs" / "trajectories" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    def rows(rs):
        return [dict(r) for r in rs]

    payload = {
        "run": dict(run) if run else None,
        "actions": rows(actions),
        "audit_events": rows(audits),
        "usage_events": rows(usage),
    }
    path = out_dir / "trajectory.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def classify_paid_call_recovery(paid_call_state: str | None) -> str:
    """
    Recovery policy for external paid calls after crash.
    - not_started: may execute
    - completed: do not replay
    - completion_unknown: do NOT blind replay; mark for review
    """
    s = paid_call_state or "not_started"
    if s == "completed":
        return "skip_replay"
    if s == "completion_unknown":
        return "mark_review_no_replay"
    return "may_execute"
