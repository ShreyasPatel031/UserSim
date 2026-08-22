#!/usr/bin/env python3
"""One-shot vLLM OpenAI-compat smoke test (text + optional image)."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import requests


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    p.add_argument("--model", default=None, help="Model id (defaults to /v1/models first entry)")
    p.add_argument("--image", type=Path, default=None, help="PNG/JPEG for vision smoke")
    p.add_argument("--prompt", default="Say OK in one word.")
    args = p.parse_args()

    models = requests.get(f"{args.base_url}/models", timeout=60).json()
    model = args.model or models["data"][0]["id"]
    print("model:", model, file=sys.stderr)

    content: list[dict] = [{"type": "text", "text": args.prompt}]
    if args.image:
        raw = args.image.read_bytes()
        b64 = base64.standard_b64encode(raw).decode()
        mime = "image/png" if args.image.suffix.lower() == ".png" else "image/jpeg"
        content.insert(0, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 64,
        "temperature": 0,
    }
    r = requests.post(f"{args.base_url}/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
