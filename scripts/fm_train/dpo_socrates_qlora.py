#!/usr/bin/env python3
"""QLoRA DPO of Qwen3-8B-Base starting from the Socrates SFT adapter (ckpt-425).

Paper recipe: demographic-contrastive pairs, lr=1e-6, reference = SFT policy.
Uses TRL DPOTrainer. With a PeftModel and ref_model=None, TRL disables the
adapter for the reference log-probs (no second copy of the base in VRAM).

Writes PROGRESS.json every log step for the on-VM watchdog.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import torch
from datasets import Dataset

from socrates_format import SYSTEM, build_messages

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = ROOT / "results" / "socrates_dpo"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        default=os.environ.get("DPO_CORPUS", str(ROOT / "data" / "socrates_dpo_pairs.jsonl")),
    )
    ap.add_argument("--model", default=os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base"))
    ap.add_argument(
        "--sft-adapter",
        default=os.environ.get(
            "SFT_ADAPTER",
            str(ROOT / "adapters" / "socrates_qwen3_8b_qlora" / "checkpoint-425"),
        ),
        help="Frozen SFT reference + DPO init. Must be checkpoint-425, not 1175.",
    )
    ap.add_argument(
        "--out",
        default=os.environ.get("DPO_OUT", str(ROOT / "adapters" / "socrates_qwen3_8b_dpo")),
    )
    ap.add_argument("--max-seq", type=int, default=int(os.environ.get("MAX_SEQ", "1536")))
    ap.add_argument("--epochs", type=float, default=float(os.environ.get("EPOCHS", "1")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "1e-6")))
    ap.add_argument("--wd", type=float, default=float(os.environ.get("WD", "0.1")))
    ap.add_argument("--warmup-ratio", type=float, default=float(os.environ.get("WARMUP_RATIO", "0.05")))
    ap.add_argument("--micro-batch", type=int, default=int(os.environ.get("MICRO_BATCH", "1")))
    ap.add_argument("--grad-accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "64")))
    ap.add_argument("--beta", type=float, default=float(os.environ.get("DPO_BETA", "0.1")))
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "-1")))
    ap.add_argument("--save-steps", type=int, default=int(os.environ.get("SAVE_STEPS", "25")))
    ap.add_argument("--log-steps", type=int, default=int(os.environ.get("LOG_STEPS", "10")))
    ap.add_argument("--limit-rows", type=int, default=int(os.environ.get("LIMIT_ROWS", "0")))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--resume",
        action="store_true",
        default=os.environ.get("RESUME", "1") == "1",
    )
    return ap.parse_args()


def load_pairs(path: str, limit: int) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise SystemExit(f"empty DPO corpus: {path}")
    return rows


def to_trl_dataset(rows: list[dict], tok) -> Dataset:
    """TRL expects prompt / chosen / rejected as chat-templated strings.

    Prompt must end ready for the assistant turn; chosen/rejected are the
    bare response strings (paper: single number). TRL concatenates them.
    """

    def render_prompt(prompt: str) -> str:
        msgs = build_messages({"prompt": prompt})
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)

    records = {
        "prompt": [render_prompt(r["prompt"]) for r in rows],
        "chosen": [str(r["chosen"]) for r in rows],
        "rejected": [str(r["rejected"]) for r in rows],
    }
    # Format smoke hook: SYSTEM must appear in every rendered prompt.
    if not all(SYSTEM.split()[0] in p for p in records["prompt"][:8]):
        raise SystemExit("rendered DPO prompts missing SYSTEM preamble")
    return Dataset.from_dict(records)


def build_policy(args: argparse.Namespace):
    from peft import PeftModel, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    adapter = Path(args.sft_adapter)
    if not adapter.exists():
        raise SystemExit(f"SFT adapter missing: {adapter}")
    # Refuse known-worse later ckpts by name.
    if "1175" in adapter.name or "1175" in str(adapter):
        raise SystemExit(f"refusing to start DPO from worse ckpt: {adapter}")

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        torch_dtype=torch.float16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)
    base.config.use_cache = False
    model = PeftModel.from_pretrained(base, str(adapter), is_trainable=True)
    model.print_trainable_parameters()
    return model, tok


def main() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from trl import DPOConfig, DPOTrainer
    from transformers import TrainerCallback

    rows = load_pairs(args.data, args.limit_rows)
    model, tok = build_policy(args)
    ds = to_trl_dataset(rows, tok)
    effective = args.micro_batch * args.grad_accum
    print(
        f"pairs={len(rows)} micro={args.micro_batch} accum={args.grad_accum} "
        f"effective_batch={effective} lr={args.lr} beta={args.beta} "
        f"sft_adapter={args.sft_adapter}",
        flush=True,
    )

    started = time.time()

    class Heartbeat(TrainerCallback):
        last_loss: float | None = None

        def on_log(self, cfg, state, control, logs=None, **kw):
            logs = logs or {}
            loss = logs.get("loss", logs.get("train_loss"))
            if loss is None:
                loss = self.last_loss
            else:
                self.last_loss = loss
            payload = {
                "step": state.global_step,
                "max_steps": state.max_steps,
                "epoch": state.epoch,
                "loss": loss,
                "rewards/accuracies": logs.get("rewards/accuracies"),
                "rewards/margins": logs.get("rewards/margins"),
                "lr": logs.get("learning_rate"),
                "grad_norm": logs.get("grad_norm"),
                "elapsed_s": round(time.time() - started, 1),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "pairs": len(rows),
                "effective_batch": effective,
                "sft_adapter": args.sft_adapter,
                "diverged": False,
                "role": "dpo",
            }
            if loss is not None and (math.isnan(loss) or math.isinf(loss)):
                payload["diverged"] = True
                (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2))
                raise SystemExit(f"DPO loss diverged at step {state.global_step}: {loss}")
            (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2))

    # DPOConfig subclasses TrainingArguments in recent TRL.
    targs = DPOConfig(
        output_dir=str(out),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps if args.max_steps > 0 else -1,
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
        beta=args.beta,
        max_length=args.max_seq,
        max_prompt_length=args.max_seq - 32,
        dataset_num_proc=1,
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,  # PEFT: disable adapter for reference logprobs
        args=targs,
        train_dataset=ds,
        processing_class=tok,
        callbacks=[Heartbeat()],
    )

    ckpts = sorted(out.glob("checkpoint-*"))
    resume = args.resume and bool(ckpts)
    print(f"resume={resume} ckpts={[c.name for c in ckpts]}", flush=True)
    trainer.train(resume_from_checkpoint=True if resume else None)

    trainer.model.save_pretrained(str(out))
    tok.save_pretrained(str(out))
    done = {
        "adapter": str(out),
        "model": args.model,
        "sft_adapter": args.sft_adapter,
        "pairs": len(rows),
        "epochs": args.epochs,
        "lr": args.lr,
        "beta": args.beta,
        "wd": args.wd,
        "effective_batch": effective,
        "max_seq": args.max_seq,
        "elapsed_s": round(time.time() - started, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "role": "dpo",
    }
    (RESULTS / "TRAIN_DONE.json").write_text(json.dumps(done, indent=2) + "\n")
    print(json.dumps(done, indent=2), flush=True)


if __name__ == "__main__":
    main()
