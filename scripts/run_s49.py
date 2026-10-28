#!/usr/bin/env python3
"""S49: assemble delivery package, checksums, acceptance evidence."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _work_root() -> Path:
    env = os.environ.get("WORK_ROOT")
    if env:
        return Path(env)
    # repo/scripts/run_s49.py → WORK_ROOT
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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


REQUIRED_REPO_FILES = [
    "README.md",
    "docs/models/base_model_card.md",
    "docs/models/sft_model_card.md",
    "docs/models/dpo_model_card.md",
    "docs/data/data_card.md",
    "docs/data/chinese_sources_card.md",
    "docs/data/chinese_tasks_card.md",
    "docs/delivery/demo_script.md",
    "docs/delivery/delivery_checklist.md",
    "examples/docs/demo_traceable.md",
    "examples/requests/demo_smoke.sh",
    "examples/requests/ask.json",
    "examples/outputs/sample_export/answer.json",
    "examples/outputs/sample_export/citations.json",
    "examples/outputs/sample_export/report.md",
    "artifacts/artifact_index.json",
]


def main() -> int:
    wr = _work_root()
    # Prefer WORK_ROOT/repo layout
    repo = wr / "repo" if (wr / "repo").is_dir() else Path(__file__).resolve().parents[1]
    if not (repo / "README.md").is_file():
        print(f"ERROR: cannot find repo at {repo}")
        return 2

    release_id = "rel_s49_e0_0001"
    release_dir = wr / "artifacts" / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    demo_dir = release_dir / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for rel in REQUIRED_REPO_FILES:
        p = repo / rel
        ok = p.is_file() and p.stat().st_size > 0
        sha = _sha256_file(p) if ok else None
        checks.append({"id": f"repo:{rel}", "path": str(p), "pass": ok, "sha256": sha})
        if ok and sha:
            checksum_lines.append(f"{sha}  repo/{rel}")

    # Report + S48 acceptance (outside repo tree under WORK_ROOT)
    external = {
        "report_md": wr / "artifacts" / "reports" / "rpt_s47_0001" / "report.md",
        "s48_acceptance": wr / "runs" / "steps" / "S48" / "a001" / "acceptance.md",
        "sft_adapter_cfg": wr / "artifacts" / "adapters" / "sft" / "exp_sft_0001" / "adapter_config.json",
        "dpo_adapter_cfg": wr / "artifacts" / "adapters" / "dpo" / "exp_dpo_0001" / "adapter_config.json",
    }
    for kid, p in external.items():
        ok = p.is_file()
        sha = _sha256_file(p) if ok else None
        # adapters optional for public pack but required for COND note
        required = kid in ("report_md", "s48_acceptance")
        checks.append(
            {
                "id": kid,
                "path": str(p),
                "pass": ok if required else True,
                "present": ok,
                "sha256": sha,
                "required": required,
            }
        )
        if ok and sha:
            try:
                rel = p.relative_to(wr).as_posix()
            except ValueError:
                rel = str(p)
            checksum_lines.append(f"{sha}  {rel}")

    # Copy public demo pointers (text only) into release/demo
    for name in ("demo_script.md", "delivery_checklist.md"):
        src = repo / "docs" / "delivery" / name
        dst = demo_dir / name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            checksum_lines.append(f"{_sha256_file(dst)}  artifacts/releases/{release_id}/demo/{name}")

    # Public boundary: no PEM private keys in docs/examples
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

    required_ids = {c["id"] for c in checks if c["id"].startswith("repo:")} | {
        "report_md",
        "s48_acceptance",
        "no_pem_in_public_docs_examples",
    }
    required_pass = all(c["pass"] for c in checks if c["id"] in required_ids)

    manifest = {
        "release_id": release_id,
        "created_at": _utc(),
        "release_system": "e0",
        "public_hosting": "NOT_PROVIDED",
        "report": "artifacts/reports/rpt_s47_0001",
        "s48": "runs/steps/S48/a001",
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
        f"{_sha256_file(release_dir / 'release_manifest.json')}  artifacts/releases/{release_id}/release_manifest.json"
    )

    # Copy checklist into release root
    cl = repo / "docs" / "delivery" / "delivery_checklist.md"
    if cl.is_file():
        (release_dir / "delivery_checklist.md").write_text(cl.read_text(encoding="utf-8"), encoding="utf-8")
        checksum_lines.append(
            f"{_sha256_file(release_dir / 'delivery_checklist.md')}  artifacts/releases/{release_id}/delivery_checklist.md"
        )

    checksums_path = release_dir / "checksums.sha256"
    checksums_path.write_text("\n".join(sorted(set(checksum_lines))) + "\n", encoding="utf-8")

    # Update artifact_index entry
    idx_path = repo / "artifacts" / "artifact_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    entries = [e for e in idx.get("entries", []) if e.get("id") != release_id]
    entries.append(
        {
            "id": release_id,
            "kind": "release",
            "role": "delivery_s49",
            "path": f"artifacts/releases/{release_id}/",
            "release_system": "e0",
            "public_hosting": "NOT_PROVIDED",
            "checksums": f"artifacts/releases/{release_id}/checksums.sha256",
        }
    )
    idx["entries"] = entries
    idx["updated"] = _utc()
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Acceptance under WORK_ROOT/runs/steps/S49/a001
    step_dir = wr / "runs" / "steps" / "S49" / "a001"
    step_dir.mkdir(parents=True, exist_ok=True)
    acceptance = {
        "step": "S49",
        "attempt": "a001",
        "result": "PASS" if required_pass else "FAIL",
        "release_id": release_id,
        "created_at": _utc(),
        "public_hosting": "NOT_PROVIDED",
        "release_system": "e0",
        "checks": checks,
        "release_dir": str(release_dir),
    }
    (step_dir / "acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# S49 a001",
        "",
        f"- result: **{'PASS' if required_pass else 'FAIL'}**",
        f"- release_id: `{release_id}`",
        f"- release_system: e0",
        f"- public_hosting: NOT_PROVIDED",
        f"- release_dir: `artifacts/releases/{release_id}/`",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for c in checks:
        mark = "PASS" if c.get("pass") else "FAIL"
        if c.get("required") is False and not c.get("present", True):
            mark = "COND_MISSING"
        lines.append(f"| {c['id']} | {mark} |")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Adapters remain research / not-released; public pack indexes hashes, does not claim full open weights redistribution.",
            "- Blind keys and private.env stay private.",
            "- Demo is callable via tunnel; screenshots are not a substitute.",
            "",
        ]
    )
    (step_dir / "acceptance.md").write_text("\n".join(lines), encoding="utf-8")
    (step_dir / "evidence_index.json").write_text(
        json.dumps(
            {
                "acceptance": "acceptance.md",
                "acceptance_json": "acceptance.json",
                "release": f"artifacts/releases/{release_id}/",
                "checksums": f"artifacts/releases/{release_id}/checksums.sha256",
                "checklist": "repo/docs/delivery/delivery_checklist.md",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(json.dumps({"result": acceptance["result"], "release_id": release_id, "step_dir": str(step_dir)}, indent=2))
    return 0 if required_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
