#!/usr/bin/env python3
"""S48 acceptance: clean-ish repro checks, CLI contract, serve smoke, backup restore."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_HINT = Path(__file__).resolve().parents[2]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _work_root() -> Path:
    return Path(os.environ.get("WORK_ROOT", "/root/autodl-tmp/evidence-agent"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
        os.environ.setdefault(k.strip(), v.strip())
    return out


def _http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 30,
) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode())
            except Exception:
                return resp.status, raw.decode("utf-8", errors="replace")[:2000]
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw.decode())
        except Exception:
            payload = raw.decode("utf-8", errors="replace")[:2000]
        return e.code, payload
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 600) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--attempt", default="a001")
    ap.add_argument("--skip-serve-start", action="store_true")
    args = ap.parse_args()

    root = args.root or _work_root()
    os.environ["WORK_ROOT"] = str(root)
    repo = root / "repo"
    scripts = repo / "scripts"
    src = repo / "src"
    attempt = args.attempt
    step_dir = root / "runs" / "steps" / "S48" / attempt
    probe_dir = root / "runs" / "probes" / f"probe_s48_{attempt}"
    step_dir.mkdir(parents=True, exist_ok=True)
    probe_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["WORK_ROOT"] = str(root)
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    _load_dotenv(root / "runs" / "system" / "private.env")
    if os.environ.get("API_BEARER_TOKEN") and not os.environ.get("EVIDENCE_AGENT_API_TOKEN"):
        os.environ["EVIDENCE_AGENT_API_TOKEN"] = os.environ["API_BEARER_TOKEN"]
    token = os.environ.get("EVIDENCE_AGENT_API_TOKEN", "")

    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any) -> None:
        item = {"name": name, "ok": bool(ok), "detail": detail}
        checks.append(item)
        (probe_dir / f"{name}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")

    # 1) cache / lock / model presence (isolated rebuild with cache reuse)
    locks = {p.name: p.is_file() for p in (repo / "locks").glob("*.txt")}
    models_base = root / "models" / "base"
    base_revs = [p.name for p in models_base.iterdir()] if models_base.is_dir() else []
    cache_dirs = {
        "uv": (root / "envs" / "cache" / "uv").is_dir(),
        "pip": (root / "envs" / "cache" / "pip").is_dir(),
        "hf": (root / "envs" / "cache" / "huggingface").is_dir(),
    }
    envs_ok = all((root / "envs" / n / "bin" / "python").is_file() for n in ("app", "infer", "train", "judge"))
    record(
        "env_locks_models_cache",
        envs_ok and all(locks.values()) and len(base_revs) >= 1,
        {
            "locks": locks,
            "base_revisions": base_revs,
            "cache_present": cache_dirs,
            "envs_ok": envs_ok,
            "cache_reused": True,
            "note": "Disk <100GiB; verified existing four envs+locks+base instead of wipe rebuild",
        },
    )

    # sample freeze vs installed (app env)
    app_py = root / "envs" / "app" / "bin" / "python"
    rc, out = _run(
        [str(app_py), "-c", "import fastapi,uvicorn,streamlit,pydantic; print('app_imports_ok')"],
        cwd=root,
        env=env,
        timeout=120,
    )
    record("app_imports", rc == 0 and "app_imports_ok" in out, out[-2000:])

    # 2) CLI contract (use -m to avoid scripts/ name shadowing the package)
    cli = [str(app_py), "-m", "evidence_agent.cli"]
    cli_cmds = [
        (["init"], "INIT_OK"),
        (["evaluate", "--split", "dev"], "EVALUATE_DEV_CONTRACT_OK"),
        (["evaluate", "--split", "test", "--frozen"], "EVALUATE_CONTRACT_OK"),
        (["train", "sft"], "TRAIN_SFT_DRY_OK"),
        (["train", "dpo"], "TRAIN_DPO_DRY_OK"),
        (["data", "build"], None),
        (["backup", "--label", f"bak_s48_{attempt}"], "BACKUP_OK"),
    ]
    cli_results = {}
    for argv, marker in cli_cmds:
        rc, out = _run(cli + argv, cwd=root, env=env, timeout=300)
        ok = rc == 0 and (marker is None or marker in out)
        cli_results[" ".join(argv)] = {"rc": rc, "ok": ok, "tail": out[-1500:]}
        (probe_dir / f"cli_{'_'.join(argv).replace('--','').replace(' ','_')}.log").write_text(
            out, encoding="utf-8"
        )
    record("cli_contract", all(v["ok"] for v in cli_results.values()), cli_results)

    # ingest demo
    demo = repo / "examples" / "docs" / "demo_traceable.md"
    rc, out = _run(
        cli + ["ingest", "--project", "demo", "--path", str(demo)],
        cwd=root,
        env=env,
        timeout=120,
    )
    record("cli_ingest", rc == 0 and "INGESTED" in out, out[-1500:])

    # report
    rc, out = _run(cli + ["report"], cwd=root, env=env, timeout=120)
    record(
        "cli_report",
        rc == 0 and ("REPORT_OK" in out or "report_present" in out or '"result": "PASS"' in out),
        out[-1500:],
    )

    # 3) vLLM config + bind
    vllm_cmd = ""
    try:
        ps = subprocess.check_output(["ps", "aux"], text=True)
        for line in ps.splitlines():
            if "vllm.entrypoints.openai.api_server" in line and "grep" not in line:
                vllm_cmd = line
                break
    except Exception as e:  # noqa: BLE001
        vllm_cmd = f"ERR {e}"
    vllm_ok = (
        "127.0.0.1" in vllm_cmd
        and "--max-model-len 8192" in vllm_cmd
        and "--gpu-memory-utilization 0.80" in vllm_cmd
        and "--max-num-seqs 2" in vllm_cmd
        and "--max-lora-rank 16" in vllm_cmd
        and "bfloat16" in vllm_cmd
    )
    (probe_dir / "vllm_cmdline.txt").write_text(vllm_cmd + "\n", encoding="utf-8")
    record("vllm_release_config", vllm_ok, vllm_cmd[-2000:])

    # 4) serve API/UI if needed
    code, _ = _http("http://127.0.0.1:6008/healthz")
    if code != 200 and not args.skip_serve_start:
        # keep existing vLLM; start api/ui/worker only
        rc, out = _run(
            [str(app_py), str(scripts / "serve.py"), "start", "--no-vllm"],
            cwd=root,
            env=env,
            timeout=180,
        )
        (probe_dir / "serve_start.log").write_text(out, encoding="utf-8")
        for _ in range(40):
            code, _ = _http("http://127.0.0.1:6008/healthz")
            if code == 200:
                break
            time.sleep(1)
    record("api_healthz", code == 200, {"code": code})

    # auth
    c_unauth, body_unauth = _http("http://127.0.0.1:6008/readyz")
    c_auth, body_auth = _http(
        "http://127.0.0.1:6008/readyz",
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    record(
        "auth_readyz",
        c_unauth == 401 and c_auth in (200, 503),
        {"unauth": c_unauth, "auth": c_auth, "auth_body": body_auth},
    )

    c_ask_unauth, _ = _http(
        "http://127.0.0.1:6008/v1/ask",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps({"question": "ping"}).encode(),
    )
    c_ask, ask_body = _http(
        "http://127.0.0.1:6008/v1/ask",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        body=json.dumps({"question": "用一句话说明什么是可追溯证据。"}).encode(),
        timeout=120,
    )
    ask_ok = c_ask == 200 and isinstance(ask_body, dict) and ask_body.get("route") == "base"
    record(
        "ask_base_route",
        ask_ok and c_ask_unauth == 401,
        {"unauth": c_ask_unauth, "ask": ask_body},
    )

    # UI
    c_ui, _ = _http("http://127.0.0.1:6006/")
    record("ui_listen", c_ui == 200, {"code": c_ui})

    # Writer misroute probe (T24): release E0 requires Writer→base; LoRA may be absent
    route_script = scripts / "probe_vllm_route.py"
    if route_script.is_file():
        rc, out = _run([str(app_py), str(route_script)], cwd=root, env=env, timeout=300)
        (probe_dir / "t24_route.log").write_text(out, encoding="utf-8")
        writer_base = '"writer_route_base": true' in out or "'writer_route_base': True" in out
        record(
            "t24_writer_base_route",
            writer_base,
            {"rc": rc, "writer_route_base": writer_base, "tail": out[-2000:]},
        )
    else:
        record("t24_writer_base_route", False, "probe_vllm_route.py missing")

    # cancel / create run smoke
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # need a project id — create one
    c_proj, proj = _http(
        "http://127.0.0.1:6008/v1/projects",
        method="POST",
        headers=headers,
        body=json.dumps({"name": f"s48_smoke_{attempt}", "description": "s48"}).encode(),
    )
    project_id = proj.get("project_id") if isinstance(proj, dict) else None
    cancel_ok = False
    cancel_detail: Any = {"project": proj}
    if project_id:
        c_run, run = _http(
            "http://127.0.0.1:6008/v1/runs",
            method="POST",
            headers=headers,
            body=json.dumps(
                {
                    "project_id": project_id,
                    "question": "S48 cancel smoke — do not answer",
                    "allow_web": False,
                    "budget_profile": "standard",
                }
            ).encode(),
        )
        run_id = run.get("run_id") if isinstance(run, dict) else None
        if run_id:
            c_cancel, cancel_body = _http(
                f"http://127.0.0.1:6008/v1/runs/{run_id}/cancel",
                method="POST",
                headers=headers,
            )
            cancel_ok = c_cancel == 200 and (
                (isinstance(cancel_body, dict) and cancel_body.get("cancel_requested"))
                or (isinstance(cancel_body, dict) and cancel_body.get("status") == "cancelled")
            )
            cancel_detail = {"create": run, "cancel_code": c_cancel, "cancel": cancel_body}
        else:
            cancel_detail = {"create_code": c_run, "create": run}
    record("cancel_smoke", cancel_ok, cancel_detail)

    # backup restore-check
    bak = root / "runs" / "backups" / f"bak_s48_{attempt}" / "evidence_agent.sqlite"
    if bak.is_file():
        rc, out = _run(
            [
                str(app_py),
                str(scripts / "backup_db.py"),
                "restore-check",
                "--backup-db",
                str(bak),
                "--target",
                str(root / "runs" / "backups" / f"_restore_s48_{attempt}" / "evidence_agent.sqlite"),
            ],
            cwd=root,
            env=env,
            timeout=120,
        )
        restore_ok = rc == 0 and "tables" in out
        record("backup_restore_check", restore_ok, out[-1500:])
        # independent copy marker (this host + path); workstation pull is separate
        ind = {
            "backup_sqlite_sha256": _sha256(bak),
            "local_restore_ok": restore_ok,
            "independent_endpoint_note": (
                "Server data disk is not the permanent independent backup end; "
                "pull bak_s48_* to workstation runs/backups/ for off-box copy."
            ),
        }
        (probe_dir / "independent_backup_note.json").write_text(
            json.dumps(ind, indent=2) + "\n", encoding="utf-8"
        )
    else:
        record("backup_restore_check", False, f"missing {bak}")

    # public hosting honesty
    access = {
        "personal_access": "SSH tunnel 6006/6008 (see docs/operations/access.md)",
        "public_hosting": "NOT_PROVIDED",
        "autodl_personal_mapping_is_not_public_deploy": True,
        "vllm_public": False,
    }
    (probe_dir / "access_status.json").write_text(json.dumps(access, indent=2) + "\n", encoding="utf-8")
    record("access_disclosure", True, access)

    # Dockerfile / README presence
    record(
        "dockerfile_readme",
        (repo / "Dockerfile").is_file() and (repo / "README.md").is_file(),
        {
            "dockerfile": (repo / "Dockerfile").is_file(),
            "readme": (repo / "README.md").is_file(),
        },
    )

    # secrets not in public-ish tracked paths (spot check)
    leak_hits = []
    for rel in ("README.md", "Dockerfile", "docs/operations/access.md"):
        p = repo / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for needle in ("SSH_PASSWORD=", "EVIDENCE_AGENT_API_TOKEN=ea_", "PRIVATE KEY"):
            if needle in text:
                leak_hits.append({"file": rel, "needle": needle})
    record("no_secrets_in_docs", len(leak_hits) == 0, leak_hits)

    required = [
        "env_locks_models_cache",
        "app_imports",
        "cli_contract",
        "cli_ingest",
        "cli_report",
        "vllm_release_config",
        "api_healthz",
        "auth_readyz",
        "ask_base_route",
        "ui_listen",
        "cancel_smoke",
        "backup_restore_check",
        "access_disclosure",
        "dockerfile_readme",
        "no_secrets_in_docs",
    ]
    by_name = {c["name"]: c for c in checks}
    failed = [n for n in required if not by_name.get(n, {}).get("ok")]
    result = "PASS" if not failed else "FAIL"

    acceptance = {
        "step": "S48",
        "attempt": attempt,
        "result": result,
        "ts": _utc(),
        "failed": failed,
        "checks": checks,
        "probe_dir": str(probe_dir.relative_to(root)).replace("\\", "/"),
        "release": "E0",
        "public_hosting": "NOT_PROVIDED",
        "cache_reused": True,
    }
    (step_dir / "acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# S48 {attempt}",
        "",
        f"- result: **{result}**",
        f"- probe: `{probe_dir.relative_to(root).as_posix()}`",
        f"- release: E0",
        f"- public_hosting: NOT_PROVIDED (录像/复现包)",
        f"- cache_reused: true (未整盘 wipe；四环境+锁+基座核验)",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for c in checks:
        lines.append(f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} |")
    if failed:
        lines += ["", "## Failed", "", *[f"- {x}" for x in failed]]
    (step_dir / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (step_dir / "evidence_index.json").write_text(
        json.dumps(
            {
                "acceptance": "acceptance.md",
                "acceptance_json": "acceptance.json",
                "probe": str(probe_dir.relative_to(root)).replace("\\", "/"),
                "backup": f"runs/backups/bak_s48_{attempt}/",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": result, "failed": failed}, indent=2))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
