#!/usr/bin/env python3
"""Qwen3-8B-Base LoRA SFT kill-test (Be.FM adapter + Centaur masked CE).

Recipe:
  - base: Qwen/Qwen3-8B-Base
  - LoRA r=8 α=32 dropout 0.05 on q/k/v/o/gate/up/down_proj
  - 1 epoch, lr 1e-4, wd 0.01, warmup 100, effective batch 128
  - seq 2048
  - loss only on assistant tokens (response after system\\nuser\\n)

Uses Unsloth when available (Centaur stack); falls back to peft+transformers.
Writes adapter to OUT_DIR (default /opt/usersim_fm/adapters/qwen3_8b_base_pilot).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import torch
from datasets import load_dataset
from transformers import TrainingArguments
from trl import DataCollatorForCompletionOnlyLM, SFTTrainer


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        default=os.environ.get(
            "PILOT_DATA",
            str(Path(__file__).resolve().parents[2] / "data" / "fm_train" / "pilot_corpus.jsonl"),
        ),
    )
    ap.add_argument("--model", default=os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base"))
    ap.add_argument(
        "--out",
        default=os.environ.get(
            "PILOT_OUT",
            "/opt/usersim_fm/adapters/qwen3_8b_base_pilot",
        ),
    )
    ap.add_argument("--max-seq", type=int, default=int(os.environ.get("MAX_SEQ", "2048")))
    ap.add_argument("--epochs", type=float, default=float(os.environ.get("EPOCHS", "1")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "1e-4")))
    ap.add_argument("--wd", type=float, default=float(os.environ.get("WD", "0.01")))
    ap.add_argument("--warmup", type=int, default=int(os.environ.get("WARMUP", "100")))
    ap.add_argument("--micro-batch", type=int, default=int(os.environ.get("MICRO_BATCH", "2")))
    ap.add_argument(
        "--grad-accum",
        type=int,
        default=int(os.environ.get("GRAD_ACCUM", "64")),  # 2*64=128 effective
    )
    ap.add_argument("--lora-r", type=int, default=8)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "-1")))
    return ap.parse_args()


def load_model_and_tokenizer(args: argparse.Namespace):
    target = [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]
    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=args.model,
            max_seq_length=args.max_seq,
            dtype=None,
            load_in_4bit=True,
            trust_remote_code=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=args.lora_r,
            target_modules=target,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=args.seed,
        )
        return model, tokenizer, "unsloth"
    except Exception as exc:  # noqa: BLE001
        print("unsloth unavailable, falling back to peft:", exc, flush=True)
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            quantization_config=bnb,
            device_map="auto",
            trust_remote_code=True,
        )
        model = prepare_model_for_kbit_training(model)
        model = get_peft_model(
            model,
            LoraConfig(
                r=args.lora_r,
                lora_alpha=args.lora_alpha,
                lora_dropout=args.lora_dropout,
                bias="none",
                task_type="CAUSAL_LM",
                target_modules=target,
            ),
        )
        return model, tok, "peft"


def main() -> None:
    args = parse_args()
    data_path = Path(args.data)
    if not data_path.exists():
        raise SystemExit(f"missing corpus: {data_path}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = out_dir / "TRAIN_DONE.json"
    if done.exists():
        print("ALREADY_DONE", done, flush=True)
        return

    print("loading", args.model, "data", data_path, flush=True)
    model, tokenizer, backend = load_model_and_tokenizer(args)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    ds = load_dataset("json", data_files=str(data_path), split="train")

    # Completion-only: mask everything before the assistant answer.
    # Text format is "{system}\n{user}\n{assistant}" — response starts after
    # the second newline following user. We use a response template that is the
    # assistant string's leading bracket form; Centaur-style: find assistant by
    # reconstructing prompt = system+"\n"+user+"\n".
    def formatting(example: dict) -> str:
        return example["text"]

    # Use DataCollatorForCompletionOnlyLM with a unique marker.
    # Inject ASSISTANT_START into texts for masking, strip from saved data? Simpler:
    # reformat on the fly so response template is unambiguous.
    marker = "\n### ASSISTANT\n"

    def map_text(example: dict) -> dict:
        prompt = f"{example['system']}\n{example['user']}{marker}"
        return {"text": prompt + example["assistant"]}

    ds = ds.map(map_text, remove_columns=[c for c in ds.column_names if c != "text"])

    collator = DataCollatorForCompletionOnlyLM(
        response_template=marker,
        tokenizer=tokenizer,
    )

    effective = args.micro_batch * args.grad_accum
    print(
        f"backend={backend} n={len(ds)} micro={args.micro_batch} "
        f"accum={args.grad_accum} effective_batch={effective} lr={args.lr}",
        flush=True,
    )

    targs = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.micro_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        weight_decay=args.wd,
        warmup_steps=args.warmup,
        logging_steps=10,
        save_steps=200,
        save_total_limit=2,
        bf16=torch.cuda.is_available(),
        fp16=False,
        optim="paged_adamw_8bit",
        lr_scheduler_type="cosine",
        report_to=[],
        seed=args.seed,
        max_steps=args.max_steps if args.max_steps > 0 else -1,
        dataloader_num_workers=2,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        dataset_text_field="text",
        max_seq_length=args.max_seq,
        data_collator=collator,
        args=targs,
        packing=False,
    )
    trainer.train()
    model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    meta = {
        "model": args.model,
        "data": str(data_path),
        "n_examples": len(ds),
        "backend": backend,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "lr": args.lr,
        "epochs": args.epochs,
        "effective_batch": effective,
        "max_seq": args.max_seq,
        "out": str(out_dir),
    }
    done.write_text(json.dumps(meta, indent=2) + "\n")
    (out_dir / "train_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("DONE", json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
