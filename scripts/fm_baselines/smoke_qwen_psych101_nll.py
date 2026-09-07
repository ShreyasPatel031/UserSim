#!/usr/bin/env python3
"""Smoke: score first N Psych-101 rows with Qwen3-8B-Base; require non-null NLLs."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import torch

N = int(os.environ.get("SMOKE_N", "20"))
MODEL = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
DATA = Path("/opt/usersim_fm/data/Psych-101-test/prompts_testing_t1.jsonl")
SCRIPT = Path("/opt/usersim_fm/scripts/colab_qwen3_8b_floor_psych101_nll.py")


def main() -> None:
    os.environ.setdefault("SKIP_INSTALL", "1")
    spec = importlib.util.spec_from_file_location("floor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    print("Loading", MODEL, flush=True)
    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    print("tokenizer_fast", getattr(tok, "is_fast", None), flush=True)
    # Probe offsets on one short string
    probe = tok("You press <<C>>.", return_offsets_mapping=True, add_special_tokens=False)
    print("offset_probe", list(zip(tok.convert_ids_to_tokens(probe.input_ids), probe["offset_mapping"])), flush=True)

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL,
        quantization_config=quant,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()][:N]
    vals = []
    for i, r in enumerate(rows):
        v = mod.nll_for_text(model, tok, r["text"])
        vals.append(v)
        exp = r["experiment"].split("/")[0]
        print(f"i={i} exp={exp} nll={v}", flush=True)

    ok = [v for v in vals if v is not None]
    mean = sum(ok) / len(ok) if ok else None
    print(
        json.dumps(
            {
                "smoke_n": N,
                "valid": len(ok),
                "null": N - len(ok),
                "mean_nll": mean,
                "model": MODEL,
            },
            indent=2,
        ),
        flush=True,
    )
    if not ok:
        raise SystemExit("SMOKE_FAILED: all nll null")
    print("SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    main()
