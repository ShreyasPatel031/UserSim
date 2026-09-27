#!/usr/bin/env python3
"""Format smoke test: Qwen3-14B distmatch QLoRA checkpoint-1400.

Verifies that every generation parses as a valid answer for its question type.
Uses the SAME model loading approach as training:
- transformers + PEFT (not vLLM)
- bitsandbytes 4-bit quantization
- Qwen/Qwen3-14B base (not FP8)
- enable_thinking=False in chat template

Key fix: training predicts SINGLE TOKENS after the chat template prefix,
so we generate max_new_tokens=1 with greedy decoding (temperature=0).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
RESULTS = Path(os.environ.get("RESULTS_DIR", str(ROOT / "results" / "smoke_format")))
LORA_PATH = os.environ.get("LORA_PATH", str(ROOT / "adapters" / "qwen3_14b_distmatch" / "checkpoint-1400"))
MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-14B")
SAMPLES_PER_TYPE = int(os.environ.get("SAMPLES_PER_TYPE", "20"))
GENS_PER_SAMPLE = int(os.environ.get("GENS_PER_SAMPLE", "3"))

SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)

UNSEEN = {
    "326nv", "5vm8g", "w72cz", "5hqan", "rj3aw", "py9kw", "5an26", "jmtyn",
    "kwfs3", "y9nb7", "c5r2f", "3muqx", "s43kb", "xym9d", "vnm9y", "ux8qt",
    "wn3y9", "qkhdg", "jkspw", "tcg8p", "rpw4u", "b3ve6", "ervm8", "a7uk3",
    "c38xe", "8ctbk", "nhgxf", "53kjy", "3rvgz", "zsekp", "7jt2f", "3pcdm",
    "9nphm", "yjvpn", "yp736", "xtvu5", "a5v96", "ak35q", "a693y", "ztwqy",
}


def classify_question_type(response: str, prompt: str) -> str:
    """Classify question type based on response value and prompt patterns."""
    prompt_lower = prompt.lower()
    try:
        val = float(response)
        is_int = val == int(val)
        
        if is_int and int(val) in [0, 1] and any(x in prompt_lower for x in ["yes", "no", "true", "false"]):
            return "binary_01"
        elif is_int and 1 <= val <= 7 and "1" in prompt and "7" in prompt:
            return "likert_1_7"
        elif is_int and 1 <= val <= 5 and "1" in prompt and "5" in prompt:
            return "likert_1_5"
        elif is_int and 0 <= val <= 100 and any(x in prompt_lower for x in ["percent", "%", "probability"]):
            return "percentage"
        elif is_int:
            return "integer_other"
        else:
            return "continuous"
    except ValueError:
        return "non_numeric"


def is_valid_answer(pred_text: str, qtype: str) -> tuple[bool, float | None]:
    """Check if prediction is valid for the question type. Returns (is_valid, parsed_value)."""
    stripped = (pred_text or "").strip()
    if not stripped:
        return False, None
    
    try:
        val = float(stripped)
    except ValueError:
        match = re.search(r"[-+]?\d*\.?\d+", stripped.replace(",", ""))
        if not match:
            return False, None
        try:
            val = float(match.group(0))
        except ValueError:
            return False, None
    
    if qtype == "binary_01":
        return val in [0, 1, 0.0, 1.0], val
    elif qtype == "likert_1_7":
        return 1 <= val <= 7, val
    elif qtype == "likert_1_5":
        return 1 <= val <= 5, val
    elif qtype == "percentage":
        return 0 <= val <= 100, val
    elif qtype in ["integer_other", "continuous"]:
        return np.isfinite(val), val
    else:
        return False, val


def first_token_is_digit(text: str) -> bool:
    """Check if the first non-whitespace character is a digit."""
    stripped = (text or "").lstrip()
    return bool(stripped) and stripped[0].isdigit()


def bare_numeric(text: str) -> bool:
    """Check if text is a bare number (matches training target format)."""
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", (text or "").strip()))


def main() -> None:
    import torch
    from datasets import load_dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"model={MODEL} lora={LORA_PATH}", flush=True)
    print(f"samples_per_type={SAMPLES_PER_TYPE} gens_per_sample={GENS_PER_SAMPLE}", flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    print("loading base model", flush=True)
    base = AutoModelForCausalLM.from_pretrained(
        MODEL,
        quantization_config=quant,
        torch_dtype=torch.bfloat16,
        device_map={"": 0},
        trust_remote_code=True,
    )
    
    print("loading LoRA adapter", flush=True)
    model = PeftModel.from_pretrained(base, LORA_PATH, is_trainable=False)
    model.eval()

    print("loading SocSci210 unseen studies", flush=True)
    ds = load_dataset("socratesft/SocSci210", split="train")
    unseen_rows = [r for r in ds if r["study_id"] in UNSEEN]
    print(f"unseen_rows={len(unseen_rows)}", flush=True)

    by_type: dict[str, list] = defaultdict(list)
    for r in unseen_rows:
        qtype = classify_question_type(str(r["response"]), r["prompt"])
        by_type[qtype].append(r)
    
    print("\n=== Question Type Distribution ===", flush=True)
    for qtype, rows in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {qtype}: {len(rows)}", flush=True)

    results_by_type: dict[str, dict] = {}
    all_gens = []
    started = time.time()

    for qtype, rows in sorted(by_type.items()):
        if qtype == "non_numeric":
            print(f"\nSkipping non_numeric type", flush=True)
            continue
            
        sampled = rows[:SAMPLES_PER_TYPE]
        print(f"\n=== Testing {qtype}: {len(sampled)} samples ===", flush=True)
        
        type_gens = []
        for rec in sampled:
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": rec["prompt"]},
            ]
            prompt = tok.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=768).to(model.device)
            
            for gen_i in range(GENS_PER_SAMPLE):
                with torch.no_grad():
                    out = model.generate(
                        **inputs,
                        max_new_tokens=1,
                        do_sample=False,
                        pad_token_id=tok.pad_token_id,
                    )
                gen_text = tok.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
                is_valid, parsed = is_valid_answer(gen_text, qtype)
                is_bare = bare_numeric(gen_text)
                is_digit_first = first_token_is_digit(gen_text)
                
                gen_rec = {
                    "study_id": rec["study_id"],
                    "human": rec["response"],
                    "qtype": qtype,
                    "gen_i": gen_i,
                    "pred_raw": gen_text,
                    "pred": parsed,
                    "is_valid": is_valid,
                    "is_bare": is_bare,
                    "first_token_digit": is_digit_first,
                }
                type_gens.append(gen_rec)
                all_gens.append(gen_rec)

        n_gens = len(type_gens)
        n_valid = sum(1 for g in type_gens if g["is_valid"])
        n_bare = sum(1 for g in type_gens if g["is_bare"])
        n_digit_first = sum(1 for g in type_gens if g["first_token_digit"])
        
        results_by_type[qtype] = {
            "n_samples": len(sampled),
            "n_gens": n_gens,
            "n_valid": n_valid,
            "n_bare": n_bare,
            "n_digit_first": n_digit_first,
            "valid_rate": n_valid / n_gens if n_gens else 0,
            "bare_rate": n_bare / n_gens if n_gens else 0,
            "digit_first_rate": n_digit_first / n_gens if n_gens else 0,
            "examples": [{"human": g["human"], "raw": g["pred_raw"], "parsed": g["pred"]} for g in type_gens[:5]],
        }
        
        print(f"  valid={n_valid}/{n_gens} ({100*n_valid/n_gens:.1f}%) "
              f"bare={n_bare}/{n_gens} ({100*n_bare/n_gens:.1f}%) "
              f"digit_first={n_digit_first}/{n_gens} ({100*n_digit_first/n_gens:.1f}%)", flush=True)
        for ex in results_by_type[qtype]["examples"][:3]:
            print(f"    human={ex['human']} raw={repr(ex['raw'])} parsed={ex['parsed']}", flush=True)

    elapsed = time.time() - started
    total_gens = len(all_gens)
    total_valid = sum(1 for g in all_gens if g["is_valid"])
    total_bare = sum(1 for g in all_gens if g["is_bare"])
    total_digit_first = sum(1 for g in all_gens if g["first_token_digit"])
    
    all_valid = all(r["valid_rate"] == 1.0 for r in results_by_type.values())
    
    summary = {
        "model": MODEL,
        "lora": LORA_PATH,
        "role": "format_smoke_test",
        "samples_per_type": SAMPLES_PER_TYPE,
        "gens_per_sample": GENS_PER_SAMPLE,
        "total_gens": total_gens,
        "total_valid": total_valid,
        "total_bare": total_bare,
        "total_digit_first": total_digit_first,
        "overall_valid_rate": total_valid / total_gens if total_gens else 0,
        "overall_bare_rate": total_bare / total_gens if total_gens else 0,
        "overall_digit_first_rate": total_digit_first / total_gens if total_gens else 0,
        "pass": all_valid,
        "by_type": results_by_type,
        "elapsed_s": round(elapsed, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (RESULTS / "generations.jsonl").open("w") as f:
        for g in all_gens:
            f.write(json.dumps(g) + "\n")
    
    print(f"\n=== OVERALL ===", flush=True)
    print(f"Total: {total_valid}/{total_gens} valid ({100*total_valid/total_gens:.1f}%)", flush=True)
    print(f"Bare numeric: {total_bare}/{total_gens} ({100*total_bare/total_gens:.1f}%)", flush=True)
    print(f"First token digit: {total_digit_first}/{total_gens} ({100*total_digit_first/total_gens:.1f}%)", flush=True)
    print(f"PASS: {all_valid}", flush=True)
    print(f"Elapsed: {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
