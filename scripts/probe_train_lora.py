#!/usr/bin/env python3
"""S07: tiny LoRA forward/backward/save/reload; trainable = LoRA only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_paths import ensure_cache_env, work_root  # noqa: E402


def latest_model(root: Path, role: str) -> Path:
    base = root / "models" / role
    dirs = [p for p in base.iterdir() if p.is_dir()]
    if not dirs:
        raise SystemExit("base model missing")
    return sorted(dirs, key=lambda p: p.name)[-1]


def main() -> int:
    root = ensure_cache_env()
    probe_id = "probe_s07_train_lora_a001"
    out_dir = root / "runs" / "probes" / probe_id
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = root / "artifacts" / "checkpoints" / "exp_probe_s07_0001"
    ckpt.mkdir(parents=True, exist_ok=True)
    (ckpt / "PROBE_MARKER.txt").write_text("probe_only_not_sft\n", encoding="utf-8")

    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_path = latest_model(root, "base")
    tok = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        trust_remote_code=True,
    )
    lora = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    trainable = [(n, p.numel()) for n, p in model.named_parameters() if p.requires_grad]
    all_params = list(model.named_parameters())
    non_lora_trainable = [n for n, p in trainable if "lora_" not in n]
    text = "Hello"
    inputs = tok(text, return_tensors="pt").to("cuda")
    out = model(**inputs, labels=inputs["input_ids"])
    loss = out.loss
    loss.backward()
    model.save_pretrained(str(ckpt / "adapter"))
    # reload
    base = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        trust_remote_code=True,
    )
    reloaded = PeftModel.from_pretrained(base, str(ckpt / "adapter"))
    with torch.no_grad():
        _ = reloaded(**inputs)

    report = {
        "probe_id": probe_id,
        "loss": float(loss.detach().cpu()),
        "trainable_param_tensors": len(trainable),
        "trainable_params": int(sum(n for _, n in trainable)),
        "non_lora_trainable": non_lora_trainable,
        "only_lora_trainable": len(non_lora_trainable) == 0,
        "checkpoint": str(ckpt),
        "probe_marker": True,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        f"# {probe_id}\n\nonly_lora_trainable={report['only_lora_trainable']}\nloss={report['loss']}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    print("TRAIN_LORA_OK" if report["only_lora_trainable"] else "TRAIN_LORA_FAIL")
    return 0 if report["only_lora_trainable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
