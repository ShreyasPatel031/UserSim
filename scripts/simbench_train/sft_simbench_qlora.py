#!/usr/bin/env python3
"""QLoRA SFT script for Qwen3-14B on SimBench distribution prediction.

Features:
- 4-bit nf4 quantization (fits 1x L4 24GB)
- enable_thinking=False chat template
- Loss options:
  (a) CE on verbalized JSON target only
  (b) (a) + lambda-weighted first-token soft-label KL with FULL-vocabulary softmax
- GCS checkpoint every N steps with auto-resume
- Step-50 format gate (parse rate of 50 sampled generations)
- VM startup and auto-resume pattern from fm-sft-socrates-l4

Usage:
  python sft_simbench_qlora.py --data armA_humandist/train.jsonl --loss ce
  python sft_simbench_qlora.py --data armA_humandist/train.jsonl --loss ce_kl --kl-lambda 0.5
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch
from torch.utils.data import Dataset

# Add eval kit to path for parsing
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "simbench_eval_kit"))

ROOT = Path(os.environ.get("ROOT", "/opt/simbench_train"))
RESULTS = ROOT / "results"
GCS_BUCKET = os.environ.get(
    "GCS_BUCKET", 
    "gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train"
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="Path to train.jsonl")
    ap.add_argument("--val-data", help="Path to val.jsonl (optional)")
    ap.add_argument("--model", default="Qwen/Qwen3-14B")
    ap.add_argument("--out", default=str(ROOT / "adapters" / "simbench_sft"))
    
    # Loss options
    ap.add_argument("--loss", choices=["ce", "ce_kl"], default="ce",
                    help="ce=CE on verbalized target; ce_kl=CE + KL on first token")
    ap.add_argument("--kl-lambda", type=float, default=0.5,
                    help="Weight for first-token KL loss (only for ce_kl)")
    
    # Training hyperparams
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--wd", type=float, default=0.1)
    ap.add_argument("--warmup-ratio", type=float, default=0.05)
    ap.add_argument("--micro-batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--max-steps", type=int, default=1000)
    ap.add_argument("--save-steps", type=int, default=100)
    ap.add_argument("--log-steps", type=int, default=5)
    ap.add_argument("--gate-step", type=int, default=50)
    
    # LoRA config
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    
    # Other
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--limit-rows", type=int, default=0)
    
    return ap.parse_args()


@dataclass
class SimBenchItem:
    """A single training item with both CE and KL targets."""
    source_id: str
    system: str
    user_verbalized: str
    verbalized_target: str
    keys: list[str]
    soft_label: list[float]


def load_data(path: str, limit: int = 0) -> list[SimBenchItem]:
    """Load SimBench format training data."""
    items = []
    with open(path) as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                items.append(SimBenchItem(
                    source_id=d.get("source_id", ""),
                    system=d["system"],
                    user_verbalized=d["user_verbalized"],
                    verbalized_target=d["verbalized_target"],
                    keys=d["keys"],
                    soft_label=d["soft_label"],
                ))
            if limit and len(items) >= limit:
                break
    return items


class SimBenchDataset(Dataset):
    """Dataset for SimBench SFT with CE + optional KL loss."""
    
    def __init__(
        self,
        items: list[SimBenchItem],
        tokenizer,
        max_seq: int,
        compute_kl: bool = False,
    ):
        self.items = items
        self.tok = tokenizer
        self.max_seq = max_seq
        self.compute_kl = compute_kl
        
        # Map option letters to token IDs (for KL computation)
        self.letter_token_ids = {}
        for letter in "ABCDEFGHIJ":
            variants = [letter, f" {letter}", f"({letter}"]
            ids = []
            for v in variants:
                toks = self.tok(v, add_special_tokens=False)["input_ids"]
                if len(toks) == 1:
                    ids.append(toks[0])
            self.letter_token_ids[letter] = ids
    
    def __len__(self) -> int:
        return len(self.items)
    
    def _build_prompt(self, item: SimBenchItem) -> str:
        """Build prompt with enable_thinking=False."""
        messages = [
            {"role": "system", "content": item.system},
            {"role": "user", "content": item.user_verbalized},
        ]
        return self.tok.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    
    def __getitem__(self, idx: int) -> dict:
        item = self.items[idx]
        
        # Build prompt + target
        prompt = self._build_prompt(item)
        target = item.verbalized_target + (self.tok.eos_token or "")
        
        # Tokenize
        prompt_ids = self.tok(prompt, add_special_tokens=False)["input_ids"]
        target_ids = self.tok(target, add_special_tokens=False)["input_ids"]
        
        # Truncate prompt if needed
        budget = self.max_seq - len(target_ids)
        if budget < 1:
            target_ids = target_ids[:self.max_seq - 1]
            budget = 1
        if len(prompt_ids) > budget:
            prompt_ids = prompt_ids[-budget:]
        
        input_ids = prompt_ids + target_ids
        labels = [-100] * len(prompt_ids) + list(target_ids)
        
        result = {
            "input_ids": input_ids,
            "labels": labels,
            "prompt_len": len(prompt_ids),
        }
        
        # Add soft label info for KL loss
        if self.compute_kl:
            result["keys"] = item.keys
            result["soft_label"] = item.soft_label
            result["letter_token_ids"] = [
                self.letter_token_ids.get(k, []) for k in item.keys
            ]
        
        return result


class PadCollator:
    """Collate with left padding for batched inference compatibility."""
    
    def __init__(self, pad_id: int, compute_kl: bool = False):
        self.pad_id = pad_id
        self.compute_kl = compute_kl
    
    def __call__(self, feats: list[dict]) -> dict:
        max_len = max(len(f["input_ids"]) for f in feats)
        
        input_ids, labels, attn, prompt_lens = [], [], [], []
        
        for f in feats:
            pad = max_len - len(f["input_ids"])
            # Left padding
            input_ids.append([self.pad_id] * pad + f["input_ids"])
            labels.append([-100] * pad + f["labels"])
            attn.append([0] * pad + [1] * len(f["input_ids"]))
            prompt_lens.append(pad + f["prompt_len"])
        
        batch = {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attn, dtype=torch.long),
            "prompt_lens": torch.tensor(prompt_lens, dtype=torch.long),
        }
        
        if self.compute_kl:
            # Collect KL-related data
            batch["keys"] = [f["keys"] for f in feats]
            batch["soft_labels"] = [f["soft_label"] for f in feats]
            batch["letter_token_ids"] = [f["letter_token_ids"] for f in feats]
        
        return batch


def compute_kl_loss(
    logits: torch.Tensor,
    prompt_lens: torch.Tensor,
    keys: list[list[str]],
    soft_labels: list[list[float]],
    letter_token_ids: list[list[list[int]]],
) -> torch.Tensor:
    """Compute first-token soft-label KL with FULL-vocabulary softmax.
    
    This is the correct implementation that avoids the subset-softmax bug.
    We compute log_softmax over the FULL vocabulary, then index into the
    answer token positions to get the per-option log probabilities.
    """
    device = logits.device
    batch_size = logits.shape[0]
    
    kl_losses = []
    
    for b in range(batch_size):
        # Get logits at the first-token position (right after prompt)
        first_token_pos = prompt_lens[b].item() - 1  # Position to predict first answer token
        if first_token_pos < 0 or first_token_pos >= logits.shape[1]:
            continue
        
        first_logits = logits[b, first_token_pos]  # [vocab_size]
        
        # FULL-vocabulary log softmax (critical: not subset!)
        log_probs = torch.log_softmax(first_logits, dim=-1)
        
        # Gather log probs for each answer option
        option_log_probs = []
        for key_idx, token_ids in enumerate(letter_token_ids[b]):
            if not token_ids:
                # No valid token IDs for this option, use uniform
                option_log_probs.append(torch.tensor(float("-inf"), device=device))
                continue
            
            # Sum probability mass over all variants (letter, space+letter, (letter)
            probs_for_option = torch.logsumexp(
                torch.stack([log_probs[tid] for tid in token_ids]),
                dim=0
            )
            option_log_probs.append(probs_for_option)
        
        if not option_log_probs:
            continue
        
        # Renormalize over options only (for KL, we compare relative probs)
        option_log_probs = torch.stack(option_log_probs)
        option_log_probs = option_log_probs - torch.logsumexp(option_log_probs, dim=0)
        
        # Target soft labels (human distribution)
        target_probs = torch.tensor(soft_labels[b], device=device, dtype=torch.float32)
        target_probs = target_probs / target_probs.sum()  # Normalize
        target_probs = torch.clamp(target_probs, min=1e-8)  # Avoid log(0)
        
        # Forward KL: sum_x p(x) * (log p(x) - log q(x))
        # Where p = target (human), q = model
        kl = (target_probs * (torch.log(target_probs) - option_log_probs)).sum()
        kl_losses.append(kl)
    
    if not kl_losses:
        return torch.tensor(0.0, device=device)
    
    return torch.stack(kl_losses).mean()


def build_model(args: argparse.Namespace):
    """Build quantized model with LoRA."""
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    
    # 4-bit nf4 quantization
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


def format_gate_check(model, tok, items: list[SimBenchItem], n_samples: int = 50) -> dict:
    """Check parse rate of generated outputs at a checkpoint."""
    from simbench_common import parse_verbalized
    
    model.eval()
    
    valid = 0
    total = 0
    samples = items[:n_samples]
    
    with torch.no_grad():
        for item in samples:
            messages = [
                {"role": "system", "content": item.system},
                {"role": "user", "content": item.user_verbalized},
            ]
            prompt = tok.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            
            inputs = tok(prompt, return_tensors="pt", add_special_tokens=False)
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            
            # Truncate if needed
            if inputs["input_ids"].shape[1] > 512:
                inputs["input_ids"] = inputs["input_ids"][:, -512:]
                inputs["attention_mask"] = inputs["attention_mask"][:, -512:]
            
            outputs = model.generate(
                **inputs,
                max_new_tokens=100,
                do_sample=False,
                pad_token_id=tok.pad_token_id,
            )
            
            gen = tok.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            
            try:
                parse_verbalized(gen, item.keys)
                valid += 1
            except Exception:
                pass
            
            total += 1
    
    model.train()
    
    return {
        "valid": valid,
        "total": total,
        "rate": valid / total if total > 0 else 0,
        "passed": (valid / total) >= 0.95 if total > 0 else False,
    }


def upload_checkpoint(local_path: Path, step: int) -> None:
    """Upload checkpoint to GCS."""
    gcs_path = f"{GCS_BUCKET}/checkpoint-{step}/"
    try:
        subprocess.Popen(
            ["gsutil", "-m", "cp", "-r", f"{local_path}/*", gcs_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"GCS_UPLOAD_STARTED {gcs_path}")
    except Exception as e:
        print(f"GCS_UPLOAD_FAILED {e}")


def download_latest_checkpoint(out: Path) -> Optional[int]:
    """Download latest checkpoint from GCS for resume."""
    try:
        result = subprocess.run(
            ["gsutil", "ls", f"{GCS_BUCKET}/"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return None
        
        # Find latest checkpoint
        checkpoints = []
        for line in result.stdout.strip().split("\n"):
            match = re.search(r"checkpoint-(\d+)/", line)
            if match:
                checkpoints.append(int(match.group(1)))
        
        if not checkpoints:
            return None
        
        latest = max(checkpoints)
        gcs_path = f"{GCS_BUCKET}/checkpoint-{latest}/"
        local_path = out / f"checkpoint-{latest}"
        
        print(f"Downloading checkpoint-{latest} from GCS...")
        local_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["gsutil", "-m", "cp", "-r", f"{gcs_path}*", str(local_path)],
            check=True,
            timeout=300,
        )
        
        return latest
    except Exception as e:
        print(f"Failed to download checkpoint: {e}")
        return None


class SimBenchTrainer:
    """Custom trainer with CE + KL loss support."""
    
    def __init__(
        self,
        model,
        tok,
        train_ds: Dataset,
        collator,
        args: argparse.Namespace,
        items: list[SimBenchItem],
    ):
        self.model = model
        self.tok = tok
        self.train_ds = train_ds
        self.collator = collator
        self.args = args
        self.items = items
        
        self.compute_kl = args.loss == "ce_kl"
        self.kl_lambda = args.kl_lambda
        
        # Setup
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        RESULTS.mkdir(parents=True, exist_ok=True)
        
        self.global_step = 0
        self.best_loss = float("inf")
        self.started = time.time()
    
    def train(self):
        from torch.utils.data import DataLoader
        from torch.optim import AdamW
        from transformers import get_cosine_schedule_with_warmup
        
        # DataLoader
        loader = DataLoader(
            self.train_ds,
            batch_size=self.args.micro_batch,
            shuffle=True,
            collate_fn=self.collator,
            num_workers=2,
            pin_memory=True,
        )
        
        # Optimizer
        optimizer = AdamW(
            self.model.parameters(),
            lr=self.args.lr,
            weight_decay=self.args.wd,
        )
        
        # Scheduler
        num_training_steps = self.args.max_steps
        warmup_steps = int(num_training_steps * self.args.warmup_ratio)
        scheduler = get_cosine_schedule_with_warmup(
            optimizer,
            num_warmup_steps=warmup_steps,
            num_training_steps=num_training_steps,
        )
        
        # Resume
        if self.args.resume:
            latest = download_latest_checkpoint(self.out)
            if latest:
                self.global_step = latest
                print(f"Resuming from step {latest}")
        
        # Training loop
        self.model.train()
        accum_loss = 0.0
        accum_ce_loss = 0.0
        accum_kl_loss = 0.0
        accum_steps = 0
        
        data_iter = iter(loader)
        
        while self.global_step < self.args.max_steps:
            # Get batch
            try:
                batch = next(data_iter)
            except StopIteration:
                data_iter = iter(loader)
                batch = next(data_iter)
            
            # Forward
            input_ids = batch["input_ids"].to(self.model.device)
            labels = batch["labels"].to(self.model.device)
            attention_mask = batch["attention_mask"].to(self.model.device)
            
            outputs = self.model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )
            
            ce_loss = outputs.loss
            total_loss = ce_loss
            kl_loss = torch.tensor(0.0)
            
            # KL loss
            if self.compute_kl:
                kl_loss = compute_kl_loss(
                    outputs.logits,
                    batch["prompt_lens"].to(self.model.device),
                    batch["keys"],
                    batch["soft_labels"],
                    batch["letter_token_ids"],
                )
                total_loss = ce_loss + self.kl_lambda * kl_loss
            
            # Backward
            (total_loss / self.args.grad_accum).backward()
            
            accum_loss += total_loss.item()
            accum_ce_loss += ce_loss.item()
            accum_kl_loss += kl_loss.item()
            accum_steps += 1
            
            # Optimizer step
            if accum_steps >= self.args.grad_accum:
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                
                self.global_step += 1
                
                # Logging
                if self.global_step % self.args.log_steps == 0:
                    avg_loss = accum_loss / accum_steps
                    avg_ce = accum_ce_loss / accum_steps
                    avg_kl = accum_kl_loss / accum_steps
                    
                    progress = {
                        "step": self.global_step,
                        "loss": round(avg_loss, 4),
                        "ce_loss": round(avg_ce, 4),
                        "kl_loss": round(avg_kl, 4),
                        "lr": scheduler.get_last_lr()[0],
                        "elapsed_s": round(time.time() - self.started, 1),
                    }
                    
                    print(f"Step {self.global_step}: loss={avg_loss:.4f} "
                          f"ce={avg_ce:.4f} kl={avg_kl:.4f}")
                    
                    (RESULTS / "PROGRESS.json").write_text(
                        json.dumps(progress, indent=2)
                    )
                
                accum_loss = 0.0
                accum_ce_loss = 0.0
                accum_kl_loss = 0.0
                accum_steps = 0
                
                # Format gate check
                if self.global_step == self.args.gate_step:
                    print(f"\nRunning format gate check at step {self.global_step}...")
                    gate = format_gate_check(self.model, self.tok, self.items)
                    print(f"GATE: parse_rate={gate['rate']:.1%} "
                          f"({'PASS' if gate['passed'] else 'FAIL'})")
                    
                    (RESULTS / "GATE.json").write_text(json.dumps(gate, indent=2))
                    
                    if not gate["passed"]:
                        print("WARNING: Format gate FAILED!")
                
                # Save checkpoint
                if self.global_step % self.args.save_steps == 0:
                    ckpt_path = self.out / f"checkpoint-{self.global_step}"
                    ckpt_path.mkdir(parents=True, exist_ok=True)
                    
                    self.model.save_pretrained(str(ckpt_path))
                    self.tok.save_pretrained(str(ckpt_path))
                    
                    upload_checkpoint(ckpt_path, self.global_step)
        
        # Final save
        self.model.save_pretrained(str(self.out))
        self.tok.save_pretrained(str(self.out))
        upload_checkpoint(self.out, self.global_step)
        
        done = {
            "adapter": str(self.out),
            "model": self.args.model,
            "loss_type": self.args.loss,
            "kl_lambda": self.kl_lambda if self.compute_kl else None,
            "steps": self.global_step,
            "elapsed_s": round(time.time() - self.started, 1),
        }
        
        (RESULTS / "TRAIN_DONE.json").write_text(json.dumps(done, indent=2))
        print(f"\nTraining complete: {json.dumps(done, indent=2)}")


def main():
    args = parse_args()
    
    print(f"SimBench QLoRA SFT")
    print(f"  Data: {args.data}")
    print(f"  Model: {args.model}")
    print(f"  Loss: {args.loss}" + (f" (lambda={args.kl_lambda})" if args.loss == "ce_kl" else ""))
    print(f"  Max steps: {args.max_steps}")
    print()
    
    # Load data
    items = load_data(args.data, args.limit_rows)
    print(f"Loaded {len(items)} training items")
    
    # Build model
    model, tok = build_model(args)
    
    # Dataset
    compute_kl = args.loss == "ce_kl"
    train_ds = SimBenchDataset(items, tok, args.max_seq, compute_kl=compute_kl)
    collator = PadCollator(tok.pad_token_id, compute_kl=compute_kl)
    
    # Train
    trainer = SimBenchTrainer(model, tok, train_ds, collator, args, items)
    trainer.train()


if __name__ == "__main__":
    main()
