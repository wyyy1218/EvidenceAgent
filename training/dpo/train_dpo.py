#!/usr/bin/env python3
"""S37/S38: QLoRA DPO with dual adapters (train + frozen reference).

Modes:
  validate-cache  build/verify reference log-prob cache vs frozen SFT
  t23             fault-inject missing reference → must exit non-zero
  probe           short real-pair forward/backward + save/reload + VRAM
  formal          full DPO from project.yaml hyperparams
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
_DPO = Path(__file__).resolve().parent
for _p in (_REPO, _SRC, _DPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from ref_cache import (  # noqa: E402
    DEFAULT_ATOL,
    MASK_RULE,
    assert_t23_blocks,
    build_cache_key,
    cache_invalid_reasons,
    load_cache_manifest,
    load_cache_rows,
    logprob_within_atol,
    mask_rule_fingerprint,
    sample_hash,
    select_spot_indices,
    sha_file,
    t23_reference_misconfigured,
    tokenizer_fingerprint,
    validate_spot_diffs,
    write_cache_manifest,
    write_cache_rows,
)

# PEFT ModuleDict rejects adapter name "train" (collides with nn.Module.train).
TRAIN_ADAPTER = "policy"
REF_ADAPTER = "reference"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_project_dpo(root: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(f"pyyaml required: {exc}") from exc
    path = root / "repo" / "configs" / "project.yaml"
    if not path.is_file():
        path = _REPO / "configs" / "project.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict((cfg.get("training") or {}).get("dpo") or {})


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


def _sft_adapter_dir(root: Path, explicit: Path | None) -> Path:
    if explicit:
        p = explicit if explicit.is_absolute() else root / explicit
        return p
    return root / "artifacts" / "adapters" / "sft" / "exp_sft_0001"


def _adapter_sha(adapter_dir: Path) -> str:
    weights = adapter_dir / "adapter_model.safetensors"
    if not weights.is_file():
        raise FileNotFoundError(f"missing adapter weights: {weights}")
    return sha_file(weights)


def _dataset_from_rows(rows: list[dict[str, Any]]):
    from datasets import Dataset

    return Dataset.from_dict(
        {
            "prompt": [r["prompt"] for r in rows],
            "chosen": [r["chosen"] for r in rows],
            "rejected": [r["rejected"] for r in rows],
        }
    )


def _patch_lm_head(model) -> None:
    lm = getattr(model, "lm_head", None)
    if lm is None:
        return
    original = lm.forward

    def _forward(x):
        return original(x.to(lm.weight.dtype))

    lm.forward = _forward


def _tokenize_pair(
    tokenizer,
    prompt: str,
    chosen: str,
    rejected: str,
    *,
    max_prompt_length: int,
    max_completion_length: int,
) -> dict[str, list[int]]:
    """Match TRL DPOTrainer.tokenize_row with add_special_tokens=False."""
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    chosen_ids = tokenizer(chosen, add_special_tokens=False)["input_ids"]
    rejected_ids = tokenizer(rejected, add_special_tokens=False)["input_ids"]
    eos = tokenizer.eos_token_id
    chosen_ids = chosen_ids + [eos]
    rejected_ids = rejected_ids + [eos]
    prompt_ids = prompt_ids[-max_prompt_length:]
    chosen_ids = chosen_ids[:max_completion_length]
    rejected_ids = rejected_ids[:max_completion_length]
    return {
        "prompt_input_ids": prompt_ids,
        "chosen_input_ids": chosen_ids,
        "rejected_input_ids": rejected_ids,
    }


def _sum_completion_logps(model, tokenizer, prompt_ids: list[int], completion_ids: list[int]) -> float:
    import torch
    import torch.nn.functional as F

    input_ids = torch.tensor([prompt_ids + completion_ids], device=model.device)
    attention_mask = torch.ones_like(input_ids)
    with torch.no_grad():
        logits = model(input_ids=input_ids, attention_mask=attention_mask).logits
    # Predict token t from position t-1
    shift_logits = logits[:, :-1, :]
    shift_labels = input_ids[:, 1:]
    logps = F.log_softmax(shift_logits, dim=-1)
    token_logps = logps.gather(2, shift_labels.unsqueeze(-1)).squeeze(-1)
    prompt_len = len(prompt_ids)
    # completion tokens occupy labels indices [prompt_len-1 .. prompt_len+len(comp)-2]
    start = prompt_len - 1
    end = start + len(completion_ids)
    return float(token_logps[0, start:end].sum().item())


def _pair_logps(
    model,
    tokenizer,
    row: dict[str, Any],
    *,
    max_prompt_length: int,
    max_completion_length: int,
) -> dict[str, float]:
    tok = _tokenize_pair(
        tokenizer,
        row["prompt"],
        row["chosen"],
        row["rejected"],
        max_prompt_length=max_prompt_length,
        max_completion_length=max_completion_length,
    )
    return {
        "chosen_logp": _sum_completion_logps(
            model, tokenizer, tok["prompt_input_ids"], tok["chosen_input_ids"]
        ),
        "rejected_logp": _sum_completion_logps(
            model, tokenizer, tok["prompt_input_ids"], tok["rejected_input_ids"]
        ),
    }


def _load_base_nf4(model_dir: Path):
    import torch
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

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
    _patch_lm_head(model)
    return model


def _load_tokenizer(adapter_dir: Path, model_dir: Path):
    from transformers import AutoTokenizer

    tok_src = adapter_dir if (adapter_dir / "tokenizer_config.json").is_file() else model_dir
    tokenizer = AutoTokenizer.from_pretrained(
        str(tok_src), trust_remote_code=True, local_files_only=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    return tokenizer


def _load_frozen_sft(root: Path, args) -> dict[str, Any]:
    """Single frozen SFT adapter on NF4 base — ground-truth reference for cache."""
    from peft import PeftModel

    model_dir = _find_model_dir(root, args.model_dir)
    sft_dir = _sft_adapter_dir(root, args.sft_adapter_dir)
    tokenizer = _load_tokenizer(sft_dir, model_dir)
    base = _load_base_nf4(model_dir)
    model = PeftModel.from_pretrained(base, str(sft_dir), adapter_name=REF_ADAPTER)
    model.set_adapter(REF_ADAPTER)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False
    return {
        "model": model,
        "tokenizer": tokenizer,
        "model_dir": model_dir,
        "sft_dir": sft_dir,
        "sft_sha": _adapter_sha(sft_dir),
        "tokenizer_fp": tokenizer_fingerprint(sft_dir),
    }


def _load_dual_adapters(root: Path, args, *, load_reference: bool = True) -> dict[str, Any]:
    """NF4 base + train (+ optional frozen reference) adapters from same SFT init."""
    from peft import PeftModel, prepare_model_for_kbit_training

    model_dir = _find_model_dir(root, args.model_dir)
    sft_dir = _sft_adapter_dir(root, args.sft_adapter_dir)
    tokenizer = _load_tokenizer(sft_dir, model_dir)
    base = _load_base_nf4(model_dir)
    base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)
    _patch_lm_head(base)
    model = PeftModel.from_pretrained(base, str(sft_dir), is_trainable=True, adapter_name=TRAIN_ADAPTER)
    ref_loaded = False
    if load_reference:
        model.load_adapter(str(sft_dir), adapter_name=REF_ADAPTER)
        ref_loaded = True
        # Freeze reference LoRA params; keep train trainable.
        for name, param in model.named_parameters():
            if f".{REF_ADAPTER}." in name or name.endswith(f".{REF_ADAPTER}"):
                param.requires_grad = False
            elif f".{TRAIN_ADAPTER}." in name:
                param.requires_grad = True
    model.set_adapter(TRAIN_ADAPTER)
    return {
        "model": model,
        "tokenizer": tokenizer,
        "model_dir": model_dir,
        "sft_dir": sft_dir,
        "sft_sha": _adapter_sha(sft_dir),
        "tokenizer_fp": tokenizer_fingerprint(sft_dir),
        "ref_adapter_loaded": ref_loaded,
    }


def _adapter_weight_digest(model, adapter_name: str) -> str:
    import torch

    chunks: list[bytes] = []
    for name, param in model.named_parameters():
        if f".{adapter_name}." in name:
            chunks.append(name.encode())
            chunks.append(param.detach().float().cpu().numpy().tobytes())
    if not chunks:
        return "empty"
    return hashlib.sha256(b"".join(chunks)).hexdigest()


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
            for key in ("loss", "grad_norm", "rewards/chosen", "rewards/rejected"):
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


def _resolve_hyperparams(args, root: Path) -> dict[str, Any]:
    dpo = _load_project_dpo(root)
    return {
        "epochs": args.epochs if args.epochs is not None else int(dpo.get("epochs", 2)),
        "accum": args.accum if args.accum is not None else int(dpo.get("accumulation", 8)),
        "lr": args.lr if args.lr is not None else float(dpo.get("learning_rate", 5e-6)),
        "beta": float(dpo.get("beta", 0.1)),
        "loss_type": str(dpo.get("loss_type", "sigmoid")),
        "max_prompt_length": int(dpo.get("max_prompt_length", 2880)),
        "max_completion_length": int(dpo.get("max_completion_length", 192)),
        "precompute_ref_log_probs": bool(dpo.get("precompute_ref_log_probs", True)),
        "model_adapter_name": str(dpo.get("model_adapter_name", TRAIN_ADAPTER)),
        "ref_adapter_name": str(dpo.get("ref_adapter_name", REF_ADAPTER)),
        "save_steps": args.save_steps if args.save_steps is not None else int(dpo.get("save_steps", 50)),
        "logging_steps": int(dpo.get("logging_steps", 10)),
        "seed": 42,
    }


def _ensure_cache(
    root: Path,
    args,
    rows: list[dict[str, Any]],
    *,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Build or load reference cache keyed by SFT SHA / tokenizer / samples / mask."""
    import torch

    hp = _resolve_hyperparams(args, root)
    dataset_dir = args.dataset_dir or (root / "data" / "dpo" / "dpo_s36_v1")
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir
    cache_dir = args.cache_dir or (dataset_dir / "reference_cache")
    if not cache_dir.is_absolute():
        cache_dir = root / cache_dir

    sft_dir = _sft_adapter_dir(root, args.sft_adapter_dir)
    sft_sha = _adapter_sha(sft_dir)
    tok_fp = tokenizer_fingerprint(sft_dir)
    mask_fp = mask_rule_fingerprint()
    hashes = [
        sample_hash(
            r,
            max_prompt_length=hp["max_prompt_length"],
            max_completion_length=hp["max_completion_length"],
        )
        for r in rows
    ]
    key = build_cache_key(
        sft_adapter_sha=sft_sha,
        tokenizer_fp=tok_fp,
        sample_hashes=hashes,
        mask_fp=mask_fp,
        max_prompt_length=hp["max_prompt_length"],
        max_completion_length=hp["max_completion_length"],
    )

    if cache_dir.is_dir() and (cache_dir / "manifest.json").is_file() and not force_rebuild:
        man = load_cache_manifest(cache_dir)
        reasons = cache_invalid_reasons(
            expected_key=key,
            actual_key=str(man.get("cache_key") or ""),
            expected_sft_sha=sft_sha,
            actual_sft_sha=str(man.get("sft_adapter_sha") or ""),
            expected_tokenizer_fp=tok_fp,
            actual_tokenizer_fp=str(man.get("tokenizer_fp") or ""),
            expected_mask_fp=mask_fp,
            actual_mask_fp=str(man.get("mask_fp") or ""),
        )
        if not reasons:
            cached = load_cache_rows(cache_dir, split="train")
            return {
                "cache_dir": cache_dir,
                "cache_key": key,
                "rows": cached,
                "manifest": man,
                "rebuilt": False,
                "sft_sha": sft_sha,
                "tokenizer_fp": tok_fp,
                "mask_fp": mask_fp,
                "hp": hp,
            }
        print(json.dumps({"cache_invalid": reasons}, ensure_ascii=False))

    packed = _load_frozen_sft(root, args)
    model, tokenizer = packed["model"], packed["tokenizer"]
    out_rows: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        lp = _pair_logps(
            model,
            tokenizer,
            r,
            max_prompt_length=hp["max_prompt_length"],
            max_completion_length=hp["max_completion_length"],
        )
        out_rows.append(
            {
                "pair_id": r.get("pair_id"),
                "task_id": r.get("task_id"),
                "index": i,
                "sample_hash": hashes[i],
                "chosen_logp": lp["chosen_logp"],
                "rejected_logp": lp["rejected_logp"],
            }
        )
        if (i + 1) % 25 == 0 or i == 0:
            print(json.dumps({"cache_progress": i + 1, "of": len(rows)}, ensure_ascii=False))

    man = {
        "cache_key": key,
        "sft_adapter_sha": sft_sha,
        "sft_adapter_dir": str(sft_dir),
        "tokenizer_fp": tok_fp,
        "mask_fp": mask_fp,
        "mask_rule": MASK_RULE,
        "max_prompt_length": hp["max_prompt_length"],
        "max_completion_length": hp["max_completion_length"],
        "n_samples": len(rows),
        "atol": DEFAULT_ATOL,
        "built_at": _now(),
        "reference_definition": "frozen_sft_adapter_not_base",
    }
    write_cache_manifest(cache_dir, man)
    write_cache_rows(cache_dir, out_rows, split="train")

    del model
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "cache_dir": cache_dir,
        "cache_key": key,
        "rows": out_rows,
        "manifest": man,
        "rebuilt": True,
        "sft_sha": sft_sha,
        "tokenizer_fp": tok_fp,
        "mask_fp": mask_fp,
        "hp": hp,
    }


def mode_validate_cache(args) -> int:
    import torch

    root = args.root.resolve()
    dataset_dir = args.dataset_dir or (root / "data" / "dpo" / "dpo_s36_v1")
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir
    rows = _load_jsonl(dataset_dir / "train.jsonl")
    if args.max_samples and args.max_samples > 0:
        rows = rows[: args.max_samples]

    out_dir = args.output_dir or (root / "runs" / "probes" / "dpo_validate_cache_s37")
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = _ensure_cache(root, args, rows, force_rebuild=args.rebuild_cache)
    spots = select_spot_indices(rows)

    # Independent recomputation (fresh frozen SFT) for spot pairs.
    packed = _load_frozen_sft(root, args)
    model, tokenizer = packed["model"], packed["tokenizer"]
    hp = cache["hp"]
    spot_pairs: list[dict[str, Any]] = []
    for tag, idx in spots.items():
        live = _pair_logps(
            model,
            tokenizer,
            rows[idx],
            max_prompt_length=hp["max_prompt_length"],
            max_completion_length=hp["max_completion_length"],
        )
        cached = cache["rows"][idx]
        spot_pairs.append(
            {
                "tag": tag,
                "pair_id": rows[idx].get("pair_id"),
                "index": idx,
                "cached_chosen": cached["chosen_logp"],
                "live_chosen": live["chosen_logp"],
                "cached_rejected": cached["rejected_logp"],
                "live_rejected": live["rejected_logp"],
            }
        )
    report = validate_spot_diffs(spot_pairs, atol=DEFAULT_ATOL)
    report["spots"] = spot_pairs
    report["cache_key"] = cache["cache_key"]
    report["rebuilt"] = cache["rebuilt"]
    report["sft_adapter_sha"] = cache["sft_sha"]
    report["n_train"] = len(rows)
    report["ok"] = bool(report["ok"])
    _write_json(out_dir / "validate_cache.json", report)
    print(json.dumps({k: report[k] for k in ("ok", "atol", "n", "failures", "cache_key", "rebuilt")}, ensure_ascii=False))
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return 0 if report["ok"] else 3


def mode_t23(args) -> int:
    """Fault injection: no reference adapter → cache mismatch → non-zero exit."""
    import torch

    root = args.root.resolve()
    dataset_dir = args.dataset_dir or (root / "data" / "dpo" / "dpo_s36_v1")
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir

    out_dir = args.output_dir or (root / "runs" / "probes" / "dpo_t23_s37")
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Full-train cache is the ground truth; spot-check base (disable adapter) vs cache.
    train_all = _load_jsonl(dataset_dir / "train.jsonl")
    cache = _ensure_cache(root, args, train_all, force_rebuild=False)

    # Misconfiguration: load train adapter only; compute "ref" with adapters disabled (= base).
    packed = _load_dual_adapters(root, args, load_reference=False)
    model, tokenizer = packed["model"], packed["tokenizer"]
    misconfigured = t23_reference_misconfigured(
        ref_adapter_loaded=packed["ref_adapter_loaded"],
        ref_adapter_name=None,
        configured_ref_adapter_name=REF_ADAPTER,
        using_disable_adapter_for_ref=True,
    )
    assert_t23_blocks(
        ref_adapter_loaded=packed["ref_adapter_loaded"],
        ref_adapter_name=None,
        configured_ref_adapter_name=REF_ADAPTER,
        using_disable_adapter_for_ref=True,
    )

    hp = cache["hp"]
    spots = select_spot_indices(train_all)
    failures: list[dict[str, Any]] = []
    for tag, idx in spots.items():
        # Base via disable_adapter — wrong reference.
        with model.disable_adapter():
            live = _pair_logps(
                model,
                tokenizer,
                train_all[idx],
                max_prompt_length=hp["max_prompt_length"],
                max_completion_length=hp["max_completion_length"],
            )
        cached = cache["rows"][idx]
        ok_c = logprob_within_atol(cached["chosen_logp"], live["chosen_logp"])
        ok_r = logprob_within_atol(cached["rejected_logp"], live["rejected_logp"])
        if ok_c and ok_r:
            # Unexpected: base matched SFT — still block on misconfig flag.
            failures.append({"tag": tag, "unexpected_match": True, "index": idx})
        else:
            failures.append(
                {
                    "tag": tag,
                    "index": idx,
                    "delta_chosen": abs(cached["chosen_logp"] - live["chosen_logp"]),
                    "delta_rejected": abs(cached["rejected_logp"] - live["rejected_logp"]),
                    "blocked": True,
                }
            )

    blocked = bool(misconfigured and failures)
    report = {
        "ok": False,  # T23 success means we detected and blocked
        "t23_blocked": blocked,
        "misconfigured": misconfigured,
        "failures": failures,
        "message": "reference adapter missing/disabled; DPO blocked",
        "exit_policy": "non_zero",
    }
    _write_json(out_dir / "t23.json", report)
    print(json.dumps(report, ensure_ascii=False))
    del model
    gc.collect()
    torch.cuda.empty_cache()
    # Non-zero: fault was detected (expected PASS path for the test itself is blocked==True).
    return 4 if blocked else 5


def _build_dpo_trainer(args, root: Path, train_rows: list[dict[str, Any]], *, load_reference: bool = True):
    import torch
    from trl import DPOConfig, DPOTrainer

    hp = _resolve_hyperparams(args, root)
    packed = _load_dual_adapters(root, args, load_reference=load_reference)
    if load_reference and not packed["ref_adapter_loaded"]:
        raise SystemExit("reference adapter failed to load")
    if load_reference and t23_reference_misconfigured(
        ref_adapter_loaded=True,
        ref_adapter_name=hp["ref_adapter_name"],
        configured_ref_adapter_name=REF_ADAPTER,
        using_disable_adapter_for_ref=False,
    ):
        raise SystemExit("T23: reference misconfigured")

    model = packed["model"]
    tokenizer = packed["tokenizer"]
    train_ds = _dataset_from_rows(train_rows)

    max_steps = args.max_steps if args.max_steps is not None else -1
    cfg = DPOConfig(
        output_dir=str(args.output_dir),
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=hp["accum"],
        num_train_epochs=hp["epochs"],
        max_steps=max_steps,
        learning_rate=hp["lr"],
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        weight_decay=0.01,
        max_grad_norm=1.0,
        optim="paged_adamw_8bit",
        bf16=True,
        fp16=False,
        logging_steps=hp["logging_steps"] if args.mode == "formal" else 1,
        logging_first_step=True,
        save_strategy="steps" if hp["save_steps"] > 0 else "no",
        save_steps=hp["save_steps"] if hp["save_steps"] > 0 else 50,
        save_total_limit=2,
        eval_strategy="no",
        beta=hp["beta"],
        loss_type=hp["loss_type"],
        max_prompt_length=hp["max_prompt_length"],
        max_completion_length=hp["max_completion_length"],
        max_length=hp["max_prompt_length"] + hp["max_completion_length"],
        precompute_ref_log_probs=hp["precompute_ref_log_probs"],
        model_adapter_name=hp["model_adapter_name"] if load_reference else TRAIN_ADAPTER,
        ref_adapter_name=hp["ref_adapter_name"] if load_reference else None,
        remove_unused_columns=False,
        report_to=[],
        seed=hp["seed"],
        data_seed=hp["seed"],
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_num_workers=0,
        save_safetensors=True,
        disable_tqdm=False,
    )
    callback = _build_callbacks()
    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=cfg,
        train_dataset=train_ds,
        processing_class=tokenizer,
        callbacks=[callback],
    )
    return {
        "trainer": trainer,
        "tokenizer": tokenizer,
        "model": model,
        "packed": packed,
        "hp": hp,
        "callback": callback,
        "config": cfg,
    }


def _probe_rows(rows: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if n <= 0 or n >= len(rows):
        return list(rows)
    spots = select_spot_indices(rows)
    picked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx in (spots["normal"], spots["longest"], spots["chinese"]):
        if idx not in seen:
            picked.append(rows[idx])
            seen.add(idx)
    for i, r in enumerate(rows):
        if len(picked) >= n:
            break
        if i not in seen:
            picked.append(r)
            seen.add(i)
    return picked


def mode_train(args) -> int:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    root = args.root.resolve()
    dataset_dir = args.dataset_dir or (root / "data" / "dpo" / "dpo_s36_v1")
    if not dataset_dir.is_absolute():
        dataset_dir = root / dataset_dir

    if args.mode == "probe":
        default_out = root / "runs" / "probes" / args.experiment_id
        default_adapter = root / "artifacts" / "checkpoints" / args.experiment_id / "adapter"
    else:
        default_out = root / "runs" / "training" / args.experiment_id
        default_adapter = root / "artifacts" / "adapters" / "dpo" / args.experiment_id

    output_dir = args.output_dir or default_out
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    adapter_dir = args.adapter_dir or default_adapter
    if not adapter_dir.is_absolute():
        adapter_dir = root / adapter_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir = output_dir

    train_rows = _load_jsonl(dataset_dir / "train.jsonl")
    if args.mode == "probe":
        n = args.max_samples if args.max_samples is not None else 8
        train_rows = _probe_rows(train_rows, n)
    elif args.max_samples and args.max_samples > 0:
        train_rows = train_rows[: args.max_samples]

    # Cache must exist / match before formal or probe training.
    cache = _ensure_cache(root, args, _load_jsonl(dataset_dir / "train.jsonl"), force_rebuild=False)
    _write_json(
        output_dir / "reference_cache_link.json",
        {
            "cache_dir": str(cache["cache_dir"]),
            "cache_key": cache["cache_key"],
            "sft_adapter_sha": cache["sft_sha"],
            "meets_target_scale": False,
            "train_pairs_used": len(train_rows),
            "train_pairs_available": cache["manifest"]["n_samples"],
            "preference_scope": "action_json_only_not_full_trajectory",
        },
    )

    started = _now()
    built = _build_dpo_trainer(args, root, train_rows, load_reference=True)
    trainer = built["trainer"]
    model = built["model"]
    tokenizer = built["tokenizer"]
    callback = built["callback"]
    packed = built["packed"]
    hp = built["hp"]

    ref_hash_before = _adapter_weight_digest(model, REF_ADAPTER)
    train_hash_before = _adapter_weight_digest(model, TRAIN_ADAPTER)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    only_train_lora = all(
        TRAIN_ADAPTER in name for name, p in model.named_parameters() if p.requires_grad
    )
    trainable_info = {
        "trainable_params": int(trainable),
        "total_params": int(total),
        "trainable_ratio": round(trainable / total, 8) if total else 0.0,
        "only_train_adapter_trainable": bool(only_train_lora),
        "ref_adapter_loaded": packed["ref_adapter_loaded"],
    }

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
                "max_prompt_length": hp["max_prompt_length"],
                "max_completion_length": hp["max_completion_length"],
                "precompute_ref_log_probs": hp["precompute_ref_log_probs"],
                "time": _now(),
            },
        )

    if oom:
        print(json.dumps({"ok": False, "reason": "cuda_oom", "output_dir": str(output_dir)}))
        return 2

    ref_hash_after = _adapter_weight_digest(model, REF_ADAPTER)
    train_hash_after = _adapter_weight_digest(model, TRAIN_ADAPTER)
    ref_unchanged = ref_hash_before == ref_hash_after
    train_changed = train_hash_before != train_hash_after

    global_step = int(trainer.state.global_step)
    # Save only the train adapter as the DPO policy.
    unwrapped = trainer.accelerator.unwrap_model(trainer.model)
    if hasattr(unwrapped, "save_pretrained"):
        try:
            unwrapped.save_pretrained(str(adapter_dir), selected_adapters=[TRAIN_ADAPTER])
        except TypeError:
            unwrapped.set_adapter(TRAIN_ADAPTER)
            unwrapped.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    # Flatten if PEFT nested train/ subdir.
    nested = adapter_dir / TRAIN_ADAPTER
    if nested.is_dir() and (nested / "adapter_model.safetensors").is_file():
        for f in nested.iterdir():
            target = adapter_dir / f.name
            if not target.exists():
                f.replace(target)

    adapter_file = adapter_dir / "adapter_model.safetensors"
    if not adapter_file.is_file():
        # PEFT may write under adapter name folder only
        candidates = list(adapter_dir.rglob("adapter_model.safetensors"))
        adapter_file = candidates[0] if candidates else adapter_file
    adapter_hash = sha_file(adapter_file) if adapter_file.is_file() else None

    history = list(trainer.state.log_history)
    _write_json(output_dir / "history.json", history)
    losses = [h.get("loss") for h in history if isinstance(h.get("loss"), (int, float))]
    grad_norms = [h.get("grad_norm") for h in history if isinstance(h.get("grad_norm"), (int, float))]
    nan = bool(callback.nan) or any(not math.isfinite(float(x)) for x in losses + grad_norms)

    peak_vram = round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1)
    reload_probe: dict[str, Any] = {"skipped": args.mode != "probe"}
    if args.mode == "probe":
        del trainer
        gc.collect()
        torch.cuda.empty_cache()
        try:
            bnb = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            base = AutoModelForCausalLM.from_pretrained(
                str(packed["model_dir"]),
                quantization_config=bnb,
                torch_dtype=torch.bfloat16,
                device_map={"": 0},
                trust_remote_code=True,
            )
            _patch_lm_head(base)
            reload_dir = adapter_file.parent
            reloaded = PeftModel.from_pretrained(base, str(reload_dir))
            # Smoke: one forward logp
            sample = train_rows[0]
            lp = _pair_logps(
                reloaded,
                tokenizer,
                sample,
                max_prompt_length=hp["max_prompt_length"],
                max_completion_length=hp["max_completion_length"],
            )
            reload_probe = {"skipped": False, "ok": True, "sample_logps": lp}
            del reloaded, base
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001
            reload_probe = {"skipped": False, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    n_pairs = len(train_rows)
    effective_batch = hp["accum"]
    updates_est = None
    if args.mode == "formal" and effective_batch > 0:
        updates_est = int(math.ceil(n_pairs / effective_batch) * hp["epochs"])

    summary = {
        "experiment_id": args.experiment_id,
        "mode": args.mode,
        "ok": (
            not nan
            and ref_unchanged
            and (args.mode != "probe" or (train_changed and reload_probe.get("ok", False)))
            and (args.mode != "formal" or train_changed or global_step == 0)
        ),
        "started_at": started,
        "ended_at": _now(),
        "base_model_dir": str(packed["model_dir"]),
        "sft_adapter_dir": str(packed["sft_dir"]),
        "sft_adapter_sha": packed["sft_sha"],
        "dataset_dir": str(dataset_dir),
        "train_samples": n_pairs,
        "meets_target_scale": False,
        "preference_scope": "action_json_only_not_full_trajectory",
        "reference_cache_key": cache["cache_key"],
        "hyperparams": hp,
        "global_step": global_step,
        "updates_estimated": updates_est,
        "trainable": trainable_info,
        "peak_vram_mib": peak_vram,
        "losses": losses,
        "grad_norms": grad_norms,
        "loss_finite": not any(not math.isfinite(float(x)) for x in losses),
        "grad_norm_finite": not any(not math.isfinite(float(x)) for x in grad_norms),
        "nan_detected": nan,
        "reference_hash_before": ref_hash_before,
        "reference_hash_after": ref_hash_after,
        "reference_unchanged": ref_unchanged,
        "train_hash_before": train_hash_before,
        "train_hash_after": train_hash_after,
        "train_changed": train_changed,
        "checkpoints": callback.checkpoints,
        "adapter_dir": str(adapter_dir),
        "adapter_hash": adapter_hash,
        "reload_probe": reload_probe,
    }
    # Formal: train should change; allow edge case of tiny steps
    if args.mode == "formal":
        summary["ok"] = not nan and ref_unchanged and bool(adapter_hash)
    if args.mode == "probe":
        summary["ok"] = (
            not nan
            and ref_unchanged
            and train_changed
            and trainable_info["only_train_adapter_trainable"]
            and reload_probe.get("ok", False)
        )

    _write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(
        "\n".join(
            [
                f"# {args.experiment_id}",
                "",
                f"- mode: {args.mode}",
                f"- train_samples: {n_pairs}",
                f"- meets_target_scale: false",
                f"- global_step: {global_step}",
                f"- reference_unchanged: {ref_unchanged}",
                f"- train_changed: {train_changed}",
                f"- peak_vram_mib: {peak_vram}",
                f"- nan_detected: {nan}",
                f"- adapter_hash: {adapter_hash}",
                f"- cache_key: {cache['cache_key']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "experiment_id",
                    "mode",
                    "ok",
                    "train_samples",
                    "global_step",
                    "peak_vram_mib",
                    "nan_detected",
                    "reference_unchanged",
                    "train_changed",
                    "adapter_hash",
                    "reload_probe",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if summary["ok"] else 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument(
        "--mode",
        choices=["probe", "formal", "validate-cache", "t23"],
        required=True,
    )
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--dataset-dir", type=Path, default=None)
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--sft-adapter-dir", type=Path, default=None)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--adapter-dir", type=Path, default=None)
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--accum", type=int, default=None)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--save-steps", type=int, default=None)
    ap.add_argument("--rebuild-cache", action="store_true")
    args = ap.parse_args()

    if args.mode == "validate-cache":
        return mode_validate_cache(args)
    if args.mode == "t23":
        return mode_t23(args)

    if not args.experiment_id:
        args.experiment_id = "probe_dpo_s37_0001" if args.mode == "probe" else "exp_dpo_0001"

    if args.mode == "probe":
        if args.max_samples is None:
            args.max_samples = 8
        if args.max_steps is None:
            args.max_steps = 4
        if args.epochs is None:
            args.epochs = 1
        if args.accum is None:
            args.accum = 1
        if args.save_steps is None:
            args.save_steps = 0
    else:
        # formal: stick to project.yaml via _resolve_hyperparams; only fill max_steps
        if args.max_steps is None:
            args.max_steps = -1

    return mode_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
