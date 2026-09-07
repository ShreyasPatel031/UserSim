#!/usr/bin/env python3
"""Minimal OpenAI-compatible chat server for Qwen floor / BehaviorBench."""
from __future__ import annotations

import os
from typing import Any, List, Optional

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = os.environ.get("FLOOR_MODEL", "Qwen/Qwen3-8B-Base")
PORT = int(os.environ.get("PORT", "8000"))

print("Loading", MODEL_ID, flush=True)
tok = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True,
)
model.eval()
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
print("READY", MODEL_ID, "fast=", getattr(tok, "is_fast", None), flush=True)

app = FastAPI()


class Msg(BaseModel):
    role: str
    content: str


class ChatReq(BaseModel):
    model: str = "qwen3-8b-base"
    messages: List[Msg]
    max_tokens: Optional[int] = 64
    temperature: Optional[float] = 0.6
    top_p: Optional[float] = 0.95
    top_k: Optional[int] = 20


def _build_prompt(messages: list[dict[str, str]]) -> str:
    try:
        return tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        parts = []
        for m in messages:
            parts.append(f"{m['role'].upper()}: {m['content']}")
        parts.append("ASSISTANT:")
        return "\n".join(parts)


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"data": [{"id": "qwen3-8b-base", "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
def chat(req: ChatReq) -> dict[str, Any]:
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    prompt = _build_prompt(messages)
    inputs = tok(prompt, return_tensors="pt").to(model.device)
    gen_kwargs: dict[str, Any] = dict(
        max_new_tokens=req.max_tokens or 64,
        do_sample=True,
        temperature=req.temperature if req.temperature is not None else 0.6,
        top_p=req.top_p if req.top_p is not None else 0.95,
        pad_token_id=tok.pad_token_id,
        eos_token_id=tok.eos_token_id,
    )
    if req.top_k:
        gen_kwargs["top_k"] = req.top_k
    with torch.no_grad():
        out = model.generate(**inputs, **gen_kwargs)
    text = tok.decode(out[0][inputs.input_ids.shape[1] :], skip_special_tokens=True)
    return {
        "id": "chatcmpl-qwen-floor",
        "object": "chat.completion",
        "model": req.model or "qwen3-8b-base",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(inputs.input_ids.shape[1]),
            "completion_tokens": 0,
            "total_tokens": int(inputs.input_ids.shape[1]),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
