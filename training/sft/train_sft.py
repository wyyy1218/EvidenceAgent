#!/usr/bin/env python3
"""S31/S32: QLoRA SFT for the EvidenceAgent policy.

Probe mode uses 32 samples and a few updates to verify the full training path.
Formal mode uses the frozen S30 train split, 2 epochs, effective batch 16.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
for _p in (_REPO, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

ACTION_ORDER = ("action", "query", "candidate_id", "reason_code")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _find_model_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = root / p
        return p
    base = root / "models" / "base"
    candidates = [
        p for p in base.iterdir() if p.is_dir() and (p / "config.json").is_file()
    ] if base.is_dir() else []
    if not candidates:
        raise SystemExit(f"no base model under {base}; pass --model-dir")
    return sorted(candidates, key=lambda p: p.name)[-1]


def _select_eval(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if n <= 0:
        return []
    ordered = sorted(rows, key=lambda r: hashlib.sha256(f"s33_dev_eval:{r['state_hash']}".encode()).hexdigest())
    return ordered[:n]


def _dataset_from_rows(rows: list[dict[str, Any]]):
    from datasets import Dataset

    return Dataset.from_dict(
        {
            "prompt": [r["prompt"] for r in rows],
            "completion": [r["completion"] for r in rows],
        }
    )


def _generation_prompts(rows: list[dict[str, Any]], n: int = 4) -> list[dict[str, Any]]:
    picked = _select_eval(rows, n)
    return [
        {
            "state_id": r["state_id"],
            "task_id": r["task_id"],
            "messages": r["messages"],
            "reference_action": r["action"],
        }
        for r in picked
    ]

def _patch_lm_head(model) -> None:
    """Keep the final projection dtype-safe after k-bit preparation.

    prepare_model_for_kbit_training upcasts some norms to fp32; the lm_head
    weight may stay fp32 while hidden states are bf16 (or vice versa). Casting
    the input to the projection's own dtype avoids a hard dtype mismatch.
    """
    lm = getattr(model, "lm_head", None)
    if lm is None:
        return
    original = lm.forward

    def _forward(x):
        return original(x.to(lm.weight.dtype))

    lm.forward = _forward


def _action_valid(text: str) -> bool:
    import json as _json

    try:
        obj = _json.loads(text)
    except Exception:
        return False
    if not isinstance(obj, dict) or set(obj) != set(ACTION_ORDER):
        return False
    return obj.get("action") in {
        "local_search",
        "web_search",
        "read_evidence",
        "finish",
        "abstain",
    }


def _generate(model, tokenizer, prompts: list[dict[str, Any]], max_new_tokens: int = 192) -> list[dict[str, Any]]:
    import torch

    model.eval()
    out: list[dict[str, Any]] = []
    for p in prompts:
        text = tokenizer.apply_chat_template(
            p["messages"], tokenize=False, add_generation_prompt=True
        )
        enc = tokenizer(text, return_tensors="pt", add_special_tokens=False)
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.no_grad():
            gen = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                eos_token_id=tokenizer.eos_token_id,
                pad_token_id=tokenizer.pad_token_id,
            )
        new_ids = gen[0][enc["input_ids"].shape[1]:]
        content = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        out.append(
            {
                "state_id": p["state_id"],
                "task_id": p["task_id"],
                "reference_action": p["reference_action"],
                "raw": content,
                "valid_json": _action_valid(content),
            }
        )
    return out


def _build_callbacks():
    from transformers import TrainerCallback

    class MetricsCallback(TrainerCallback):
        def __init__(self) -> None:
            import torch

            self._torch = torch
            self.logs: list[dict[str, Any]] = []
            self.checkpoints: list[dict[str, Any]] = []
            self.nan = False

        def on_log(self, args, state, control, logs=None, **kwargs):  # noqa: ANN001
            logs = logs or {}
            rec = {
                "step": int(state.global_step),
                "time": _now(),
                "logs": {k: v for k, v in logs.items() if isinstance(v, (int, float, str))},
                "peak_vram_mib": round(self._torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
            }
            self.logs.append(rec)
            for key in ("loss", "grad_norm"):
                v = logs.get(key)
                if isinstance(v, (int, float)) and not math.isfinite(float(v)):
                    self.nan = True
                    control.should_training_stop = True

        def on_save(self, args, state, control, **kwargs):  # noqa: ANN001
            self.checkpoints.append(
                {
                    "step": int(state.global_step),
                    "dir": str(Path(args.output_dir) / f"checkpoint-{state.global_step}"),
                }
            )

    return MetricsCallback()


def _build_trainer(args, root: Path, train_rows: list[dict[str, Any]], dev_rows: list[dict[str, Any]]):
    import torch
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    model_dir = _find_model_dir(root, args.model_dir)
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir), trust_remote_code=True, local_files_only=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

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
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    _patch_lm_head(model)

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        task_type="CAUSAL_LM",
    )

    eval_rows = _select_eval(dev_rows, args.eval_samples) if args.mode == "formal" else []
    train_ds = _dataset_from_rows(train_rows)
    eval_ds = _dataset_from_rows(eval_rows) if eval_rows else None
    use_eval = eval_ds is not None
    cfg = SFTConfig(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.accum,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        weight_decay=0.01,
        max_grad_norm=1.0,
        optim="paged_adamw_8bit",
        bf16=True,
        fp16=False,
        logging_steps=10,
        logging_first_step=True,
        save_strategy="steps" if args.save_steps > 0 else "no",
        save_steps=args.save_steps if args.save_steps > 0 else 100,
        save_total_limit=2,
        eval_strategy="steps" if use_eval else "no",
        eval_steps=args.save_steps if use_eval and args.save_steps > 0 else None,
        prediction_loss_only=True,
        max_length=args.max_length,
        packing=False,
        completion_only_loss=True,
        remove_unused_columns=False,
        report_to=[],
        seed=42,
        data_seed=42,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_num_workers=0,
        save_safetensors=True,
        disable_tqdm=False,
    )
    callback = _build_callbacks()
    trainer = SFTTrainer(
        model=model,
        args=cfg,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        peft_config=lora,
        callbacks=[callback],
    )
    return {
        "trainer": trainer,
        "tokenizer": tokenizer,
        "model": model,
        "model_dir": model_dir,
        "config": cfg,
        "lora": lora,
        "callback": callback,
        "eval_rows": eval_rows,
    }

def _probe_rows(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["action"]["action"], []).append(r)
    order = ["local_search", "read_evidence", "web_search", "finish", "abstain"]
    out: list[dict[str, Any]] = []
    while len(out) < n:
        added = False
        for action in order:
            bucket = groups.get(action) or []
            if bucket:
                out.append(bucket.pop(0))
                added = True
                if len(out) >= n:
                    break
        if not added:
            break
    return out


def run(args) -> int:
    import torch

    root = args.root.resolve()
    dataset_dir = args.dataset_dir or (root / "data" / "sft" / "sft_s30_v1")
    output_dir = args.output_dir or (root / "runs" / "training" / args.experiment_id)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    if args.adapter_dir:
        adapter_dir = args.adapter_dir
        if not adapter_dir.is_absolute():
            adapter_dir = root / adapter_dir
    elif args.mode == "probe":
        adapter_dir = root / "artifacts" / "checkpoints" / args.experiment_id / "adapter"
    else:
        adapter_dir = root / "artifacts" / "adapters" / "sft" / args.experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    # SFTConfig receives args.output_dir; keep it equal to the resolved run dir
    # so checkpoints land next to train.log instead of ./None/.
    args.output_dir = output_dir

    train_rows = _load_jsonl(dataset_dir / "train.jsonl")
    dev_rows = _load_jsonl(dataset_dir / "dev.jsonl")
    if args.mode == "probe":
        train_rows = _probe_rows(train_rows, args.max_samples)
    elif args.max_samples > 0:
        train_rows = train_rows[: args.max_samples]

    started = _now()
    built = _build_trainer(args, root, train_rows, dev_rows)
    trainer = built["trainer"]
    tokenizer = built["tokenizer"]
    model = built["model"]
    callback = built["callback"]

    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in trainer.model.parameters())
    only_lora = all(
        "lora_" in name for name, p in trainer.model.named_parameters() if p.requires_grad
    )
    trainable_info = {
        "trainable_params": int(trainable),
        "total_params": int(total),
        "trainable_ratio": round(trainable / total, 8) if total else 0.0,
        "only_lora_trainable": bool(only_lora),
    }

    base_outputs: list[dict[str, Any]] = []
    base_prompts: list[dict[str, Any]] = []
    if args.mode == "probe":
        base_prompts = _generation_prompts(dev_rows, 4)
        base_outputs = _generate(model, tokenizer, base_prompts)

    oom = False
    try:
        trainer.train()
    except torch.cuda.OutOfMemoryError as exc:
        oom = True
        _write_json(
            output_dir / "oom.json",
            {
                "error": "cuda_oom",
                "message": str(exc),
                "max_length": args.max_length,
                "trainable": trainable_info,
                "time": _now(),
            },
        )

    if oom:
        print(json.dumps({"ok": False, "reason": "cuda_oom", "output_dir": str(output_dir)}))
        return 2

    global_step = int(trainer.state.global_step)
    trainer.model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    trainer.save_state()
    adapter_file = adapter_dir / "adapter_model.safetensors"
    adapter_hash = _sha_file(adapter_file) if adapter_file.is_file() else None

    history = list(trainer.state.log_history)
    _write_json(output_dir / "history.json", history)
    losses = [h.get("loss") for h in history if isinstance(h.get("loss"), (int, float))]
    grad_norms = [h.get("grad_norm") for h in history if isinstance(h.get("grad_norm"), (int, float))]
    nan = bool(callback.nan) or any(not math.isfinite(float(x)) for x in losses + grad_norms)

    first_batch: dict[str, Any] = {}
    try:
        sample = trainer.train_dataset[0]
        first_batch["keys"] = list(sample.keys())
        if "completion_mask" in sample:
            cm = list(sample["completion_mask"])
            first_batch["completion_mask_len"] = len(cm)
            first_batch["completion_tokens"] = int(sum(cm))
            first_batch["prompt_tokens"] = len(cm) - int(sum(cm))
        if "input_ids" in sample:
            ids = list(sample["input_ids"])
            first_batch["input_len"] = len(ids)
            first_batch["last_token"] = int(ids[-1])
            first_batch["eos_token_id"] = int(tokenizer.eos_token_id)
        batch = trainer.data_collator([trainer.train_dataset[0]])
        labels = list(batch["labels"][0].tolist())
        first_batch["labels_len"] = len(labels)
        first_batch["labels_neg100"] = sum(1 for x in labels if x == -100)
        first_batch["labels_active"] = sum(1 for x in labels if x != -100)
        first_batch["labels_last"] = int(labels[-1])
    except Exception as exc:  # noqa: BLE001
        first_batch["error"] = f"{type(exc).__name__}: {exc}"
    _write_json(output_dir / "first_batch_mask.json", first_batch)

    peak_vram = round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1)
    adapter_outputs: list[dict[str, Any]] = []
    reload_probe: dict[str, Any] = {"skipped": args.mode != "probe"}
    if args.mode == "probe":
        adapter_outputs = _generate(trainer.model, tokenizer, base_prompts)
        _write_json(output_dir / "probe_outputs_base.json", base_outputs)
        _write_json(output_dir / "probe_outputs_adapter.json", adapter_outputs)
        base_valid = sum(1 for x in base_outputs if x["valid_json"])
        adapter_valid = sum(1 for x in adapter_outputs if x["valid_json"])
        del trainer
        del model
        gc.collect()
        torch.cuda.empty_cache()
        try:
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, BitsAndBytesConfig

            bnb = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            base = AutoModelForCausalLM.from_pretrained(
                str(built["model_dir"]),
                quantization_config=bnb,
                torch_dtype=torch.bfloat16,
                device_map={"": 0},
                trust_remote_code=True,
            )
            _patch_lm_head(base)
            reloaded = PeftModel.from_pretrained(base, str(adapter_dir))
            reload_out = _generate(reloaded, tokenizer, base_prompts[:1])
            reload_probe = {
                "skipped": False,
                "ok": bool(reload_out and reload_out[0]["raw"]),
                "output": reload_out[0] if reload_out else None,
            }
            del reloaded
            del base
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001
            reload_probe = {"skipped": False, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        reload_probe["base_valid_rate"] = round(base_valid / max(1, len(base_outputs)), 4)
        reload_probe["adapter_valid_rate"] = round(adapter_valid / max(1, len(adapter_outputs)), 4)

    summary = {
        "experiment_id": args.experiment_id,
        "mode": args.mode,
        "ok": not nan and (args.mode != "probe" or reload_probe.get("ok", False)),
        "started_at": started,
        "ended_at": _now(),
        "base_model_dir": str(built["model_dir"]),
        "dataset_dir": str(dataset_dir),
        "train_samples": len(train_rows),
        "dev_samples": len(dev_rows),
        "eval_samples": len(built["eval_rows"]),
        "max_length": args.max_length,
        "learning_rate": args.lr,
        "epochs": args.epochs,
        "max_steps": args.max_steps,
        "gradient_accumulation_steps": args.accum,
        "effective_batch": args.accum,
        "global_step": global_step,
        "trainable": trainable_info,
        "peak_vram_mib": peak_vram,
        "losses": losses,
        "grad_norms": grad_norms,
        "loss_finite": not any(not math.isfinite(float(x)) for x in losses),
        "grad_norm_finite": not any(not math.isfinite(float(x)) for x in grad_norms),
        "nan_detected": nan,
        "checkpoints": callback.checkpoints,
        "adapter_dir": str(adapter_dir),
        "adapter_hash": adapter_hash,
        "first_batch_mask": first_batch,
        "reload_probe": reload_probe,
        "config": {
            "lora_r": 16,
            "lora_alpha": 32,
            "lora_dropout": 0.05,
            "target_modules": [
                "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"
            ],
            "completion_only_loss": True,
            "packing": False,
            "optim": "paged_adamw_8bit",
            "bf16": True,
        },
    }
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(
        "\n".join(
            [
                f"# {args.experiment_id}",
                "",
                f"- mode: {args.mode}",
                f"- train_samples: {len(train_rows)}",
                f"- global_step: {summary['global_step']}",
                f"- trainable: {trainable_info['trainable_params']} ({trainable_info['trainable_ratio']})",
                f"- only_lora_trainable: {trainable_info['only_lora_trainable']}",
                f"- peak_vram_mib: {peak_vram}",
                f"- loss_finite: {summary['loss_finite']}",
                f"- grad_norm_finite: {summary['grad_norm_finite']}",
                f"- nan_detected: {nan}",
                f"- adapter_hash: {adapter_hash}",
                f"- reload_probe: {reload_probe}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({k: summary[k] for k in ("experiment_id", "mode", "ok", "train_samples", "global_step", "trainable", "peak_vram_mib", "loss_finite", "grad_norm_finite", "nan_detected", "adapter_hash", "reload_probe")}, ensure_ascii=False))
    return 0 if summary["ok"] else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--mode", choices=["probe", "formal"], required=True)
    ap.add_argument("--experiment-id", required=True)
    ap.add_argument("--dataset-dir", type=Path, default=None)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--adapter-dir", type=Path, default=None)
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--accum", type=int, default=None)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-length", type=int, default=3072)
    ap.add_argument("--save-steps", type=int, default=None)
    ap.add_argument("--eval-samples", type=int, default=None)
    args = ap.parse_args()
    if args.mode == "probe":
        args.max_samples = 32 if args.max_samples is None else args.max_samples
        args.max_steps = 4 if args.max_steps is None else args.max_steps
        args.epochs = 1 if args.epochs is None else args.epochs
        args.accum = 1 if args.accum is None else args.accum
        args.save_steps = 0 if args.save_steps is None else args.save_steps
        args.eval_samples = 0 if args.eval_samples is None else args.eval_samples
    else:
        args.max_samples = 0 if args.max_samples is None else args.max_samples
        args.max_steps = -1 if args.max_steps is None else args.max_steps
        args.epochs = 2 if args.epochs is None else args.epochs
        args.accum = 16 if args.accum is None else args.accum
        args.save_steps = 100 if args.save_steps is None else args.save_steps
        args.eval_samples = 64 if args.eval_samples is None else args.eval_samples
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())