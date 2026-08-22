#!/usr/bin/env python3
"""Minimal OpenAI-compatible server for Fara1.5-4B via transformers (T4 fallback)."""
from __future__ import annotations

import argparse
import base64
import io
import re
import uuid
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
from transformers import AutoModelForImageTextToText, AutoProcessor

app = FastAPI()
MODEL = None
PROCESSOR = None
MODEL_ID = "Fara1.5-4B"


class ChatRequest(BaseModel):
    model: str
    messages: list
    max_tokens: int = 512
    temperature: float = 0.0


def _b64_to_image(data_url: str) -> Image.Image:
    if data_url.startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _messages_to_chat(messages: list) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        parts = []
        for p in content:
            if p.get("type") == "text":
                parts.append({"type": "text", "text": p.get("text", "")})
            elif p.get("type") == "image_url":
                url = p.get("image_url", {}).get("url", "")
                parts.append({"type": "image", "image": _b64_to_image(url)})
        out.append({"role": role, "content": parts})
    return out


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    messages = _messages_to_chat(req.messages)
    inputs = PROCESSOR.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    )
    inputs = {k: v.to(MODEL.device) for k, v in inputs.items()}
    with torch.inference_mode():
        out = MODEL.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            do_sample=req.temperature > 0,
            temperature=req.temperature or None,
        )
    text = PROCESSOR.decode(out[0], skip_special_tokens=True)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    # Return only the assistant tail if template echoes prompt
    if "<tool_call>" in text:
        text = text[text.rfind("assistant") :] if "assistant" in text else text
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


def main() -> None:
    global MODEL, PROCESSOR, MODEL_ID
    p = argparse.ArgumentParser()
    p.add_argument("--model", type=Path, default=Path.home() / "usersim/models/Fara1.5-4B")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    args = p.parse_args()
    MODEL_ID = args.model.name
    print(f"loading {args.model}", flush=True)
    PROCESSOR = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    load_kwargs: dict = {
        "torch_dtype": torch.bfloat16,
        "device_map": "auto",
        "trust_remote_code": True,
    }
    try:
        from transformers import BitsAndBytesConfig

        load_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        print("using 4-bit quantization", flush=True)
    except Exception:
        print("4-bit unavailable; using bf16", flush=True)
    MODEL = AutoModelForImageTextToText.from_pretrained(args.model, **load_kwargs)
    print(f"ready on :{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
