#!/usr/bin/env python3
"""Headless SFT: Ministral-3-3B-Base -> web computer-use agent.

Trains on the web-only subset of xlangai/aguvis-stage2 and writes a merged,
servable bf16 checkpoint. Designed to run detached on a single A100.

Smoke first, then the real run:
    python train_ministral3_cua.py --smoke
    python train_ministral3_cua.py
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download
from PIL import Image
from torch.utils.data import Dataset

BASE_MODEL = "mistralai/Ministral-3-3B-Base-2512"
REPO = "xlangai/aguvis-stage2"

# Both dims divisible by patch_size(14) and by 14*2 for spatial_merge_size=2.
# 1008 = 72 patches, 784 = 56 patches -> merged 36x28 = 1008 vision tokens.
IMAGE_W, IMAGE_H = 1008, 784

# mind2web is on-distribution for Online-Mind2Web, so take all of it.
MIX = {
    "mind2web-l2.json": {"zip": "mind2web.zip", "take": None},
    "guiact-web-single.json": {"zip": "guiact-web-single.zip", "take": 12000},
    "miniwob-l2.json": {"zip": "miniwob.zip", "take": 2500},
}

DATA = Path.home() / "usersim" / "aguvis"
IMG_ROOT = DATA / "images"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- data


def fetch_data(smoke: bool) -> None:
    IMG_ROOT.mkdir(parents=True, exist_ok=True)
    for js, spec in MIX.items():
        hf_hub_download(REPO, js, repo_type="dataset")
        marker = IMG_ROOT / f".done_{spec['zip']}"
        if marker.exists():
            log(f"{spec['zip']} already extracted")
            continue
        if smoke and js != "miniwob-l2.json":
            continue  # smoke only needs the 60 MB zip
        log(f"downloading {spec['zip']} ...")
        zp = hf_hub_download(REPO, spec["zip"], repo_type="dataset")
        log(f"extracting {spec['zip']} ...")
        with zipfile.ZipFile(zp) as z:
            z.extractall(IMG_ROOT)
        marker.touch()


def build_index() -> dict:
    index = {}
    for p in IMG_ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            index.setdefault(p.name, p)
    log(f"indexed {len(index)} images")
    return index


def build_records(index: dict, smoke: bool) -> list[dict]:
    random.seed(0)
    records = []
    for js, spec in MIX.items():
        if smoke and js != "miniwob-l2.json":
            continue
        raw = json.load(open(hf_hub_download(REPO, js, repo_type="dataset")))
        out, missing = [], 0
        for rec in raw:
            img = index.get(rec["image"]) if isinstance(rec["image"], str) else None
            if img is None:
                missing += 1
                continue
            turns = rec["conversations"]
            user = next((t["value"] for t in turns if t["from"] == "human"), "")
            gpt = [t["value"].strip() for t in turns if t["from"] == "gpt" and t["value"].strip()]
            if not user or not gpt:
                continue
            out.append(
                {
                    "image": str(img),
                    "system": next((t["value"] for t in turns if t["from"] == "system"), ""),
                    "user": user.replace("<image>", "[IMG]"),
                    # Records carry a thought turn then an action turn; merge them.
                    "assistant": "\n".join(gpt),
                }
            )
        random.shuffle(out)
        take = 64 if smoke else spec["take"]
        if take:
            out = out[:take]
        log(f"{js}: {len(out)} records (missing images: {missing})")
        records += out
    random.shuffle(records)
    return records


# ---------------------------------------------------------------- model io


def build_prompt(rec: dict) -> str:
    sys_part = f"[SYSTEM_PROMPT]{rec['system']}[/SYSTEM_PROMPT]" if rec["system"] else ""
    return f"{sys_part}[INST]{rec['user']}[/INST]"


class CUADataset(Dataset):
    def __init__(self, recs, processor, end_inst, eos):
        self.recs, self.processor = recs, processor
        self.end_inst, self.eos = end_inst, eos

    def __len__(self):
        return len(self.recs)

    def __getitem__(self, i):
        rec = self.recs[i]
        img = Image.open(rec["image"]).convert("RGB").resize((IMAGE_W, IMAGE_H), Image.BICUBIC)
        enc = self.processor(
            text=build_prompt(rec) + rec["assistant"] + self.eos,
            images=[img],
            return_tensors="pt",
        )
        ids = enc["input_ids"][0]
        labels = ids.clone()
        # Mask the prompt: everything up to and including the final [/INST].
        pos = (ids == self.end_inst).nonzero()
        if len(pos):
            labels[: pos[-1].item() + 1] = -100
        else:
            n = self.processor(text=build_prompt(rec), images=[img], return_tensors="pt")[
                "input_ids"
            ].shape[1]
            labels[:n] = -100

        item = {"input_ids": ids, "labels": labels, "attention_mask": torch.ones_like(ids)}
        for k in ("pixel_values", "image_sizes"):
            if k in enc:
                v = enc[k]
                item[k] = v[0] if (hasattr(v, "shape") and v.shape[0] == 1) else v
        return item


def make_collate(pad_id):
    def collate(batch):
        n = max(b["input_ids"].shape[0] for b in batch)
        out = {}
        for key, fill in (("input_ids", pad_id), ("labels", -100), ("attention_mask", 0)):
            rows = []
            for b in batch:
                t = b[key][:n]
                if t.shape[0] < n:
                    t = torch.cat([t, torch.full((n - t.shape[0],), fill, dtype=t.dtype)])
                rows.append(t)
            out[key] = torch.stack(rows)
        for k in ("pixel_values", "image_sizes"):
            if k in batch[0]:
                try:
                    out[k] = torch.stack([b[k] for b in batch])
                except Exception:
                    out[k] = [b[k] for b in batch]
        return out

    return collate


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="64 samples, few steps, verify end-to-end")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--micro-batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-r", type=int, default=64)
    ap.add_argument("--time-budget-hours", type=float, default=6.0)
    ap.add_argument("--out", default=str(Path.home() / "usersim" / "ministral3-cua"))
    ap.add_argument("--merged", default=str(Path.home() / "usersim" / "Ministral3-3B-CUA-web"))
    ap.add_argument(
        "--gcs",
        default="gs://ai-studio-bucket-347838016394-us-east1/usersim-models/Ministral3-3B-CUA-web",
    )
    ap.add_argument("--shutdown", action="store_true", help="power off the VM when finished")
    args = ap.parse_args()

    log(f"torch {torch.__version__} | cuda {torch.version.cuda}")
    assert torch.cuda.is_available(), "no GPU"
    log(f"{torch.cuda.get_device_name(0)} | bf16={torch.cuda.is_bf16_supported()}")

    fetch_data(args.smoke)
    records = build_records(build_index(), args.smoke)
    n_hold = min(200, max(8, len(records) // 10))
    holdout, records = records[:n_hold], records[n_hold:]
    log(f"TRAIN {len(records)} | HOLDOUT {len(holdout)}")
    assert records, "no training records"

    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoProcessor,
        Mistral3ForConditionalGeneration,
        Trainer,
        TrainerCallback,
        TrainingArguments,
    )

    processor = AutoProcessor.from_pretrained(BASE_MODEL)
    processor.image_processor.size = {"longest_edge": max(IMAGE_W, IMAGE_H)}
    tok = processor.tokenizer
    end_inst = tok.convert_tokens_to_ids("[/INST]")
    eos = tok.eos_token or "</s>"
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0
    log(f"[/INST]={end_inst} pad={pad_id}")

    attn = "sdpa"
    try:
        import flash_attn  # noqa: F401

        attn = "flash_attention_2"
    except Exception:
        pass
    log(f"attention: {attn}")

    try:
        model = Mistral3ForConditionalGeneration.from_pretrained(
            BASE_MODEL, dtype=torch.bfloat16, attn_implementation=attn, device_map="cuda:0"
        )
    except TypeError:
        model = Mistral3ForConditionalGeneration.from_pretrained(
            BASE_MODEL, torch_dtype=torch.bfloat16, attn_implementation=attn, device_map="cuda:0"
        )
    model.config.use_cache = False

    train_ds = CUADataset(records, processor, end_inst, eos)
    probe = train_ds[0]
    supervised = int((probe["labels"] != -100).sum())
    log(f"probe tokens={probe['input_ids'].shape[0]} supervised={supervised}")
    assert supervised > 0, "label masking removed everything"
    log("target: " + tok.decode(probe["input_ids"][probe["labels"] != -100])[:200])

    targets = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    lm_targets = sorted(
        {
            n
            for n, _ in model.named_modules()
            if n.endswith(tuple(targets)) and "vision_tower" not in n
        }
    )
    log(f"{len(lm_targets)} LoRA target modules")
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_r * 2,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=lm_targets,
        ),
    )
    # The projector maps ViT features into the LM space; small and worth training.
    for n, m in model.named_modules():
        if n.endswith("multi_modal_projector"):
            for p in m.parameters():
                p.requires_grad_(True)
    for n, p in model.named_parameters():
        if "vision_tower" in n:
            p.requires_grad_(False)
    # Frozen embeddings + gradient checkpointing starves LoRA of gradient without this.
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    class TimeBudget(TrainerCallback):
        def on_train_begin(self, a, s, c, **kw):
            self.t0 = time.time()

        def on_step_end(self, a, s, c, **kw):
            if time.time() - self.t0 > args.time_budget_hours * 3600:
                log("time budget reached — stopping, model still saves")
                c.should_training_stop = True
            return c

    total_steps = max(1, int(len(train_ds) / (args.micro_batch * args.grad_accum) * args.epochs))
    targs = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        max_steps=4 if args.smoke else -1,
        per_device_train_batch_size=args.micro_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=max(3, int(0.03 * total_steps)),
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch_fused",
        logging_steps=10,
        save_steps=200,
        save_total_limit=2,
        dataloader_num_workers=4,
        remove_unused_columns=False,
        label_names=["labels"],
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=targs,
        train_dataset=train_ds,
        data_collator=make_collate(pad_id),
        callbacks=[TimeBudget()],
    )
    steps = len(train_ds) // (args.micro_batch * args.grad_accum)
    log(f"begin training | ~{steps} optimizer steps")
    t0 = time.time()
    trainer.train()
    log(f"training done in {(time.time()-t0)/3600:.2f} h")

    trainer.save_model(args.out)
    processor.save_pretrained(args.out)

    log("merging LoRA into base weights ...")
    merged = model.merge_and_unload()
    merged.config.use_cache = True
    merged.save_pretrained(args.merged, safe_serialization=True)
    processor.save_pretrained(args.merged)
    log(f"merged checkpoint -> {args.merged}")

    # Quick grounding proxy on held-out data.
    def xy(text):
        m = re.search(r"x=([0-9.]+)\s*,\s*y=([0-9.]+)", text)
        return (float(m.group(1)), float(m.group(2))) if m else None

    hits = tried = parsed = 0
    for rec in holdout[: 10 if args.smoke else 50]:
        gold = xy(rec["assistant"])
        if not gold:
            continue
        im = Image.open(rec["image"]).convert("RGB").resize((IMAGE_W, IMAGE_H), Image.BICUBIC)
        e = processor(text=build_prompt(rec), images=[im], return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            o = merged.generate(**e, max_new_tokens=128, do_sample=False)
        p = tok.decode(o[0][e["input_ids"].shape[1] :], skip_special_tokens=True)
        tried += 1
        pr = xy(p)
        if pr:
            parsed += 1
            if abs(pr[0] - gold[0]) < 0.05 and abs(pr[1] - gold[1]) < 0.05:
                hits += 1
    summary = {
        "train_samples": len(records),
        "parsed": parsed,
        "tried": tried,
        "click_within_5pct": hits,
        "accuracy": hits / max(tried, 1),
    }
    log(f"HOLDOUT {json.dumps(summary)}")
    Path(args.merged, "eval_summary.json").write_text(json.dumps(summary, indent=2))

    if args.gcs and not args.smoke:
        log(f"uploading to {args.gcs} ...")
        subprocess.run(["gsutil", "-m", "cp", "-r", args.merged, args.gcs], check=False)
        # Keep the run log next to the weights; the VM may power off right after.
        train_log = Path.home() / "usersim" / "logs" / "train.log"
        if train_log.exists():
            subprocess.run(["gsutil", "cp", str(train_log), f"{args.gcs}/train.log"], check=False)
        log("upload complete")

    log("ALL DONE")
    if args.shutdown and not args.smoke:
        subprocess.run(["sudo", "shutdown", "-h", "+2"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
