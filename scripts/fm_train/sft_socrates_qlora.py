#!/usr/bin/env python3
"""QLoRA SFT of Qwen3-8B-Base on the SocSci210 seen-study corpus.

Loss is masked to the assistant response tokens only (Centaur/Socrates
convention). Writes PROGRESS.json every logging step so an external watchdog
can tell "training" from "hung", and aborts on non-finite loss instead of
burning hours on a diverged run.

Resume: pass --resume; HF Trainer picks the newest checkpoint in --out.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import torch
from torch.utils.data import Dataset

from socrates_format import render_prompt, render_target

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = ROOT / "results" / "socrates_sft"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")))
    ap.add_argument("--model", default=os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base"))
    ap.add_argument("--out", default=os.environ.get("SFT_OUT", str(ROOT / "adapters" / "socrates_qwen3_8b_qlora")))
    ap.add_argument("--max-seq", type=int, default=int(os.environ.get("MAX_SEQ", "1536")))
    ap.add_argument("--epochs", type=float, default=float(os.environ.get("EPOCHS", "1")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "1e-4")))
    ap.add_argument("--wd", type=float, default=float(os.environ.get("WD", "0.1")))
    ap.add_argument("--warmup-ratio", type=float, default=float(os.environ.get("WARMUP_RATIO", "0.05")))
    ap.add_argument("--micro-batch", type=int, default=int(os.environ.get("MICRO_BATCH", "4")))
    ap.add_argument("--grad-accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "16")))
    ap.add_argument("--lora-r", type=int, default=int(os.environ.get("LORA_R", "16")))
    ap.add_argument("--lora-alpha", type=int, default=int(os.environ.get("LORA_ALPHA", "32")))
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "-1")))
    ap.add_argument("--save-steps", type=int, default=int(os.environ.get("SAVE_STEPS", "200")))
    ap.add_argument("--log-steps", type=int, default=int(os.environ.get("LOG_STEPS", "10")))
    ap.add_argument("--limit-rows", type=int, default=int(os.environ.get("LIMIT_ROWS", "0")))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--resume", action="store_true", default=os.environ.get("RESUME", "1") == "1")
    return ap.parse_args()


class MaskedSFTDataset(Dataset):
    """Tokenize prompt+target, mask labels on the prompt."""

    def __init__(self, rows: list[dict], tok, max_seq: int):
        self.rows = rows
        self.tok = tok
        self.max_seq = max_seq

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> dict:
        row = self.rows[idx]
        prompt = render_prompt(self.tok, row)
        target = render_target(row) + (self.tok.eos_token or "")
        p_ids = self.tok(prompt, add_special_tokens=False)["input_ids"]
        t_ids = self.tok(target, add_special_tokens=False)["input_ids"]
        # Truncate the prompt from the left so the response always survives.
        budget = self.max_seq - len(t_ids)
        if budget < 1:
            t_ids = t_ids[: self.max_seq - 1]
            budget = 1
        if len(p_ids) > budget:
            p_ids = p_ids[-budget:]
        input_ids = p_ids + t_ids
        labels = [-100] * len(p_ids) + list(t_ids)
        return {"input_ids": input_ids, "labels": labels}


class PadCollator:
    def __init__(self, pad_id: int):
        self.pad_id = pad_id

    def __call__(self, feats: list[dict]) -> dict:
        n = max(len(f["input_ids"]) for f in feats)
        input_ids, labels, attn = [], [], []
        for f in feats:
            pad = n - len(f["input_ids"])
            input_ids.append(f["input_ids"] + [self.pad_id] * pad)
            labels.append(f["labels"] + [-100] * pad)
            attn.append([1] * len(f["input_ids"]) + [0] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attn, dtype=torch.long),
        }


def load_rows(path: str, limit: int) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise SystemExit(f"empty corpus: {path}")
    return rows


def build_model(args: argparse.Namespace):
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        torch_dtype=torch.float16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.config.use_cache = False
    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    return model, tok


def main() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from transformers import Trainer, TrainerCallback, TrainingArguments

    rows = load_rows(args.data, args.limit_rows)
    model, tok = build_model(args)
    ds = MaskedSFTDataset(rows, tok, args.max_seq)
    effective = args.micro_batch * args.grad_accum
    print(
        f"rows={len(rows)} micro={args.micro_batch} accum={args.grad_accum} "
        f"effective_batch={effective} lr={args.lr} max_seq={args.max_seq}",
        flush=True,
    )

    started = time.time()

    class Heartbeat(TrainerCallback):
        """Progress file for the watchdog + hard stop on divergence."""

        def on_log(self, cfg, state, control, logs=None, **kw):
            logs = logs or {}
            loss = logs.get("loss")
            payload = {
                "step": state.global_step,
                "max_steps": state.max_steps,
                "epoch": state.epoch,
                "loss": loss,
                "lr": logs.get("learning_rate"),
                "grad_norm": logs.get("grad_norm"),
                "elapsed_s": round(time.time() - started, 1),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "rows": len(rows),
                "effective_batch": effective,
                "model": args.model,
                "diverged": False,
            }
            if loss is not None and (math.isnan(loss) or math.isinf(loss)):
                payload["diverged"] = True
                (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2))
                raise SystemExit(f"loss diverged at step {state.global_step}: {loss}")
            (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2))

    targs = TrainingArguments(
        output_dir=str(out),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.micro_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        weight_decay=args.wd,
        warmup_ratio=args.warmup_ratio,
        lr_scheduler_type="cosine",
        logging_steps=args.log_steps,
        save_steps=args.save_steps,
        save_total_limit=2,
        fp16=True,
        bf16=False,
        optim="paged_adamw_8bit",
        gradient_checkpointing=True,
        report_to=[],
        seed=args.seed,
        dataloader_num_workers=2,
        max_grad_norm=1.0,
        remove_unused_columns=False,
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=ds,
        data_collator=PadCollator(tok.pad_token_id),
        callbacks=[Heartbeat()],
    )

    ckpts = sorted(out.glob("checkpoint-*"))
    resume = args.resume and bool(ckpts)
    print(f"resume={resume} ckpts={[c.name for c in ckpts]}", flush=True)
    trainer.train(resume_from_checkpoint=resume or None)

    trainer.model.save_pretrained(str(out))
    tok.save_pretrained(str(out))
    done = {
        "adapter": str(out),
        "model": args.model,
        "rows": len(rows),
        "epochs": args.epochs,
        "lr": args.lr,
        "wd": args.wd,
        "effective_batch": effective,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "max_seq": args.max_seq,
        "elapsed_s": round(time.time() - started, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (RESULTS / "TRAIN_DONE.json").write_text(json.dumps(done, indent=2) + "\n")
    print(json.dumps(done, indent=2), flush=True)


if __name__ == "__main__":
    main()
