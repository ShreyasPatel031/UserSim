"""Prompt-based model adapter with a pluggable text backend.

The person's history is rendered as text (bench.HistoryBatch.render: last ~30 endorsed items with title, summary and
topics, plus recent comments), the item as title / summary / description / topics, and the model is asked for JSON
{"p_vote": 0..1, "comment": "..."}. One call per (person, item).

Backends implement `call(prompt: str) -> str` and keep `cost_usd`. Implemented: Gemini on Vertex (via the repo's
src/capability/gemini_config.gemini_chat). Stubs, clearly marked, for Claude, OpenAI and a local open model.

Language models have read about past launches: rank tests must be scored forward or on items after the model's
training cutoff (AGENTS.md, "two models").
"""
from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from simharness.models.base import VoteModel

PROMPT = """You simulate one real Product Hunt member deciding about today's launches.

THIS MEMBER'S HISTORY (everything known before today):
{history}

TODAY'S LAUNCH:
Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}

About 25-40 products launch each day and most members upvote only a few of them, or none.
Estimate the probability that this member upvotes this launch today, and write the one-line comment they would leave
if they commented (in their voice).
Reply with JSON only: {{"p_vote": <number 0-1>, "comment": "<one line>"}}"""


def build_prompt(history_text: str, item) -> str:
    desc = " ".join((item.description or "").split())[:600] or "(none)"
    return PROMPT.format(history=history_text, title=item.title, summary=item.summary, description=desc,
                         tags=", ".join(item.tags) or "(none)")


def parse(text: str) -> tuple[float, str]:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    try:
        p = float(d.get("p_vote", np.nan))
    except (TypeError, ValueError):
        p = np.nan
    return (min(max(p, 0.0), 1.0) if p == p else np.nan), str(d.get("comment", ""))


# ------------------------------------------------------------------------------------------ backends
class Backend:
    name = "backend"
    cost_usd = 0.0
    calls = 0

    def call(self, prompt: str) -> str:
        raise NotImplementedError


class GeminiBackend(Backend):
    """Gemini on Vertex AI. Needs PYTHONPATH to include the repo's src/ and GOOGLE_CLOUD_PROJECT set.

    Cost is estimated from characters (about 4 chars per token) at the list prices passed in (USD per 1M tokens);
    defaults are gemini-2.5-flash-lite list prices."""

    def __init__(self, model: str = "gemini-2.5-flash-lite", price_in: float = 0.10, price_out: float = 0.40,
                 temperature: float = 0.2):
        from capability.gemini_config import gemini_chat  # repo helper (src/ on PYTHONPATH)
        self._chat = gemini_chat
        self.model, self.price_in, self.price_out, self.temperature = model, price_in, price_out, temperature
        self.name = f"gemini:{model}"
        self.tok_in = self.tok_out = 0

    def call(self, prompt: str) -> str:
        out = asyncio.run(self._chat([{"role": "user", "content": prompt}], model=self.model,
                                     temperature=self.temperature, json_mode=True, max_retries=4))
        ti, to = len(prompt) / 4.0, len(out) / 4.0
        self.tok_in += ti; self.tok_out += to; self.calls += 1
        self.cost_usd += ti * self.price_in / 1e6 + to * self.price_out / 1e6
        return out


class ClaudeBackend(Backend):
    """STUB: Claude via Vertex Model Garden (publisher `anthropic`) or the Anthropic API.
    Needs the model enabled in Model Garden for this project (terms accepted by an owner) or an API key.
    Implement: POST {region}-aiplatform.googleapis.com/v1/projects/P/locations/L/publishers/anthropic/models/M:rawPredict
    with an Anthropic Messages body, and track usage.input_tokens / output_tokens for cost."""
    name = "claude:stub"

    def call(self, prompt: str) -> str:
        raise NotImplementedError("ClaudeBackend is a stub: enable Claude in Vertex Model Garden first")


class OpenAIBackend(Backend):
    """STUB: OpenAI chat completions. Needs an API key held as a network secret / Secret Manager secret."""
    name = "openai:stub"

    def call(self, prompt: str) -> str:
        raise NotImplementedError("OpenAIBackend is a stub: no OpenAI access configured")


class LocalOpenModelBackend(Backend):
    """STUB: a local or self-hosted open model (e.g. an OpenAI-compatible vLLM server on our own GPU VM, or a
    Vertex Model Garden open-model endpoint). Fine-tuned weights stay private."""
    name = "open:stub"

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url, self.model = base_url, model

    def call(self, prompt: str) -> str:
        raise NotImplementedError("LocalOpenModelBackend is a stub: point it at a served open model")


# ------------------------------------------------------------------------------------------ model
class PromptVote(VoteModel):
    def __init__(self, backend: Backend, max_items: int = 30, workers: int = 8, cache: dict | None = None):
        self.backend, self.max_items, self.workers = backend, max_items, workers
        self.name = f"prompt[{backend.name}]"
        self.cache = cache if cache is not None else {}
        self.failures = 0

    @property
    def cost_usd(self) -> float:
        return self.backend.cost_usd

    def _one(self, histories, j, item):
        key = (histories.day, int(histories.person_idx[j]), item.item_idx)
        if key not in self.cache:
            prompt = build_prompt(histories.render(j, self.max_items), item)
            try:
                self.cache[key] = parse(self.backend.call(prompt))
            except Exception:  # noqa: BLE001 - one failed call must not stop a run; counted and scored as NaN
                self.failures += 1
                self.cache[key] = (np.nan, "")
        return self.cache[key]

    def score(self, histories, item) -> np.ndarray:
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda j: self._one(histories, j, item), range(len(histories))))
        return np.array([r[0] for r in res], dtype=float)

    def comment(self, histories, j: int, item) -> str:
        return self._one(histories, j, item)[1]
