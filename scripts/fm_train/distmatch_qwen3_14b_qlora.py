#!/usr/bin/env python3
"""Distribution-matching QLoRA on Qwen3-14B.

For each seen-study prompt, the target is the empirical distribution of human
answers in that (study, condition, task) cell, not the one sampled response.
Loss is soft cross-entropy over the single-token answers in the cell.

Does not train on the 40 unseen studies. Writes PROGRESS.json every step and
a LoRA checkpoint periodically so a Spot preemption can resume.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import torch

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
CORPUS = Path(os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")))
OUT = Path(os.environ.get("DMOUT", str(ROOT / "adapters" / "qwen3_14b_distmatch")))
RESULTS = Path(os.environ.get("RESULTS_DIR", str(ROOT / "results" / "qwen3_14b_distmatch")))
MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-14B")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "300"))
SAVE_STEPS = int(os.environ.get("SAVE_STEPS", "25"))
LIMIT = int(os.environ.get("LIMIT_ROWS", "4096"))
LR = float(os.environ.get("LR", "1e-4"))
UNSEEN = {
    "326nv", "5vm8g", "w72cz", "5hqan", "rj3aw", "py9kw", "5an26", "jmtyn",
    "kwfs3", "y9nb7", "c5r2f", "3muqx", "s43kb", "xym9d", "vnm9y", "ux8qt",
    "wn3y9", "qkhdg", "jkspw", "tcg8p", "rpw4u", "b3ve6", "ervm8", "a7uk3",
    "c38xe", "8ctbk", "nhgxf", "53kjy", "3rvgz", "zsekp", "7jt2f", "3pcdm",
    "9nphm", "yjvpn", "yp736", "xtvu5", "a5v96", "ak35q", "a693y", "ztwqy",
}
SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)


def load_examples():
    cells: dict[tuple, list] = defaultdict(list)
    with CORPUS.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["study_id"] in UNSEEN:
                raise SystemExit(f"seen corpus contains unseen study {row['study_id']}")
            key = (row["study_id"], str(row["condition_num"]), str(row["task_num"]))
            cells[key].append(row)
    examples = []
    for key, rows in cells.items():
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            counts[str(row["response"]).strip()] += 1
        if len(counts) < 2:
            continue
        total = sum(counts.values())
        dist = {ans: n / total for ans, n in counts.items()}
        for row in rows:
            examples.append({"prompt": row["prompt"], "dist": dist, "study_id": row["study_id"]})
            if len(examples) >= LIMIT:
                return examples
    return examples


def main() -> None:
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    RESULTS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    examples = load_examples()
    print(f"examples={len(examples)} model={MODEL}", flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        MODEL,
        quantization_config=quant,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)
    base.config.use_cache = False
    step = 0
    prior = sorted(OUT.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1]))
    if prior:
        from peft import PeftModel

        model = PeftModel.from_pretrained(base, str(prior[-1]), is_trainable=True)
        step = int(prior[-1].name.split("-")[-1])
        print(f"loaded {prior[-1].name} resume_step={step}", flush=True)
    else:
        model = get_peft_model(
            base,
            LoraConfig(
                r=16,
                lora_alpha=32,
                lora_dropout=0.05,
                bias="none",
                task_type="CAUSAL_LM",
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            ),
        )
    for p in model.parameters():
        if p.requires_grad and p.dtype != torch.float32:
            p.data = p.data.float()
    model.print_trainable_parameters()

    # Keep cells whose answers are a single token so one logit vector is the distribution.
    packed = []
    for ex in examples:
        ids = {}
        ok = True
        for ans in ex["dist"]:
            toks = tok.encode(ans, add_special_tokens=False)
            if len(toks) != 1:
                ok = False
                break
            ids[toks[0]] = ex["dist"][ans]
        if not ok or len(ids) < 2:
            continue
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": ex["prompt"]},
        ]
        prompt = tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        input_ids = tok(prompt, return_tensors="pt", truncation=True, max_length=768).input_ids
        if input_ids.shape[1] < 8:
            continue
        packed.append((input_ids[0], ids, ex["study_id"]))
    print(f"single_token_examples={len(packed)}", flush=True)
    if len(packed) < 32:
        raise SystemExit("too few single-token cells to train")

    opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=LR)
    model.train()
    started = time.time()
    # Step counter follows the loaded checkpoint, not STEP. STEP can sit ahead
    # of the last complete save if the VM stops mid-interval.
    step_path = RESULTS / "STEP"
    print(f"train_from_step={step} max_steps={MAX_STEPS}", flush=True)
    micro = 0
    accum = 8
    opt.zero_grad(set_to_none=True)
    cursor = 0
    while step < MAX_STEPS:
        ids, dist, _study = packed[cursor % len(packed)]
        cursor += 1
        batch = ids.unsqueeze(0).to(model.device)
        out = model(input_ids=batch)
        logits = out.logits[0, -1].float()
        labels = torch.tensor(list(dist.keys()), device=logits.device)
        target = torch.tensor(list(dist.values()), device=logits.device, dtype=torch.float32)
        target = target / target.sum()
        logp = torch.log_softmax(logits[labels], dim=0)
        loss = -(target * logp).sum() / accum
        loss.backward()
        micro += 1
        if micro < accum:
            continue
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        micro = 0
        step += 1
        step_path.write_text(str(step))
        payload = {
            "step": step,
            "max_steps": MAX_STEPS,
            "loss": float(loss.detach().cpu()) * accum,
            "examples": len(packed),
            "lr": LR,
            "elapsed_s": round(time.time() - started, 1),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": MODEL,
            "role": "distmatch_qlora",
        }
        (RESULTS / "PROGRESS.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(payload), flush=True)
        if step % SAVE_STEPS == 0:
            ckpt = OUT / f"checkpoint-{step}"
            model.save_pretrained(ckpt)
            tok.save_pretrained(ckpt)
            print(f"saved {ckpt}", flush=True)
    model.save_pretrained(OUT)
    tok.save_pretrained(OUT)
    (RESULTS / "TRAIN_DONE.json").write_text(
        json.dumps({"adapter": str(OUT), "steps": step, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2)
        + "\n"
    )
    print("TRAIN_DONE", flush=True)


if __name__ == "__main__":
    main()
