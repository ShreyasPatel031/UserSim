"""Prompt-based model adapter with a pluggable text backend.

The person's history is rendered as text (bench.HistoryBatch.render: activity rates over the last 7 / 30 / 60 days,
comment count, top topics, the last ~30 endorsed items with title, summary and topics, recent comments with @handles
removed), the item as it is known at the start of its day (name, tagline, topics), and the model is asked for JSON
{"p_vote": 0..1, "comment": "..."}. One call per (person, item). Nothing dated on or after the item's day enters a
prompt: no vote counts, comments or ranks of the item.

Backends implement `call(prompt: str) -> str` and keep `cost_usd`, token counts and latencies. Implemented (Vertex AI,
one service-account token): `VertexGemini`, `VertexClaude` (publisher anthropic, rawPredict), `VertexOpenAICompat`
(Model Garden MaaS open models such as gpt-oss-120b and Llama 4 Maverick), and `OpenAICompat` for any
OpenAI-compatible server (a vLLM on our own GPU VM serving a fine-tuned open model). `OpenAIBackend` (OpenAI's own
API) is a stub: no key is configured. A shared `Budget` stops every backend at a dollar cap. `JsonlCache` keeps every
call result on disk in append-only part files, so a restart never repeats a paid call.

Prices are list prices per 1M tokens as known on 2026-11-24 (PRICES below); check them before a large run.

Language models have read about past launches: rank tests must be scored forward or on items after the model's
training cutoff (AGENTS.md, "two models").
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from simharness.bench import scrub
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

PROMPT_V2_HEAD = """You simulate one real Product Hunt member deciding about one of today's launches.

THIS MEMBER (everything known before today, newest first):
{history}

TODAY'S LAUNCH (as listed at the start of the day):
Name: {title}
Tagline: {summary}
Topics: {tags}

Use the member's activity rate (how many launches they upvote per week) and how well this launch fits what they have
upvoted and written before. About 20-60 products launch each day.
"""

PROMPT_V2_TAIL = """Estimate the probability that this member upvotes this launch today. Also give the one-line comment (max 20 words)
they would write if they commented.
Reply with JSON only: {{"p_vote": <number 0-1>, "comment": "<one line>"}}"""

PROMPT_YN_TAIL = ("Use the member's activity rate (how many launches they upvote per week) and how well this launch "
                  "fits what they have upvoted and written before.\n"
                  "Will this member upvote this launch today? Answer with one word: yes or no.")


def build_prompt(history_text: str, item, version: int = 1) -> str:
    """version 1: v0 prompt; 2: activity-aware prompt (JSON p_vote + comment); 3: the same as 2 but answered yes/no
    (the supervised-tuning format)."""
    tags = ", ".join(item.tags) or "(none)"
    if version in (2, 3):  # @handles in launch text are removed, as they are in the history
        head = PROMPT_V2_HEAD.format(history=history_text, title=scrub(item.title), summary=scrub(item.summary),
                                     tags=tags)
        if version == 2:
            return head + PROMPT_V2_TAIL.format()
        return head.split("Use the member's activity rate")[0] + PROMPT_YN_TAIL
    desc = " ".join((item.description or "").split())[:600] or "(none)"
    return PROMPT.format(history=history_text, title=item.title, summary=item.summary, description=desc, tags=tags)


def parse(text: str) -> tuple[float, str]:
    m = re.search(r"\{[^{}]*\"p_vote\"[^{}]*\}", text or "", re.S) or re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    try:
        p = float(d.get("p_vote", np.nan))
    except (TypeError, ValueError):
        p = np.nan
    if p != p and text:  # fall back to a bare number after p_vote
        mm = re.search(r"p_vote\W+([01](?:\.\d+)?)", text)
        p = float(mm.group(1)) if mm else np.nan
    return (min(max(p, 0.0), 1.0) if p == p else np.nan), str(d.get("comment", ""))


# ------------------------------------------------------------------------------------------ budget and cache
class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """A dollar cap shared by backends. Each call reserves its worst-case cost first, so the cap is never passed."""

    def __init__(self, cap_usd: float, spent: float = 0.0):
        self.cap, self.spent, self.lines = cap_usd, spent, {}
        self._lock = threading.Lock()

    def reserve(self, usd: float) -> None:
        with self._lock:
            if self.spent + usd > self.cap:
                raise BudgetExceeded(f"budget cap ${self.cap:.2f} reached (spent ${self.spent:.4f})")
            self.spent += usd

    def settle(self, name: str, reserved: float, actual: float) -> None:
        with self._lock:
            self.spent += actual - reserved
            self.lines[name] = self.lines.get(name, 0.0) + actual


class JsonlCache:
    """Append-only call cache: {key: value} rows in part files under a directory. `roll()` closes the current part
    and returns its path (upload it somewhere durable); loading reads every part. Keys are JSON lists."""

    def __init__(self, directory: str):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.data, self._lock, self._f, self._n = {}, threading.Lock(), None, 0
        for f in sorted(glob.glob(os.path.join(directory, "part-*.jsonl"))):
            for line in open(f):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                self.data[tuple(r["k"])] = r["v"]
        self._part = len(glob.glob(os.path.join(directory, "part-*.jsonl")))

    def __contains__(self, key):
        return tuple(key) in self.data

    def __getitem__(self, key):
        return self.data[tuple(key)]

    def __setitem__(self, key, value):
        with self._lock:
            self.data[tuple(key)] = value
            if self._f is None:
                self._path = os.path.join(self.dir, f"part-{self._part:05d}-{int(time.time())}.jsonl")
                self._f = open(self._path, "a")
            self._f.write(json.dumps({"k": list(key), "v": value}) + "\n")
            self._f.flush()
            self._n += 1

    def roll(self) -> str | None:
        with self._lock:
            if self._f is None:
                return None
            self._f.close()
            path, self._f, self._n = self._path, None, 0
            self._part += 1
            return path


# ------------------------------------------------------------------------------------------ backends
# USD per 1M tokens (input, output). Thinking / reasoning tokens bill as output.
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40),
    "claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-4-5": (3.00, 15.00), "claude-sonnet-4-6": (3.00, 15.00),
    "openai/gpt-oss-120b-maas": (0.15, 0.60), "meta/llama-4-maverick-17b-128e-instruct-maas": (0.35, 1.15),
}


class Backend:
    """One text model. Subclasses implement `_call(prompt) -> (text, input_tokens, output_tokens)`; callers use
    `call(prompt) -> str` and read `cost_usd`, `calls`, `stats()`."""
    name = "backend"

    def __init__(self, model: str = "", budget: Budget | None = None, max_out: int = 200):
        self.model, self.budget, self.max_out = model, budget, max_out
        self.price_in, self.price_out = PRICES.get(model, (0.0, 0.0))
        self.cost_usd, self.calls, self.tok_in, self.tok_out, self.latency = 0.0, 0, 0, 0, []
        self._lock = threading.Lock()

    def call(self, prompt: str) -> str:
        worst = (len(prompt) / 3.0) * self.price_in / 1e6 + self.max_out * self.price_out / 1e6
        if self.budget:
            self.budget.reserve(worst)
        t = time.time()
        try:
            text, ti, to = self._call(prompt)
        except Exception:
            if self.budget:
                self.budget.settle(self.name, worst, 0.0)
            raise
        usd = ti * self.price_in / 1e6 + to * self.price_out / 1e6
        with self._lock:
            self.cost_usd += usd
            self.calls += 1
            self.tok_in += ti
            self.tok_out += to
            self.latency.append(time.time() - t)
        if self.budget:
            self.budget.settle(self.name, worst, usd)
        return text

    def _call(self, prompt: str) -> tuple[str, int, int]:
        raise NotImplementedError

    def stats(self) -> dict:
        lat = np.array(self.latency) if self.latency else np.zeros(1)
        return {"backend": self.name, "calls": self.calls, "tokens_in": int(self.tok_in),
                "tokens_out": int(self.tok_out), "cost_usd": round(self.cost_usd, 4),
                "cost_per_1k_usd": round(1000 * self.cost_usd / max(self.calls, 1), 4),
                "latency_s_median": round(float(np.median(lat)), 2),
                "latency_s_p90": round(float(np.quantile(lat, .9)), 2)}


class _VertexAuth:
    """Service-account token for Vertex (refreshed every 30 minutes). Uses the repo's src/auth.py when present."""
    _tok, _at, _lock = None, 0.0, threading.Lock()

    @classmethod
    def token(cls) -> str:
        with cls._lock:
            if cls._tok is None or time.time() - cls._at > 1800:
                try:
                    from auth import vertex_credentials  # repo helper (src/ on PYTHONPATH)
                    cls._tok = vertex_credentials().token
                except ImportError:
                    import google.auth
                    import google.auth.transport.requests
                    cr, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                    cr.refresh(google.auth.transport.requests.Request())
                    cls._tok = cr.token
                cls._at = time.time()
            return cls._tok


def _post(url: str, body: dict, retries: int = 6, timeout: float = 45.0) -> dict:
    """POST with retries on throttling, server errors and hung connections (a hung call is cut at `timeout`)."""
    import httpx
    for a in range(retries):
        try:
            r = httpx.post(url, json=body, timeout=httpx.Timeout(timeout, connect=15.0),
                           headers={"Authorization": f"Bearer {_VertexAuth.token()}",
                                    "Content-Type": "application/json"})
        except (httpx.TimeoutException, httpx.TransportError):
            if a < retries - 1:
                continue
            raise
        if r.status_code in (429, 500, 502, 503, 529) and a < retries - 1:
            time.sleep(min(60, 2 * 2 ** a))
            continue
        if r.status_code == 401 and a < retries - 1:
            _VertexAuth._tok = None
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("request failed after retries")


def _host(region: str) -> str:
    return "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"


def _p_yes(resp: dict, text: str) -> float:
    """P(yes) from the first generated token's top logprobs (renormalised over yes/no); falls back to the text."""
    import math
    try:
        top = resp["candidates"][0]["logprobsResult"]["topCandidates"][0]["candidates"]
        py = sum(math.exp(c["logProbability"]) for c in top if c["token"].strip().lower().startswith("yes"))
        pn = sum(math.exp(c["logProbability"]) for c in top if c["token"].strip().lower().startswith("no"))
        if py + pn > 0:
            return py / (py + pn)
    except (KeyError, IndexError, TypeError):
        pass
    t = (text or "").strip().lower()
    return 1.0 if t.startswith("yes") else 0.0 if t.startswith("no") else float("nan")


class VertexGemini(Backend):
    """Gemini on Vertex; `endpoint` = a tuned-model endpoint id; `yes_no` = the answer is yes/no and the returned
    text is {"p_vote": P(yes)} read from the logprobs (the supervised-tuning format)."""

    def __init__(self, model="gemini-2.5-flash", project="", region="us-central1", temperature=0.2, budget=None,
                 max_out=200, endpoint: str | None = None, yes_no: bool = False):
        super().__init__(model, budget, max_out)
        self.project, self.region, self.temperature, self.endpoint = project, region, temperature, endpoint
        self.yes_no = yes_no
        self.name = f"gemini:{model}" + (":tuned" if endpoint else "")

    def _call(self, prompt):
        base = f"https://{_host(self.region)}/v1/projects/{self.project}/locations/{self.region}"
        url = (f"{base}/endpoints/{self.endpoint}:generateContent" if self.endpoint
               else f"{base}/publishers/google/models/{self.model}:generateContent")
        gen = {"temperature": self.temperature, "maxOutputTokens": self.max_out}
        if self.yes_no:
            gen.update({"responseLogprobs": True, "logprobs": 5, "maxOutputTokens": 3})
        else:
            gen["responseMimeType"] = "application/json"
        if not self.endpoint:
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        d = _post(url, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen})
        u = d.get("usageMetadata", {})
        parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if self.yes_no:
            text = json.dumps({"p_vote": _p_yes(d, text), "comment": ""})
        return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)


class VertexClaude(Backend):
    """Claude through Vertex Model Garden (publisher anthropic). Checked 2026-11-24 in this project:
    claude-haiku-4-5, claude-sonnet-4-5 and claude-sonnet-4-6 answer (us-east5 and global); Opus is not enabled."""

    def __init__(self, model="claude-haiku-4-5", project="", region="global", temperature=0.2, budget=None,
                 max_out=120):
        super().__init__(model, budget, max_out)
        self.project, self.region, self.temperature = project, region, temperature
        self.name = f"claude:{model}"

    def _call(self, prompt):
        url = (f"https://{_host(self.region)}/v1/projects/{self.project}/locations/{self.region}"
               f"/publishers/anthropic/models/{self.model}:rawPredict")
        d = _post(url, {"anthropic_version": "vertex-2023-10-16", "max_tokens": self.max_out,
                        "temperature": self.temperature, "messages": [{"role": "user", "content": prompt}]})
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
        u = d.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


class VertexOpenAICompat(Backend):
    """Model Garden MaaS open models behind Vertex's OpenAI-compatible chat endpoint. Checked 2026-11-24:
    openai/gpt-oss-120b-maas (us-central1; a reasoning model: pass extra={"reasoning_effort": "low"} and a larger
    max_out) and meta/llama-4-maverick-17b-128e-instruct-maas (us-east5; pass
    extra={"response_format": {"type": "json_object"}} or it answers in prose)."""

    def __init__(self, model="openai/gpt-oss-120b-maas", project="", region="us-central1", temperature=0.2,
                 budget=None, max_out=200, extra: dict | None = None):
        super().__init__(model, budget, max_out)
        self.project, self.region, self.temperature, self.extra = project, region, temperature, extra or {}
        self.name = f"maas:{model.split('/')[-1]}"

    def _call(self, prompt):
        url = (f"https://{_host(self.region)}/v1/projects/{self.project}/locations/{self.region}"
               f"/endpoints/openapi/chat/completions")
        d = _post(url, {"model": self.model, "max_tokens": self.max_out, "temperature": self.temperature,
                        "messages": [{"role": "user", "content": prompt}], **self.extra})
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        u = d.get("usage", {})
        return msg.get("content") or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


class OpenAICompat(Backend):
    """Any OpenAI-compatible server, e.g. vLLM on our own GPU VM serving a fine-tuned open model (weights private).
    Price it with price_in / price_out (GPU cost per token) or leave 0."""

    def __init__(self, base_url: str, model: str, api_key: str = "none", budget=None, max_out=200,
                 price_in=0.0, price_out=0.0, temperature=0.2):
        super().__init__(model, budget, max_out)
        self.base_url, self.api_key, self.temperature = base_url.rstrip("/"), api_key, temperature
        self.price_in, self.price_out = price_in, price_out
        self.name = f"openai-compat:{model}"

    def _call(self, prompt):
        import httpx
        r = httpx.post(f"{self.base_url}/chat/completions", timeout=180,
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"model": self.model, "max_tokens": self.max_out, "temperature": self.temperature,
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        d = r.json()
        u = d.get("usage", {})
        return d["choices"][0]["message"].get("content") or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


class GeminiBackend(Backend):
    """v0 backend through the repo helper src/capability/gemini_config.gemini_chat (cost estimated from characters).
    Prefer VertexGemini, which reads real token usage."""

    def __init__(self, model: str = "gemini-2.5-flash-lite", price_in: float = 0.10, price_out: float = 0.40,
                 temperature: float = 0.2, budget: Budget | None = None):
        super().__init__(model, budget, 200)
        from capability.gemini_config import gemini_chat  # repo helper (src/ on PYTHONPATH)
        self._chat = gemini_chat
        self.price_in, self.price_out, self.temperature = price_in, price_out, temperature
        self.name = f"gemini:{model}"

    def _call(self, prompt):
        out = asyncio.run(self._chat([{"role": "user", "content": prompt}], model=self.model,
                                     temperature=self.temperature, json_mode=True, max_retries=4))
        return out, int(len(prompt) / 4), int(len(out) / 4)


class OpenAIBackend(Backend):
    """STUB: OpenAI's own API. No OpenAI key is configured for this project (checked 2026-11-23); gpt-oss-120b is
    reachable through VertexOpenAICompat instead."""
    name = "openai:stub"

    def _call(self, prompt):
        raise NotImplementedError("OpenAIBackend is a stub: no OpenAI access configured")


ClaudeBackend = VertexClaude            # v0 names kept for callers
LocalOpenModelBackend = OpenAICompat


# ------------------------------------------------------------------------------------------ model
class PromptVote(VoteModel):
    """cache: a dict or a JsonlCache keyed (day, person_idx, item_idx) -> [p_vote, comment]."""

    def __init__(self, backend: Backend, max_items: int = 30, workers: int = 8, cache=None,
                 prompt_version: int = 2):
        self.backend, self.max_items, self.workers, self.prompt_version = backend, max_items, workers, prompt_version
        self.name = f"prompt[{backend.name}]"
        self.cache = cache if cache is not None else {}
        self.failures = 0

    @property
    def cost_usd(self) -> float:
        return self.backend.cost_usd

    def _one(self, histories, j, item):
        key = (histories.day, int(histories.person_idx[j]), int(item.item_idx))
        if key not in self.cache:
            prompt = build_prompt(histories.render(j, self.max_items), item, self.prompt_version)
            try:
                p, c = parse(self.backend.call(prompt))
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001 - one failed call must not stop a run; counted, scored NaN, not cached
                self.failures += 1
                return (np.nan, "")
            self.cache[key] = [None if p != p else p, c]
        p, c = self.cache[key]
        return (np.nan if p is None else p, c)

    def score(self, histories, item) -> np.ndarray:
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda j: self._one(histories, j, item), range(len(histories))))
        return np.array([r[0] for r in res], dtype=float)

    def comment(self, histories, j: int, item) -> str:
        return self._one(histories, j, item)[1]
