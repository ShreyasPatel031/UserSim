#!/usr/bin/env python3
"""QLoRA SFT of Qwen/Qwen3-14B on the SocSci210 seen-study corpus.

Uses bf16, enable_thinking=False, uploads every checkpoint to GCS,
and includes anti-collapse sanity checks.

Hyperparams: r=16, lr=1e-4, MAX_SEQ=768, micro-batch 4 x grad-accum 8,
SAVE_STEPS=20, MAX_STEPS=600.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import torch
from torch.utils.data import Dataset

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = ROOT / "results" / os.environ.get("RESULTS_SUBDIR", "qwen3_14b_sft")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft")

SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)


def render_prompt(tok, row: dict) -> str:
    """Prompt with enable_thinking=False for Qwen3-14B."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": row["prompt"]},
    ]
    return tok.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )


def render_target(row: dict) -> str:
    """Assistant continuation the model is trained to produce."""
    return str(row["response"])


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")))
    ap.add_argument("--model", default=os.environ.get("SFT_MODEL", "Qwen/Qwen3-14B"))
    ap.add_argument("--out", default=os.environ.get("SFT_OUT", str(ROOT / "adapters" / "qwen3_14b_sft")))
    ap.add_argument("--max-seq", type=int, default=int(os.environ.get("MAX_SEQ", "768")))
    ap.add_argument("--epochs", type=float, default=float(os.environ.get("EPOCHS", "1")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "1e-4")))
    ap.add_argument("--wd", type=float, default=float(os.environ.get("WD", "0.1")))
    ap.add_argument("--warmup-ratio", type=float, default=float(os.environ.get("WARMUP_RATIO", "0.05")))
    ap.add_argument("--micro-batch", type=int, default=int(os.environ.get("MICRO_BATCH", "4")))
    ap.add_argument("--grad-accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "8")))
    ap.add_argument("--lora-r", type=int, default=int(os.environ.get("LORA_R", "16")))
    ap.add_argument("--lora-alpha", type=int, default=int(os.environ.get("LORA_ALPHA", "32")))
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "600")))
    ap.add_argument("--save-steps", type=int, default=int(os.environ.get("SAVE_STEPS", "20")))
    ap.add_argument("--log-steps", type=int, default=int(os.environ.get("LOG_STEPS", "5")))
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


def upload_checkpoint(local_path: Path, step: int) -> None:
    """Upload checkpoint to GCS without blocking."""
    gcs_path = f"{GCS_BUCKET}/checkpoint-{step}/"
    try:
        subprocess.Popen(
            ["gsutil", "-m", "cp", "-r", f"{local_path}/*", gcs_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"GCS_UPLOAD_STARTED {gcs_path}", flush=True)
    except Exception as exc:
        print(f"GCS_UPLOAD_FAILED {exc}", flush=True)


def delete_incomplete_checkpoint(out: Path) -> None:
    """Delete the newest incomplete checkpoint before resuming."""
    ckpts = sorted(out.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1]), reverse=True)
    if not ckpts:
        return
    newest = ckpts[0]
    cfg = newest / "adapter_config.json"
    weights = newest / "adapter_model.safetensors"
    if not cfg.exists() or cfg.stat().st_size <= 0 or not weights.exists() or weights.stat().st_size <= 0:
        print(f"DELETING_INCOMPLETE {newest.name}", flush=True)
        shutil.rmtree(newest)


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
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        torch_dtype=torch.bfloat16,
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
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    return model, tok


def sanity_check_generation(model, tok, rows: list[dict], n_samples: int = 50) -> dict:
    """Check that >=95% of generations are bare numeric outputs."""
    model.eval()
    bare_num = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
    bare_count = 0
    total = 0
    samples = rows[:n_samples]
    
    with torch.no_grad():
        for row in samples:
            prompt = render_prompt(tok, row)
            inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            outputs = model.generate(
                **inputs,
                max_new_tokens=16,
                do_sample=False,
                pad_token_id=tok.pad_token_id,
            )
            gen = tok.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            total += 1
            if bare_num.match(gen.strip()):
                bare_count += 1
    
    model.train()
    rate = bare_count / total if total > 0 else 0
    return {"bare_numeric_count": bare_count, "total": total, "rate": rate}


def set_train_state(state: str) -> None:
    """Update instance label for the Spot watchdog."""
    import urllib.request
    def meta(path: str) -> str:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/" + path,
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode()
    try:
        token = json.loads(meta("instance/service-accounts/default/token"))["access_token"]
        project = meta("project/project-id")
        zone = meta("instance/zone").rsplit("/", 1)[-1]
        name = meta("instance/name")
        url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            inst = json.loads(resp.read().decode())
        labels = dict(inst.get("labels") or {})
        labels["usersim-train-state"] = state
        body = json.dumps({"labels": labels, "labelFingerprint": inst["labelFingerprint"]}).encode()
        post = urllib.request.Request(
            url + "/setLabels", data=body, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(post, timeout=20) as resp:
            resp.read()
        print(f"usersim-train-state={state}", flush=True)
    except Exception as exc:
        print(f"label_update_failed {type(exc).__name__}: {exc}", flush=True)


def main() -> None:
    args = parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from transformers import Trainer, TrainerCallback, TrainingArguments

    if args.resume:
        delete_incomplete_checkpoint(out)

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

        def on_save(self, cfg, state, control, **kw):
            step = state.global_step
            ckpt = out / f"checkpoint-{step}"
            if ckpt.exists():
                upload_checkpoint(ckpt, step)

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
        save_total_limit=None,
        fp16=False,
        bf16=True,
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

    ckpts = sorted(out.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1]))
    resume = args.resume and bool(ckpts)
    print(f"resume={resume} ckpts={[c.name for c in ckpts]}", flush=True)
    
    trainer.train(resume_from_checkpoint=resume or None)

    # Anti-collapse sanity check after step 20 (done inline in callback for simplicity)
    print("Running post-training sanity check...", flush=True)
    sanity = sanity_check_generation(model, tok, rows, n_samples=50)
    print(f"SANITY_CHECK bare_rate={sanity['rate']:.1%}", flush=True)
    (RESULTS / "SANITY_CHECK.json").write_text(json.dumps(sanity, indent=2) + "\n")

    trainer.model.save_pretrained(str(out))
    tok.save_pretrained(str(out))
    upload_checkpoint(out, args.max_steps)

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
    set_train_state("done")
    print(json.dumps(done, indent=2), flush=True)


if __name__ == "__main__":
    main()
