#!/usr/bin/env python3
"""Load Fara1.5-4B with transformers (no vLLM) — T4 smoke test."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", type=Path, default=Path.home() / "usersim/models/Fara1.5-4B")
    p.add_argument("--image", type=Path, default=None)
    p.add_argument("--prompt", default="Reply with exactly: OK")
    args = p.parse_args()

    print("loading", args.model, file=sys.stderr)
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    content = [{"type": "text", "text": args.prompt}]
    if args.image:
        content.insert(0, {"type": "image", "image": Image.open(args.image).convert("RGB")})

    messages = [{"role": "user", "content": content}]
    inputs = processor.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    out = model.generate(**inputs, max_new_tokens=32, do_sample=False)
    text = processor.decode(out[0], skip_special_tokens=True)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
