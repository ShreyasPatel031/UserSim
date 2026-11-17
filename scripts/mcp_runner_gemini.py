"""Gemini on Vertex as the per-cell driver of scripts/mcp_study_runner.py (no Claude in pipelines).

The runner keeps its transcript in a provider-neutral block format (text / image / tool_use / tool_result) and calls
``llm.messages.create(model=, max_tokens=, system=, tools=, messages=)``. GeminiDriver offers exactly that call and
translates both ways, so the runner's stop rules, spend cap, pilot, retries and screenshot handling are unchanged:

- screenshots in: the newest screenshot (the runner attaches it to the last tool result) goes in as inline image data;
- one action out: function calling mode ANY (the model must call a tool) and only the first call is returned;
- cost: usage_metadata priced at Vertex gemini-2.5-flash list rates (GEMINI_USD_PER_MTOK), returned as ``usage.usd``
  for the runner's SpendGate.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = "gemini-2.5-flash"
# Vertex list price per 1M tokens, gemini-2.5-flash (text/image input, cached input, output incl. thinking).
GEMINI_USD_PER_MTOK: dict[str, float] = {"input": 0.30, "cached_input": 0.075, "output": 2.50}
THINKING_BUDGET = int(os.environ.get("RUNNER_THINKING_BUDGET", "1024"))

_DROP_SCHEMA_KEYS = {"cache_control"}


def usage_to_usd(meta: Any) -> float:
    """Gemini usage_metadata -> USD. Thinking tokens bill as output; cached prompt tokens at the cached rate."""
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    cached = min(prompt, int(getattr(meta, "cached_content_token_count", 0) or 0))
    out = int(getattr(meta, "candidates_token_count", 0) or 0) + int(getattr(meta, "thoughts_token_count", 0) or 0)
    p = GEMINI_USD_PER_MTOK
    return ((prompt - cached) * p["input"] + cached * p["cached_input"] + out * p["output"]) / 1_000_000


@dataclass
class Usage:
    """What the runner reads off resp.usage (SpendGate uses .usd; usage_cache_fields reads the cache fields)."""

    usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None
    thought_signature: str | None = None  # base64; replayed so Gemini keeps its reasoning across turns

    def model_dump(self, exclude_none: bool = False) -> dict:
        d = {"type": self.type, "text": self.text, "id": self.id, "name": self.name, "input": self.input,
             "thought_signature": self.thought_signature}
        return {k: v for k, v in d.items() if v is not None} if exclude_none else d


@dataclass
class Response:
    content: list[Block]
    usage: Usage
    raw: Any = field(default=None, repr=False)


# ---- requests ----------------------------------------------------------------------------------------------------

def _clean_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k not in _DROP_SCHEMA_KEYS}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def to_gemini_tools(tools: list[dict]) -> list[Any]:
    from google.genai import types

    decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=(t.get("description") or "")[:3000],
            parameters_json_schema=_clean_schema(t.get("input_schema") or {"type": "object", "properties": {}}),
        )
        for t in tools
    ]
    return [types.Tool(function_declarations=decls)]


def _system_text(system: Any) -> str:
    if isinstance(system, str):
        return system
    return "\n".join(b.get("text", "") for b in system or [] if isinstance(b, dict) and b.get("type") == "text")


def _image_part(block: dict) -> Any:
    from google.genai import types

    src = block.get("source") or {}
    return types.Part.from_bytes(data=base64.b64decode(src.get("data") or ""), mime_type=src.get("media_type") or "image/png")


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def to_gemini_contents(messages: list[dict]) -> list[Any]:
    """Runner messages (user/assistant, text/image/tool_use/tool_result blocks) -> Gemini contents (user/model).
    Images inside a tool result follow its function_response in the same user turn. Consecutive turns of one role
    are merged."""
    from google.genai import types

    names: dict[str, str] = {}
    out: list[Any] = []

    def add(role: str, parts: list[Any]) -> None:
        if not parts:
            return
        if out and out[-1].role == role:
            out[-1].parts.extend(parts)
        else:
            out.append(types.Content(role=role, parts=parts))

    for msg in messages:
        role = "model" if msg.get("role") == "assistant" else "user"
        content = msg.get("content")
        if isinstance(content, str):
            add(role, [types.Part.from_text(text=content)] if content else [])
            continue
        parts: list[Any] = []
        for b in content or []:
            kind = b.get("type")
            if kind == "text" and b.get("text"):
                parts.append(types.Part.from_text(text=b["text"]))
            elif kind == "image":
                parts.append(_image_part(b))
            elif kind == "tool_use":
                names[b["id"]] = b["name"]
                part = types.Part(function_call=types.FunctionCall(name=b["name"], args=b.get("input") or {}))
                if b.get("thought_signature"):
                    part.thought_signature = base64.b64decode(b["thought_signature"])
                parts.append(part)
            elif kind == "tool_result":
                name = names.get(b.get("tool_use_id", ""), "tool")
                key = "error" if b.get("is_error") else "output"
                parts.append(types.Part.from_function_response(name=name, response={key: _result_text(b.get("content"))}))
                for inner in b.get("content") or []:
                    if isinstance(inner, dict) and inner.get("type") == "image":
                        parts.append(_image_part(inner))
        add(role, parts)
    return out


# ---- responses ---------------------------------------------------------------------------------------------------

def from_gemini_response(resp: Any) -> Response:
    """First candidate -> blocks. Keeps the text and only the FIRST function call: one action per turn."""
    blocks: list[Block] = []
    cands = getattr(resp, "candidates", None) or []
    parts = (getattr(getattr(cands[0], "content", None), "parts", None) or []) if cands else []
    called = False
    for part in parts:
        if getattr(part, "thought", False):
            continue
        fc = getattr(part, "function_call", None)
        if fc is not None:
            if called:
                continue
            called = True
            sig = getattr(part, "thought_signature", None)
            blocks.append(Block(
                type="tool_use",
                id=getattr(fc, "id", None) or "call_" + uuid.uuid4().hex[:16],
                name=fc.name,
                input=copy.deepcopy(dict(fc.args or {})),
                thought_signature=base64.b64encode(sig).decode() if sig else None,
            ))
        elif getattr(part, "text", None):
            blocks.append(Block(type="text", text=part.text))
    usd = usage_to_usd(getattr(resp, "usage_metadata", None))
    meta = getattr(resp, "usage_metadata", None)
    usage = Usage(
        usd=usd,
        input_tokens=int(getattr(meta, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(meta, "candidates_token_count", 0) or 0) + int(getattr(meta, "thoughts_token_count", 0) or 0),
        cache_read_input_tokens=int(getattr(meta, "cached_content_token_count", 0) or 0),
    )
    return Response(content=blocks, usage=usage, raw=resp)


# ---- driver ------------------------------------------------------------------------------------------------------

class _Messages:
    def __init__(self, driver: "GeminiDriver") -> None:
        self._d = driver

    def create(self, *, model: str, max_tokens: int, system: Any, tools: list[dict], messages: list[dict]) -> Response:
        return self._d.create(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages)


class GeminiDriver:
    """llm.messages.create(...) for the runner, backed by google-genai on Vertex."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.messages = _Messages(self)

    def create(self, *, model: str, max_tokens: int, system: Any, tools: list[dict], messages: list[dict]) -> Response:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=_system_text(system) or None,
            tools=to_gemini_tools(tools),
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=max_tokens + max(0, THINKING_BUDGET),
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
            temperature=0.2,
        )
        resp = self.client.models.generate_content(model=model, contents=to_gemini_contents(messages), config=config)
        return from_gemini_response(resp)


def vertex_client(project: str, location: str = "global") -> Any:
    """google-genai client on Vertex with the repo's credentials (src/auth.py)."""
    from google import genai
    from auth import vertex_credentials

    return genai.Client(vertexai=True, project=project, location=location, credentials=vertex_credentials())


def dumps_for_debug(contents: list[Any]) -> str:
    return json.dumps([c.model_dump(exclude_none=True, mode="json") for c in contents], default=str)[:4000]
