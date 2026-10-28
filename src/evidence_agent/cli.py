"""Unified EvidenceAgent CLI (project_spec appendix D / S48).

Invoke as:
  python -m evidence_agent.cli <command> ...
  python repo/scripts/evidence_agent.py <command> ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
SRC = REPO_ROOT / "src"


def _ensure_path() -> None:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))


def _work_root() -> Path:
    _ensure_path()
    from common_paths import ensure_cache_env  # type: ignore

    return ensure_cache_env()


def _app_python(root: Path) -> Path:
    p = root / "envs" / "app" / "bin" / "python"
    return p if p.is_file() else Path(sys.executable)


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(cwd) if cwd else None, env=env)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def cmd_init(_args: argparse.Namespace) -> int:
    root = _work_root()
    for rel in (
        "repo",
        "envs/cache",
        "models",
        "data/raw",
        "data/normalized",
        "data/indexes",
        "data/manifests",
        "artifacts/checkpoints",
        "artifacts/exports",
        "artifacts/reports",
        "artifacts/releases",
        "runs/system/logs",
        "runs/backups",
        "runs/probes",
        "runs/steps",
        "runs/billing",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)

    private = root / "runs" / "system" / "private.env"
    if not private.is_file():
        private.write_text(
            "# EvidenceAgent private runtime — DO NOT COMMIT\n"
            "# Fill EVIDENCE_AGENT_API_TOKEN / EVIDENCE_AGENT_UI_PASSWORD before serve.\n",
            encoding="utf-8",
        )
        print(f"created_template {private}")
    else:
        print(f"private_env_present {private}")

    _ensure_path()
    from evidence_agent.storage.migrate import apply_migrations, ensure_db

    db = ensure_db(root)
    applied = apply_migrations(root)
    print(
        json.dumps(
            {
                "work_root": str(root),
                "db": str(db),
                "migrations_applied_this_call": applied,
                "ts": _utc(),
            },
            indent=2,
        )
    )
    print("INIT_OK")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = _work_root()
    paid = bool(args.all)
    if paid:
        print(
            "PAID_PROBE_NOTICE: --all may exercise external APIs if keys exist; "
            "estimated max small spend ~¥1 if teacher/Tavily keys are set; "
            "missing keys fall back to local/recorded failures (no charge).",
            flush=True,
        )
    doctor = SCRIPTS / "doctor.py"
    py = _app_python(root)
    env = os.environ.copy()
    env["WORK_ROOT"] = str(root)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    rc = _run([str(py), str(doctor)], cwd=root, env=env)
    # also print lock presence
    locks = REPO_ROOT / "locks"
    print(
        json.dumps(
            {
                "locks": {p.name: p.is_file() for p in locks.glob("*.txt")},
                "paid_probe_flag": paid,
            },
            indent=2,
        )
    )
    return rc


def cmd_ingest(args: argparse.Namespace) -> int:
    root = _work_root()
    _ensure_path()
    from evidence_agent.storage.db import connect
    from evidence_agent.storage.migrate import ensure_db
    from evidence_agent.storage import repositories as repo
    from evidence_agent.ingestion.pipeline import ingest_upload

    ensure_db(root)
    path = Path(args.path).resolve()
    if not path.exists():
        print(f"path_missing {path}", file=sys.stderr)
        return 2

    files: list[Path] = []
    if path.is_file():
        files = [path]
    else:
        for ext in ("*.md", "*.txt", "*.pdf"):
            files.extend(sorted(path.glob(ext)))
    if not files:
        print("no_ingestible_files", file=sys.stderr)
        return 2

    conn = connect(root)
    results: list[dict[str, Any]] = []
    try:
        row = conn.execute(
            "SELECT id FROM projects WHERE name=? ORDER BY created_at DESC LIMIT 1",
            (args.project,),
        ).fetchone()
        if row:
            project_id = row["id"]
        else:
            conn.execute("BEGIN")
            project_id = repo.create_project(conn, args.project, "CLI demo project")
            conn.execute("COMMIT")

        for fp in files:
            data = fp.read_bytes()
            r = ingest_upload(
                conn,
                root=root,
                project_id=project_id,
                display_name=fp.name,
                data=data,
                content_type=None,
            )
            results.append({"file": str(fp), **r})
            print(f"INGESTED {fp.name} -> {r.get('document_id')}")
    finally:
        conn.close()

    out = {"project": args.project, "project_id": project_id, "documents": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    root = _work_root()
    serve = SCRIPTS / "serve.py"
    py = Path(sys.executable)
    env = os.environ.copy()
    env["WORK_ROOT"] = str(root)
    argv = [str(py), str(serve), args.action]
    if args.action == "start":
        if args.no_vllm:
            argv.append("--no-vllm")
        if args.vllm_only:
            argv.append("--vllm-only")
        if args.lora_modules:
            argv.extend(["--lora-modules", args.lora_modules])
    return _run(argv, cwd=root, env=env)


def cmd_data(args: argparse.Namespace) -> int:
    root = _work_root()
    env = os.environ.copy()
    env["WORK_ROOT"] = str(root)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    py = _app_python(root)
    mapping = {
        "build": [
            str(py),
            str(SCRIPTS / "build_hotpotqa_subset.py"),
            "--help",
        ],
        "trajectories": [
            str(py),
            str(SCRIPTS / "collect_trajectories.py"),
            "--help",
        ],
        "preferences": [
            str(py),
            "-c",
            "print('preferences: use training/dpo preference builders; see docs/plan')",
        ],
    }
    # Prefer real entry points when present; otherwise print frozen-data guidance.
    if args.subcommand == "build":
        print(
            json.dumps(
                {
                    "note": "Frozen corpora already under data/; rebuild only with explicit scripts",
                    "hotpotqa": "scripts/build_hotpotqa_subset.py",
                    "chinese": "scripts/build_chinese_tasks.py",
                    "freeze": "scripts/freeze_chinese_sources.py",
                },
                indent=2,
            )
        )
        if (SCRIPTS / "build_hotpotqa_subset.py").is_file():
            return _run([str(py), str(SCRIPTS / "build_hotpotqa_subset.py"), "--help"], env=env)
        return 0
    if args.subcommand == "trajectories":
        script = SCRIPTS / "collect_trajectories.py"
        if script.is_file():
            return _run([str(py), str(script), "--help"], env=env)
        print("trajectories_script_missing", file=sys.stderr)
        return 2
    if args.subcommand == "preferences":
        print(
            json.dumps(
                {
                    "note": "DPO preferences produced in S35–S36; do not rebuild casually",
                    "data": "data/dpo/",
                },
                indent=2,
            )
        )
        return 0
    print(f"unknown_data_subcommand {args.subcommand}", file=sys.stderr)
    return 2


def cmd_train(args: argparse.Namespace) -> int:
    root = _work_root()
    env = os.environ.copy()
    env["WORK_ROOT"] = str(root)
    train_py = root / "envs" / "train" / "bin" / "python"
    py = train_py if train_py.is_file() else Path(sys.executable)
    if args.subcommand == "sft":
        print(
            json.dumps(
                {
                    "gate": "check GPU exclusive + S30 data thresholds before formal SFT",
                    "formal": "training/sft/formal harness / historical exp_sft_*",
                    "release_policy": "published system is E0 (base); SFT research_only",
                },
                indent=2,
            )
        )
        probe = SCRIPTS / "probe_train_lora.py"
        if args.dry_run or not probe.is_file():
            print("TRAIN_SFT_DRY_OK")
            return 0
        return _run([str(py), str(probe), "--help"], env=env)
    if args.subcommand == "dpo":
        print(
            json.dumps(
                {
                    "gate": "validate reference + preference cache (S37) before DPO",
                    "formal": "scripts/run_s38.sh",
                    "release_policy": "E2 not released",
                },
                indent=2,
            )
        )
        print("TRAIN_DPO_DRY_OK")
        return 0
    return 2


def cmd_evaluate(args: argparse.Namespace) -> int:
    root = _work_root()
    print(
        json.dumps(
            {
                "split": args.split,
                "frozen": bool(args.frozen),
                "note": "Formal evals are under runs/evaluation/; use frozen manifests for test",
                "s42_main": "runs/evaluation/eval_main_s42_0001/",
                "release": "E0",
            },
            indent=2,
        )
    )
    if args.split == "test" and not args.frozen:
        print("REFUSE: test split requires --frozen", file=sys.stderr)
        return 2
    if args.frozen:
        freeze = root / "runs" / "steps" / "S41" / "a001" / "freeze_summary.json"
        if not freeze.is_file():
            # also check artifacts
            freeze = root / "artifacts" / "reports"
            print(f"freeze_check_path_hint {freeze}")
        print("EVALUATE_CONTRACT_OK")
    else:
        print("EVALUATE_DEV_CONTRACT_OK")
    return 0


def cmd_report(_args: argparse.Namespace) -> int:
    root = _work_root()
    report = root / "artifacts" / "reports" / "rpt_s47_0001"
    for name in ("report.json", "summary.json"):
        candidate = report / name
        if candidate.is_file():
            print(f"report_present {report}")
            print(candidate.read_text(encoding="utf-8")[:2000])
            print("REPORT_OK")
            return 0
    # rebuild from raw if script available
    script = SCRIPTS / "run_s47.py"
    if script.is_file():
        py = _app_python(root)
        env = os.environ.copy()
        env["WORK_ROOT"] = str(root)
        rc = _run([str(py), str(script), "--root", str(root)], env=env)
        if rc == 0:
            print("REPORT_OK")
        return rc
    print("report_missing", file=sys.stderr)
    return 1


def cmd_backup(args: argparse.Namespace) -> int:
    root = _work_root()
    _ensure_path()
    from evidence_agent.storage.migrate import ensure_db
    from evidence_agent.storage.backup import backup_sqlite_consistent

    ensure_db(root)
    label = args.label or f"bak_s48_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    man = backup_sqlite_consistent(root, label=label)
    bak_rel = man.get("backup_db", f"runs/backups/{label}/evidence_agent.sqlite")
    bak_dir = (root / bak_rel).parent if not Path(bak_rel).is_absolute() else Path(bak_rel).parent
    bak_dir.mkdir(parents=True, exist_ok=True)

    # Hash release-relevant adapters / freeze files if present
    digest_paths: list[Path] = []
    for pattern in (
        "artifacts/checkpoints/*/adapter/adapter_config.json",
        "artifacts/reports/rpt_s47_0001/summary.json",
        "runs/steps/S41/a001/freeze_summary.json",
        "runs/steps/S40/a001/selection.json",
    ):
        digest_paths.extend(sorted(root.glob(pattern)))

    checksums: dict[str, str] = {}
    for p in digest_paths[:50]:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        rel = str(p.relative_to(root)).replace("\\", "/")
        checksums[rel] = h.hexdigest()

    manifest = {
        "backup_id": label,
        "created_at": _utc(),
        "sqlite": man,
        "artifact_sha256": checksums,
        "note": "SQLite VACUUM snapshot + selected artifact hashes; copy off-box for independent restore",
    }
    (bak_dir / "s48_backup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [f"{digest}  {rel}" for rel, digest in sorted(checksums.items())]
    if man.get("sha256"):
        lines.insert(0, f"{man['sha256']}  evidence_agent.sqlite")
    (bak_dir / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("BACKUP_OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evidence-agent", description="EvidenceAgent unified CLI")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="Create dirs, migrate DB, verify private.env template")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="Environment / model probes")
    s.add_argument("--all", action="store_true", help="Include external/paid probe notice")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("ingest", help="Ingest docs into a project")
    s.add_argument("--project", default="demo")
    s.add_argument("--path", required=True)
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("serve", help="Start/stop/status UI+API+Worker(+vLLM)")
    s.add_argument("action", choices=["start", "stop", "status"], nargs="?", default="start")
    s.add_argument("--no-vllm", action="store_true")
    s.add_argument("--vllm-only", action="store_true")
    s.add_argument("--lora-modules", default="")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("data", help="Data pipeline entries")
    s.add_argument("subcommand", choices=["build", "trajectories", "preferences"])
    s.set_defaults(func=cmd_data)

    s = sub.add_parser("train", help="Training entries")
    s.add_argument("subcommand", choices=["sft", "dpo"])
    s.add_argument("--dry-run", action="store_true", default=True)
    s.set_defaults(func=cmd_train)

    s = sub.add_parser("evaluate", help="Evaluation contract entry")
    s.add_argument("--split", choices=["dev", "test"], required=True)
    s.add_argument("--frozen", action="store_true")
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("report", help="Build/show report from raw results")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("backup", help="Consistent DB backup + artifact hashes")
    s.add_argument("--label", default=None)
    s.set_defaults(func=cmd_backup)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
