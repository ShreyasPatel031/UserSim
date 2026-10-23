"""Pure helpers for mcp_study_runner (cost, caps, pilot, retries, prompt cache). No network."""

from __future__ import annotations

import base64
import copy
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

HAIKU_USD_PER_MTOK: dict[str, float] = {
    "input": 1.0,
    "output": 5.0,
    "cache_write_mult": 1.25,
    "cache_read_mult": 0.1,
}

MAX_MODEL_ATTEMPTS = 3
MAX_TOOL_ATTEMPTS = 3
SCREENSHOT_MAX_WIDTH = 1280  # the server's viewport width: the model clicks in the pixels it sees, so never scale below it (Oct 23: 1024 put clicks 20% off, 26 misses on "Accept All")
SCREENSHOT_JPEG_QUALITY = 60
CONDENSE_AFTER_TURNS = 40


def usd_per_mtok(key: str) -> float:
    return HAIKU_USD_PER_MTOK[key] / 1_000_000.0


def usage_to_usd(usage: Any) -> float:
    """Anthropic usage: bill cache write/read separately from remaining input."""
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    regular = max(0, inp - cache_write - cache_read)
    return (
        regular * usd_per_mtok("input")
        + cache_write * usd_per_mtok("input") * HAIKU_USD_PER_MTOK["cache_write_mult"]
        + cache_read * usd_per_mtok("input") * HAIKU_USD_PER_MTOK["cache_read_mult"]
        + out * usd_per_mtok("output")
    )


def usage_cache_fields(usage: Any) -> dict[str, int]:
    return {
        "cache_creation_input_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }


@dataclass
class SpendGate:
    max_usd: float
    max_retries: int
    total_usd: float = 0.0
    retries_used: int = 0
    stopped: bool = False
    stop_reason: str = ""

    def record_usage(self, usage: Any) -> float:
        cost = usage_to_usd(usage)
        self.total_usd += cost
        if self.total_usd >= self.max_usd and not self.stopped:
            self.stopped = True
            self.stop_reason = "runner spend cap"
        return cost

    def record_retry(self) -> bool:
        """Return False when the run-wide retry budget is exhausted."""
        if self.retries_used >= self.max_retries:
            if not self.stopped:
                self.stopped = True
                self.stop_reason = "runner retry budget"
            return False
        self.retries_used += 1
        return True

    def over_cap(self) -> bool:
        return self.stopped or self.total_usd >= self.max_usd


def pilot_cells_for_study(cells: list[dict]) -> list[dict]:
    """One cell per distinct site (target + competitors → typically 3)."""
    seen: set[str] = set()
    out: list[dict] = []
    for c in cells:
        site = (c.get("site") or "").strip()
        if site and site not in seen:
            seen.add(site)
            out.append(c)
    return out


def pilot_should_abort(mean_cell_usd: float, total_cells: int, max_usd: float) -> tuple[bool, float]:
    projected = mean_cell_usd * total_cells
    return projected > max_usd, projected


def is_retryable_error(exc: BaseException) -> bool:
    """Do not retry client/validation failures."""
    s = f"{type(exc).__name__}: {exc}".lower()
    if "validation" in s or "invalid" in s and "request" in s:
        return False
    if re.search(r"\b429\b", s) or "rate limit" in s:
        return True
    for code in ("400", "401", "403", "404", "405", "408", "409", "422"):
        if re.search(rf"\b{code}\b", s) or f"http {code}" in s or f"status {code}" in s:
            return False
    return True


def backoff_seconds(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    return min(cap, base * (2 ** attempt))


def _downscale_image_b64(data_b64: str, media_type: str) -> tuple[str, str]:
    try:
        from PIL import Image
    except ImportError:
        return data_b64, media_type
    raw = base64.b64decode(data_b64)
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size
    if w > SCREENSHOT_MAX_WIDTH:
        nh = max(1, int(h * SCREENSHOT_MAX_WIDTH / w))
        im = im.resize((SCREENSHOT_MAX_WIDTH, nh))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=SCREENSHOT_JPEG_QUALITY)
    return base64.b64encode(out.getvalue()).decode("ascii"), "image/jpeg"


def observation_text_from_blocks(blocks: list[dict]) -> str:
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "text" and b.get("text"):
            parts.append(str(b["text"]))
    return "\n".join(parts)[:4000]


def mcp_content_to_blocks(
    content: list[Any],
    *,
    include_image: bool,
) -> list[dict]:
    """Build tool_result blocks; image only when include_image (newest observe)."""
    out: list[dict] = []
    image_block: dict | None = None
    for c in content:
        ctype = getattr(c, "type", None) or (c.get("type") if isinstance(c, dict) else None)
        if ctype == "text":
            text = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text")
            if text:
                out.append({"type": "text", "text": str(text)})
        elif ctype == "image" and include_image:
            mime = getattr(c, "mimeType", None) or (c.get("mimeType") if isinstance(c, dict) else "image/png")
            data = getattr(c, "data", None) or (c.get("data") if isinstance(c, dict) else "")
            if data:
                data, mime = _downscale_image_b64(str(data), str(mime or "image/png"))
                image_block = {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": data},
                }
    if image_block:
        out.append(image_block)
    return out or [{"type": "text", "text": "(empty)"}]


@dataclass
class TranscriptState:
    """Append-only message list; screenshot injected only on API copy."""

    messages: list[dict] = field(default_factory=list)
    latest_screenshot: dict | None = None
    turn_count: int = 0

    def append_user(self, content: str | list) -> None:
        self.messages.append({"role": "user", "content": content})

    def append_assistant(self, content: list) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def append_observe_tool_result(self, tool_use_id: str, mcp_content: list[Any], *, is_error: bool = False) -> None:
        blocks = mcp_content_to_blocks(mcp_content, include_image=False)
        obs_text = observation_text_from_blocks(blocks)
        if obs_text:
            blocks = [{"type": "text", "text": obs_text}] + [b for b in blocks if b.get("type") != "text"]
        img_blocks = mcp_content_to_blocks(mcp_content, include_image=True)
        for b in img_blocks:
            if b.get("type") == "image":
                self.latest_screenshot = b
                break
        tr: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": blocks}
        if is_error:
            tr["is_error"] = True
        self._append_tool_results([tr])

    def append_tool_result(self, tool_use_id: str, blocks: list[dict], *, is_error: bool = False) -> None:
        tr: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": blocks}
        if is_error:
            tr["is_error"] = True
        self._append_tool_results([tr])

    def _append_tool_results(self, results: list[dict]) -> None:
        last = self.messages[-1] if self.messages else None
        if last and last.get("role") == "user" and isinstance(last.get("content"), list):
            last["content"] = list(last["content"]) + results
        else:
            self.append_user(results)

    def inject_screenshot_for_api(self, msgs: list[dict]) -> list[dict]:
        if not self.latest_screenshot:
            return msgs
        api = copy.deepcopy(msgs)
        for i in range(len(api) - 1, -1, -1):
            msg = api[i]
            if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
                continue
            for j in range(len(msg["content"]) - 1, -1, -1):
                block = msg["content"][j]
                if block.get("type") != "tool_result":
                    continue
                content = list(block.get("content") or [])
                # the API rejects images inside an is_error tool_result (Oct 23 smoke run, 400 at message 58)
                if not block.get("is_error") and not any(x.get("type") == "image" for x in content):
                    content.append(copy.deepcopy(self.latest_screenshot))
                    block["content"] = content
                return api
        return api


def prepare_system(system_text: str) -> list[dict]:
    return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]


def prepare_tools(tools: list[dict]) -> list[dict]:
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def with_rolling_cache_on_last_message(messages: list[dict]) -> list[dict]:
    if not messages:
        return messages
    out = copy.deepcopy(messages)
    last = out[-1]
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
    elif isinstance(content, list) and content:
        block = dict(content[-1])
        block["cache_control"] = {"type": "ephemeral"}
        content = list(content[:-1]) + [block]
        last["content"] = content
    return out


def build_api_messages(state: TranscriptState) -> list[dict]:
    base = state.inject_screenshot_for_api(state.messages)
    return with_rolling_cache_on_last_message(base)


def condense_messages(messages: list[dict], summary: str) -> list[dict]:
    """Start a fresh thread with a summary (append-only policy: replace whole list)."""
    return [
        {
            "role": "user",
            "content": (
                "Continue the browser session. Earlier turns were condensed.\n\n"
                f"Summary:\n{summary}\n\n"
                "Call usersim_observe to see the current page."
            ),
        }
    ]


def summarize_steps(steps: list[dict]) -> str:
    lines = []
    for s in steps[-25:]:
        lines.append(f"turn {s.get('turn')}: {s.get('tool')} {s.get('action') or ''}".strip())
    return "\n".join(lines) or "(no steps yet)"


def snapshot_message_objects(messages: list[dict]) -> list[int]:
    """Identity hashes for append-only tests."""
    return [id(m) for m in messages]
