#!/usr/bin/env python3
"""CLI: consistent SQLite backup / restore check (S21)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evidence_agent.storage.backup import backup_sqlite_consistent, restore_sqlite_from_backup
from evidence_agent.storage.db import db_path, work_root
from evidence_agent.storage.migrate import ensure_db


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EvidenceAgent DB backup/restore")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="VACUUM INTO consistent snapshot")
    b.add_argument("--label", default=None)
    r = sub.add_parser("restore-check", help="Restore snapshot to a temp path and verify")
    r.add_argument("--backup-db", required=True, type=Path)
    r.add_argument("--target", type=Path, default=None)
    args = p.parse_args(argv)

    root = work_root()
    ensure_db(root)
    if args.cmd == "backup":
        man = backup_sqlite_consistent(root, label=args.label)
        print(json.dumps(man, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "restore-check":
        target = args.target or (root / "runs" / "backups" / "_restore_check" / "evidence_agent.sqlite")
        info = restore_sqlite_from_backup(args.backup_db, target_db=target)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("tables", 0) > 0 else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
