#!/usr/bin/env python3
"""S33: compare the training 4-bit adapter path with the vLLM adapter path."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prompts(root: Path, n: int) -> list[dict[str, Any]]:
    rows = _load_jsonl(root / "data" / "sft" / "sft_s30_v1" / "dev.jsonl")
    rows = sorted(
        rows,
        key=lambda r: hashlib.sha256(f"s33_quant_probe:{r['state_hash']}".encode()).hexdigest(),
    )[:n]
    return [
        {
            "state_id": r["state_id"],
            "task_id": r["task_id"],
            "messages": r["messages"],
            "reference_action": r["action"],
        }
        for r in rows
    ]


def _patch_lm_head(model) -> None:
    lm = getattr(model, "lm_head", None)
    if lm is None:
        return
    original = lm.forward

    def _forward(x):
        return original(x.to(lm.weight.dtype))

    lm.forward = _forward


def _valid(text: str) -> bool:
    try:
        obj = json.loads(text)
    except Exception:
        return False
    return isinstance(obj, dict) and set(obj) == {"action", "query", "candidate_id", "reason_code"}


def run_quant(root: Path, adapter_dir: Path, prompts: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    base = root / "models" / "base"
    model_dir = sorted(
        [p for p in base.iterdir() if p.is_dir() and (p / "config.json").is_file()],
        key=lambda p: p.name,
    )[-1]
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), trust_remote_code=True, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir),
        quantization_config=bnb,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    _patch_lm_head(model)
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()
    outputs: list[dict[str, Any]] = []
    for p in prompts:
        text = tokenizer.apply_chat_template(p["messages"], tokenize=False, add_generation_prompt=True)
        enc = tokenizer(text, return_tensors="pt", add_special_tokens=False)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.no_grad():
            gen = model.generate(
                **enc,
                max_new_tokens=192,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
        raw = tokenizer.decode(gen[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        outputs.append(
            {
                "state_id": p["state_id"],
                "task_id": p["task_id"],
                "reference_action": p["reference_action"],
                "raw": raw,
                "valid_json": _valid(raw),
            }
        )
    report = {"path": "quant_4bit_adapter", "adapter_dir": str(adapter_dir), "outputs": outputs}
    _write_json(out, report)
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return report


def run_vllm(prompts: list[dict[str, Any]], out: Path, adapter_name: str) -> dict[str, Any]:
    from evidence_agent.agent.llm import HttpLLMClient

    client = HttpLLMClient()
    outputs: list[dict[str, Any]] = []
    for p in prompts:
        resp = client.chat(
            p["messages"], max_tokens=192, temperature=0.0, adapter_id=adapter_name
        )
        outputs.append(
            {
                "state_id": p["state_id"],
                "task_id": p["task_id"],
                "reference_action": p["reference_action"],
                "raw": resp.content,
                "valid_json": _valid(resp.content),
            }
        )
    report = {"path": "vllm_adapter", "adapter_name": adapter_name, "outputs": outputs}
    _write_json(out, report)
    return report


def compare(quant_path: Path, vllm_path: Path, out: Path) -> dict[str, Any]:
    q = json.loads(quant_path.read_text(encoding="utf-8"))["outputs"]
    v = json.loads(vllm_path.read_text(encoding="utf-8"))["outputs"]
    by_state = {x["state_id"]: x for x in v}
    rows: list[dict[str, Any]] = []
    for x in q:
        y = by_state.get(x["state_id"]) or {}
        try:
            qa = json.loads(x["raw"]).get("action")
        except Exception:
            qa = None
        try:
            va = json.loads(y.get("raw") or "").get("action")
        except Exception:
            va = None
        rows.append(
            {
                "state_id": x["state_id"],
                "quant_valid": x["valid_json"],
                "vllm_valid": bool(y.get("valid_json")),
                "identical": x["raw"] == y.get("raw"),
                "action_equal": qa == va,
                "quant_action": qa,
                "vllm_action": va,
            }
        )
    n = max(1, len(rows))
    report = {
        "n": len(rows),
        "quant_valid_rate": round(sum(1 for r in rows if r["quant_valid"]) / n, 4),
        "vllm_valid_rate": round(sum(1 for r in rows if r["vllm_valid"]) / n, 4),
        "identical_rate": round(sum(1 for r in rows if r["identical"]) / n, 4),
        "action_equal_rate": round(sum(1 for r in rows if r["action_equal"]) / n, 4),
        "rows": rows,
    }
    _write_json(out, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--mode", choices=["quant", "vllm", "compare"], required=True)
    ap.add_argument("--adapter-dir", type=Path, default=None)
    ap.add_argument("--adapter-name", default="sft_e1")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    out = args.out if args.out.is_absolute() else root / args.out
    prompts = _prompts(root, args.n)
    if args.mode == "quant":
        adapter = args.adapter_dir or (root / "artifacts" / "adapters" / "sft" / "exp_sft_0001")
        if not adapter.is_absolute():
            adapter = root / adapter
        report = run_quant(root, adapter, prompts, out)
    elif args.mode == "vllm":
        report = run_vllm(prompts, out, args.adapter_name)
    else:
        quant_path = root / "runs" / "evaluation" / "eval_quant_probe_s33_0001" / "quant_outputs.json"
        vllm_path = root / "runs" / "evaluation" / "eval_quant_probe_s33_0001" / "vllm_outputs.json"
        report = compare(quant_path, vllm_path, out)
    print(json.dumps({k: v for k, v in report.items() if k != "outputs"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())