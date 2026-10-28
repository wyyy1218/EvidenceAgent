#!/usr/bin/env python3
"""S50: completion levels, release manifest, interview notes, acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _work_root() -> Path:
    env = os.environ.get("WORK_ROOT")
    if env:
        return Path(env)
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "repo").is_dir():
        return candidate
    return Path("/root/autodl-tmp/evidence-agent")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


REQUIRED_REPO_FILES = [
    "README.md",
    "LICENSE",
    "docs/models/base_model_card.md",
    "docs/models/sft_model_card.md",
    "docs/models/dpo_model_card.md",
    "docs/data/data_card.md",
    "docs/delivery/demo_script.md",
    "docs/delivery/delivery_checklist.md",
    "docs/delivery/completion_levels.md",
    "docs/delivery/interview_notes.md",
    "docs/plan/progress.md",
    "examples/requests/ask.json",
    "artifacts/artifact_index.json",
]

GIT_TAG = "v1.0.0-preview"
RELEASE_ID = "rel_s50_e0_0001"


def _git_head(repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "cwd": str(repo),
        "has_commits": False,
        "commit": None,
        "tag": GIT_TAG,
        "tag_present": False,
        "remote_url": "NOT_REGISTERED",
    }
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode == 0:
            out["has_commits"] = True
            out["commit"] = head.stdout.strip()
        tag = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{GIT_TAG}"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        out["tag_present"] = tag.returncode == 0
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if remote.returncode == 0 and remote.stdout.strip():
            out["remote_url"] = remote.stdout.strip()
    except OSError as e:
        out["error"] = str(e)
    return out


def main() -> int:
    wr = _work_root()
    repo = wr / "repo" if (wr / "repo").is_dir() else Path(__file__).resolve().parents[1]
    if not (repo / "README.md").is_file():
        print(f"ERROR: cannot find repo at {repo}")
        return 2

    release_dir = wr / "artifacts" / "releases" / RELEASE_ID
    release_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = release_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for rel in REQUIRED_REPO_FILES:
        p = repo / rel
        ok = p.is_file() and p.stat().st_size > 0
        sha = _sha256_file(p) if ok else None
        checks.append({"id": f"repo:{rel}", "path": str(p), "pass": ok, "sha256": sha})
        if ok and sha:
            checksum_lines.append(f"{sha}  repo/{rel}")

    external = {
        "report_md": wr / "artifacts" / "reports" / "rpt_s47_0001" / "report.md",
        "s48_acceptance": wr / "runs" / "steps" / "S48" / "a001" / "acceptance.md",
        "s49_acceptance": wr / "runs" / "steps" / "S49" / "a001" / "acceptance.md",
        "s49_manifest": wr / "artifacts" / "releases" / "rel_s49_e0_0001" / "release_manifest.json",
        "s34_acceptance": wr / "runs" / "steps" / "S34" / "a001" / "acceptance.md",
        "s40_acceptance": wr / "runs" / "steps" / "S40" / "a001" / "acceptance.md",
        "s42_acceptance": wr / "runs" / "steps" / "S42" / "a001" / "acceptance.md",
    }
    for kid, p in external.items():
        ok = p.is_file() and p.stat().st_size > 0
        sha = _sha256_file(p) if ok else None
        checks.append({"id": kid, "path": str(p), "pass": ok, "sha256": sha, "required": True})
        if ok and sha:
            try:
                rel = p.relative_to(wr).as_posix()
            except ValueError:
                rel = str(p)
            checksum_lines.append(f"{sha}  {rel}")

    # Copy S50 docs into release
    for name in (
        "completion_levels.md",
        "interview_notes.md",
        "delivery_checklist.md",
        "demo_script.md",
    ):
        src = repo / "docs" / "delivery" / name
        dst = docs_dir / name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            checksum_lines.append(
                f"{_sha256_file(dst)}  artifacts/releases/{RELEASE_ID}/docs/{name}"
            )

    # Completion level consistency spot-checks (text presence, not prose quality)
    cl = (repo / "docs" / "delivery" / "completion_levels.md").read_text(encoding="utf-8")
    notes = (repo / "docs" / "delivery" / "interview_notes.md").read_text(encoding="utf-8")
    level_checks = [
        ("levels_mention_e0", "e0" in cl.lower() or "**E0**" in cl or "E0" in cl),
        ("levels_preview_tag", GIT_TAG in cl),
        ("levels_dpo_partial", "315" in cl and "600" in cl),
        ("levels_hosting_not_provided", "NOT_PROVIDED" in cl),
        ("interview_binds_report", "rpt_s47_0001" in notes),
        ("interview_binds_sft_card", "sft_model_card" in notes),
        ("interview_no_false_scale", "600/100" in notes and "不可写" in notes),
    ]
    for cid, ok in level_checks:
        checks.append({"id": cid, "pass": bool(ok)})

    pem_hits: list[str] = []
    for p in list((repo / "docs").rglob("*")) + list((repo / "examples").rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".safetensors", ".bin", ".pt", ".gguf"}:
            continue
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "BEGIN OPENSSH PRIVATE KEY" in raw or "BEGIN RSA PRIVATE KEY" in raw:
            pem_hits.append(str(p))
    checks.append({"id": "no_pem_in_public_docs_examples", "pass": len(pem_hits) == 0, "hits": pem_hits})

    git_info = _git_head(repo)
    # Tag may be created after this script; record state honestly.
    checks.append(
        {
            "id": "git_tag_planned",
            "pass": True,
            "tag": GIT_TAG,
            "tag_present_at_run": git_info["tag_present"],
            "commit_at_run": git_info["commit"],
            "remote_url": git_info["remote_url"],
        }
    )

    required_ids = {c["id"] for c in checks if c["id"].startswith("repo:")} | {
        "report_md",
        "s48_acceptance",
        "s49_acceptance",
        "s49_manifest",
        "s34_acceptance",
        "s40_acceptance",
        "s42_acceptance",
        "no_pem_in_public_docs_examples",
    } | {cid for cid, _ in level_checks}
    required_pass = all(c["pass"] for c in checks if c["id"] in required_ids)

    completion = {
        "product_usable": "YES",
        "sft_experiment_complete": "YES",
        "dpo_experiment_complete": "YES",
        "target_data_scale_complete": "PARTIAL",
        "full_evaluation_complete": "YES",
        "full_delivery_complete": "YES_WITH_CLEAR_CONDITIONS",
        "training_path_degraded_delivery": True,
        "release_system": "e0",
        "git_tag": GIT_TAG,
        "public_hosting": "NOT_PROVIDED",
        "notes": [
            "DPO preference scale 315/89 != target 600/100",
            "E1/E2 not selected for product release",
            "Public hosting not provided",
        ],
    }

    manifest = {
        "release_id": RELEASE_ID,
        "created_at": _utc(),
        "release_system": "e0",
        "git_tag": GIT_TAG,
        "version_label": "preview",
        "public_hosting": "NOT_PROVIDED",
        "inherits_delivery": "rel_s49_e0_0001",
        "report": "artifacts/reports/rpt_s47_0001",
        "s48": "runs/steps/S48/a001",
        "s49": "runs/steps/S49/a001",
        "completion_levels": "repo/docs/delivery/completion_levels.md",
        "interview_notes": "repo/docs/delivery/interview_notes.md",
        "license": "repo/LICENSE",
        "git": git_info,
        "completion": completion,
        "docs": {
            "readme": "repo/README.md",
            "data_cards": "repo/docs/data/",
            "model_cards": "repo/docs/models/",
            "delivery": "repo/docs/delivery/",
            "demo": "repo/examples/",
        },
        "adapters": {
            "sft": {
                "path": "artifacts/adapters/sft/exp_sft_0001/",
                "status": "research_only",
                "sha256_adapter_model": "4e8b60a07b8d65f7e66fb547a71d1658bfb94531d4e0c0156589e748fe6391ce",
            },
            "dpo": {
                "path": "artifacts/adapters/dpo/exp_dpo_0001/",
                "status": "evaluated_not_released",
                "sha256_adapter_model": "011f3c14544ebb96762b6c77a818b5b6fd44d2ea670772630608836d8849ecbc",
                "meets_target_scale": False,
            },
        },
        "known_issues": completion["notes"],
        "access": {
            "personal": "SSH tunnel to UI:6006 API:6008; see docs/operations/access.md",
            "public_hosting": "NOT_PROVIDED",
        },
        "private_excluded": [
            "runs/system/private.env",
            "private/blinding_key.json",
            "SSH identity files",
            "full raw evaluation jsonl (default)",
        ],
        "checks_summary": {
            "n": len(checks),
            "all_required_pass": required_pass,
        },
    }

    (release_dir / "release_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checksum_lines.append(
        f"{_sha256_file(release_dir / 'release_manifest.json')}  artifacts/releases/{RELEASE_ID}/release_manifest.json"
    )

    cl_src = repo / "docs" / "delivery" / "delivery_checklist.md"
    if cl_src.is_file():
        (release_dir / "delivery_checklist.md").write_text(
            cl_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
        checksum_lines.append(
            f"{_sha256_file(release_dir / 'delivery_checklist.md')}  artifacts/releases/{RELEASE_ID}/delivery_checklist.md"
        )

    checksums_path = release_dir / "checksums.sha256"
    checksums_path.write_text("\n".join(sorted(set(checksum_lines))) + "\n", encoding="utf-8")

    idx_path = repo / "artifacts" / "artifact_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    entries = [e for e in idx.get("entries", []) if e.get("id") != RELEASE_ID]
    entries.append(
        {
            "id": RELEASE_ID,
            "kind": "release",
            "role": "completion_s50",
            "path": f"artifacts/releases/{RELEASE_ID}/",
            "release_system": "e0",
            "git_tag": GIT_TAG,
            "public_hosting": "NOT_PROVIDED",
            "checksums": f"artifacts/releases/{RELEASE_ID}/checksums.sha256",
        }
    )
    idx["entries"] = entries
    idx["updated"] = _utc()
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    step_dir = wr / "runs" / "steps" / "S50" / "a001"
    step_dir.mkdir(parents=True, exist_ok=True)
    acceptance = {
        "step": "S50",
        "attempt": "a001",
        "result": "PASS" if required_pass else "FAIL",
        "release_id": RELEASE_ID,
        "git_tag": GIT_TAG,
        "created_at": _utc(),
        "public_hosting": "NOT_PROVIDED",
        "release_system": "e0",
        "completion": completion,
        "git": git_info,
        "checks": checks,
        "release_dir": str(release_dir),
    }
    (step_dir / "acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# S50 a001",
        "",
        f"- result: **{'PASS' if required_pass else 'FAIL'}**",
        f"- release_id: `{RELEASE_ID}`",
        f"- git_tag: `{GIT_TAG}`",
        f"- release_system: e0",
        f"- public_hosting: NOT_PROVIDED",
        f"- release_dir: `artifacts/releases/{RELEASE_ID}/`",
        "",
        "## Completion",
        "",
        "| Level | Status |",
        "| --- | --- |",
    ]
    for k, v in completion.items():
        if k == "notes":
            continue
        lines.append(f"| {k} | {v} |")
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Result |",
            "| --- | --- |",
        ]
    )
    for c in checks:
        mark = "PASS" if c.get("pass") else "FAIL"
        lines.append(f"| {c['id']} | {mark} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Version is **preview**: DPO target scale unmet; no public hosting; E1/E2 not released.",
            "- Git remote URL may remain NOT_REGISTERED; local tag is the release pointer.",
            "- Interview notes bind claims to real paths; do not invent metrics.",
            "",
        ]
    )
    (step_dir / "acceptance.md").write_text("\n".join(lines), encoding="utf-8")
    (step_dir / "evidence_index.json").write_text(
        json.dumps(
            {
                "acceptance": "acceptance.md",
                "acceptance_json": "acceptance.json",
                "release": f"artifacts/releases/{RELEASE_ID}/",
                "checksums": f"artifacts/releases/{RELEASE_ID}/checksums.sha256",
                "completion_levels": "repo/docs/delivery/completion_levels.md",
                "interview_notes": "repo/docs/delivery/interview_notes.md",
                "git_tag": GIT_TAG,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "result": acceptance["result"],
                "release_id": RELEASE_ID,
                "git_tag": GIT_TAG,
                "git": git_info,
                "step_dir": str(step_dir),
            },
            indent=2,
        )
    )
    return 0 if required_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
