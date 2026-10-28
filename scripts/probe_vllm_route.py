#!/usr/bin/env python3
"""S07: vLLM guided JSON + temp LoRA listed + Writer→base (T24)."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env  # noqa: E402

VLLM = "http://127.0.0.1:8001/v1"
BASE_NAME = "Qwen/Qwen3-4B-Instruct-2507"
LORA_NAME = "probe_s07_tmp_lora"
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["local_search", "web_search", "read_evidence", "finish", "abstain"],
        },
        "query": {"type": ["string", "null"]},
        "candidate_id": {"type": ["string", "null"]},
        "reason_code": {"type": ["string", "null"]},
    },
    "required": ["action", "query", "candidate_id", "reason_code"],
    "additionalProperties": False,
}


def post(path: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{VLLM}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{VLLM}{path}", timeout=30) as resp:
        return json.loads(resp.read().decode())


def _structured(model: str) -> tuple[bool, str]:
    prompt = (
        "Return ONLY a JSON object with keys action,query,candidate_id,reason_code. "
        "Choose action=finish, query=null, candidate_id=null, "
        "reason_code=evidence_sufficient."
    )
    try:
        r = post(
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 128,
                "guided_json": ACTION_SCHEMA,
            },
        )
        raw = r["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        ok = (
            set(parsed) == {"action", "query", "candidate_id", "reason_code"}
            and parsed.get("action") == "finish"
        )
        return ok, raw
    except Exception as exc:  # noqa: BLE001
        return False, f"ERR {type(exc).__name__}: {exc}"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--lora-name", default="sft_e1")
    ap.add_argument("--probe-id", default="probe_s33_vllm_route_a001")
    args = ap.parse_args()
    root = ensure_cache_env()
    probe_id = args.probe_id
    out_dir = root / "runs" / "probes" / probe_id
    out_dir.mkdir(parents=True, exist_ok=True)

    models = get("/models")
    model_ids = [m.get("id") for m in models.get("data", [])]

    structured_ok, structured_raw = _structured(BASE_NAME)
    lora_listed = args.lora_name in model_ids
    lora_structured_ok, lora_structured_raw = (
        _structured(args.lora_name) if lora_listed else (False, "")
    )

    # Writer must hit base (served-model-name), not an adapter id (T24)
    writer = post(
        "/chat/completions",
        {
            "model": BASE_NAME,
            "messages": [{"role": "user", "content": "Reply with the single word BASEOK"}],
            "temperature": 0.0,
            "max_tokens": 16,
        },
    )
    used_model = writer.get("model")
    text = writer["choices"][0]["message"]["content"]
    writer_base = (used_model == BASE_NAME) or (BASE_NAME in str(used_model))

    t24_pass = bool(writer_base and structured_ok and lora_listed and lora_structured_ok)
    report = {
        "probe_id": probe_id,
        "lora_name": args.lora_name,
        "models": models,
        "structured_base_ok": structured_ok,
        "structured_base_raw": structured_raw[:1000],
        "writer_route_base": writer_base,
        "writer_model_field": used_model,
        "writer_text": text[:200],
        "lora_listed": lora_listed,
        "lora_structured_ok": lora_structured_ok,
        "lora_structured_raw": lora_structured_raw[:1000],
        "t24_pass": t24_pass,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(
        f"# {probe_id}\n\nstructured_base_ok={structured_ok}\nwriter_route_base={writer_base}\n"
        f"lora_listed={lora_listed}\nlora_structured_ok={lora_structured_ok}\nt24_pass={t24_pass}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("VLLM_ROUTE_OK" if t24_pass else "VLLM_ROUTE_FAIL")
    return 0 if t24_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
