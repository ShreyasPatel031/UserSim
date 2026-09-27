"""Shared pairwise judge: which of two versions (or two products) would these visitors act on?

One code path serves the product (``mvp.comparison``: the product against each rival, per buyer, from each run's
screenshots and trace) and the WiserUI-Bench harness (``bench/wiserui/run_bench.py``: two screenshots of one page
from a real A/B test). Every component sits behind a flag in :class:`PairFlags`, so ablation arms differ only in
flags:

- ``both_orders``: judge (A, B) and (B, A) and average, which cancels position bias.
- ``goal_diffs``: first infer the site operator's goal and a list of concrete, localized differences
  (G-FOCUS, arXiv 2505.05026v1 Appendix E), in both orders, merged; personas then judge only those differences.
- ``debias``: SimAB-style instructions (more is better only if needed, simplicity under time/price pressure,
  choice overload, ignore goal-irrelevant factors).
- ``framing``: ``"ab"`` (two versions of one page; the benchmark) or ``"products"`` (two rival products; the
  product's comparison study). Only the wording changes; labels, ratings and aggregation are shared.

Sides are always shown under neutral labels ("Version X" / "Version Y", or "Product X" / "Product Y"). Each persona
writes its reasons first, then rates EACH side 1-10 on how likely it is to take the goal action. Ratings are averaged
across orders per persona and aggregated softly into p(A > B), with the mean rating difference and its standard error.

Model calls go through a :data:`Call`: ``call(key, contents, *, temperature, max_tokens, media_resolution=None)``
returning ``(text, tokens_in, tokens_out)``; ``seed=`` is passed only when ``PairFlags.seed`` is set. ``key`` names
the call (``judge|ab|3``, ``goal|ba``, ``planner``) and is stable across runs, so callers can cache on it. The
default, :func:`default_call`, runs :func:`mvp.e2e_ui_run.gemini_generate` (Vertex Gemini, thinking off, JSON mode,
429 / 5xx backoff with region fallback) on a bounded thread pool (``MVP_PAIRWISE_THREADS``, default 16). Callers may
inject their own call (cache, ledger, mock).

The "ab" prompts, content layout and call keys are frozen at their 372b405 form: the benchmark ledger caches replies
by call key, so any change there would silently mix judgments made under different prompts.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import math
import os
import re
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, TypedDict

PAIRWISE_MODEL = os.environ.get("MVP_PAIRWISE_MODEL", "gemini-2.5-flash")
# Soft vote: a persona's mean rating difference d (in rating points) counts as sigmoid(d / SOFT_T) for A.
SOFT_T = 1.5
# Characters of PairEvidence.summary shown to the model per side.
SUMMARY_CHARS = 1500

Call = Callable[..., Awaitable[tuple[str, int, int]]]
Order = Literal["ab", "ba"]
Framing = Literal["ab", "products"]
ORDERS: tuple[Order, Order] = ("ab", "ba")
FRAMINGS: tuple[Framing, ...] = ("ab", "products")


@dataclass
class PairEvidence:
    """One side of a comparison: a label for humans, 1+ screenshots (PNG/JPEG bytes), optional url and text.

    ``label`` is never shown to the model. ``summary`` is (for "ab") text on the page, or (for "products") what the
    persona saw and did there; the first :data:`SUMMARY_CHARS` characters are shown.
    """

    label: str
    screenshots: list[bytes] = field(default_factory=list)
    url: str = ""
    summary: str = ""

    def fingerprint(self) -> str:
        """Content hash of what the model sees (screenshots and summary), for A/A checks and caching."""
        h = hashlib.sha256()
        for shot in self.screenshots:
            h.update(hashlib.sha256(shot).digest())
        h.update(self.summary[:SUMMARY_CHARS].encode())
        return h.hexdigest()


@dataclass
class PairFlags:
    """What the judge does. Fields after ``media_resolution`` were added after 372b405; their defaults reproduce it."""

    both_orders: bool = True
    goal_diffs: bool = False
    debias: bool = False
    temperature: float = 0.4
    max_tokens: int = 700
    media_resolution: str | None = None  # "high" only works with one image per call
    framing: Framing = "ab"
    seed: int | None = None  # None: no seed sent. Otherwise each call gets a seed derived from (seed, call key).
    json_retries: int = 0  # extra calls (keys suffixed "|retry1", ...) when a reply does not parse

    def __post_init__(self) -> None:
        if self.framing not in FRAMINGS:
            raise ValueError(f"framing must be one of {FRAMINGS}, got {self.framing!r}")
        if self.goal_diffs and self.framing != "ab":
            raise ValueError("goal_diffs compares two versions of one page; it needs framing='ab'")
        if self.json_retries < 0:
            raise ValueError("json_retries must be >= 0")

    def name(self) -> str:
        return "+".join(
            ["both" if self.both_orders else "one", "ratings"]
            + (["goal_diffs"] if self.goal_diffs else [])
            + (["debias"] if self.debias else [])
            + (["products"] if self.framing == "products" else [])
        )

    @property
    def orders(self) -> tuple[Order, ...]:
        return ORDERS if self.both_orders else ORDERS[:1]


class Diff(TypedDict):
    element: str
    a: str
    b: str


class Judgment(TypedDict, total=False):
    order: Order
    persona: str | None
    k: int
    rating_x: float | None
    rating_y: float | None
    rating_a: float | None
    rating_b: float | None
    reasons: str
    ok: bool
    attempts: int
    error: str | None


class PersonaResult(TypedDict):
    persona: str | None
    diff: float
    p_a: float
    by_order: dict[str, float]
    reasons: dict[str, str]


class PairResult(TypedDict, total=False):
    p_a: float
    mean_diff: float
    se: float
    winner: Literal["A", "B", "tie"]
    votes: dict[str, int]
    personas: list[PersonaResult]
    orders: dict[str, dict[str, Any]]
    n_personas: int
    label_a: str
    label_b: str
    flags: str
    goal: str
    diffs: list[Diff]
    goal_diffs_by_order: dict[str, Any] | None
    rationale: list[str]
    judgments: list[Judgment]
    failed_judgments: int
    errors: list[str]


# ----------------------------------------------------------------- model access

_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def pool_size() -> int:
    try:
        return max(1, int(os.environ.get("MVP_PAIRWISE_THREADS", "16")))
    except ValueError:
        return 16


def _pool() -> ThreadPoolExecutor:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=pool_size(), thread_name_prefix="pairwise")
        return _POOL


def configure_pool(max_workers: int) -> None:
    """Resize the shared model-call pool. Calls already running finish on the old pool."""
    global _POOL
    with _POOL_LOCK:
        old, _POOL = _POOL, ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="pairwise")
    if old is not None:
        old.shutdown(wait=False)


def vertex_call(*, model: str | None = None, retries: int | None = None,
                executor: ThreadPoolExecutor | None = None) -> Call:
    """A :data:`Call` on Vertex Gemini (:func:`mvp.e2e_ui_run.gemini_generate`), run on ``executor`` or the shared pool.

    ``retries`` (default ``MVP_PAIRWISE_RETRIES`` or 8) bounds the 429 / 5xx backoff; keep it small under a deadline,
    because a call already running in a thread cannot be cancelled.
    """
    n_retries = retries if retries is not None else int(os.environ.get("MVP_PAIRWISE_RETRIES", "8"))

    async def call(key: str, contents: list, *, temperature: float, max_tokens: int,
                   media_resolution: str | None = None, seed: int | None = None) -> tuple[str, int, int]:
        from mvp.e2e_ui_run import gemini_generate

        fn = functools.partial(
            gemini_generate, list(contents), model=model or PAIRWISE_MODEL, temperature=temperature,
            max_tokens=max_tokens, json_mode=True, media_resolution=media_resolution, retries=n_retries, seed=seed,
        )
        return await asyncio.get_running_loop().run_in_executor(executor or _pool(), fn)

    return call


async def default_call(key: str, contents: list, *, temperature: float, max_tokens: int,
                       media_resolution: str | None = None, seed: int | None = None) -> tuple[str, int, int]:
    return await vertex_call()(key, contents, temperature=temperature, max_tokens=max_tokens,
                               media_resolution=media_resolution, seed=seed)


def call_seed(base: int | None, key: str) -> int | None:
    """Per-call seed: stable for (base, key), different across keys so personas and orders do not share samples."""
    if base is None:
        return None
    return int.from_bytes(hashlib.sha256(f"{base}|{key}".encode()).digest()[:4], "big") & 0x7FFFFFFF


async def _ask(call: Call, key: str, contents: list, *, temperature: float, max_tokens: int,
               media_resolution: str | None, seed: int | None, retries: int,
               accept: Callable[[Any], bool]) -> tuple[Any, int, str | None]:
    """Call and parse; re-ask up to ``retries`` times (keys ``key|retryN``) until ``accept(parsed)``.

    Returns (parsed or None, attempts, last error). Model errors count as a failed attempt, never raise.
    """
    parsed: Any = None
    err: str | None = None
    attempt = 0
    for attempt in range(1, retries + 2):
        k = key if attempt == 1 else f"{key}|retry{attempt - 1}"
        kw: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens, "media_resolution": media_resolution}
        s = call_seed(seed, k)
        if s is not None:
            kw["seed"] = s
        try:
            text, _, _ = await call(k, contents, **kw)
        except Exception as exc:  # noqa: BLE001 - a lost call is a failed judgment, not a failed comparison
            err = repr(exc)[:300]
            continue
        parsed = parse_json(text)
        if accept(parsed):
            return parsed, attempt, None
        err = "unparseable reply"
    return parsed, attempt, err


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str | None) -> Any:
    """First JSON object or array in a model reply, or None.

    Tries the outermost bracket span first (the 372b405 behaviour), then fenced blocks, then the first position
    that decodes, so a reply with trailing prose or two objects still parses.
    """
    text = text or ""
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except Exception:  # noqa: BLE001
        pass
    for block in _FENCE.findall(text):
        try:
            return json.loads(block)
        except ValueError:
            continue
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return dec.raw_decode(text, i)[0]
            except ValueError:
                continue
    return None


def _rating(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        x = float(str(v).strip().split("/")[0])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return max(1.0, min(10.0, x))


def _ctx_line(ctx: dict[str, Any]) -> str:
    bits = [str(ctx.get("company") or "").strip(), str(ctx.get("page_type") or "page").strip()]
    extra = ", ".join(x for x in (ctx.get("industry"), ctx.get("platform")) if x)
    line = " ".join(b for b in bits if b)
    return f"{line} ({extra})" if extra else line


_SIDE = {"ab": ("Version", "text on the page"), "products": ("Product", "what you saw and did there")}


def _version_parts(first: PairEvidence, second: PairEvidence, framing: Framing = "ab") -> list:
    """Neutral labels: the first shown is always X, the second Y."""
    noun, intro = _SIDE[framing]
    parts: list = []
    for name, ev in ((f"{noun} X", first), (f"{noun} Y", second)):
        head = f"{name}:" + (f" ({intro}: {ev.summary[:SUMMARY_CHARS]})" if ev.summary else "")
        parts.append(head)
        parts.extend(ev.screenshots)
    return parts


def _ordered(ev_a: PairEvidence, ev_b: PairEvidence, order: Order) -> tuple[PairEvidence, PairEvidence]:
    return (ev_a, ev_b) if order == "ab" else (ev_b, ev_a)


# ----------------------------------------------------------------- personas (product code: mvp.fast_plan)

async def plan_personas(ctx: dict[str, Any], *, call: Call | None = None, n: int | None = None,
                        seed: int | None = None) -> list[dict[str, Any]]:
    """Visitors for this page from context only (:func:`mvp.fast_plan.ab_personas`); [] when the planner fails."""
    from mvp.fast_plan import ab_personas, ab_personas_prompt

    data, _, _ = await _ask(call or default_call, "planner", [ab_personas_prompt(ctx)], temperature=0.3,
                            max_tokens=2048, media_resolution=None, seed=seed, retries=0,
                            accept=lambda j: isinstance(j, dict))
    return ab_personas(data if isinstance(data, dict) else {}, ctx, n)


# ----------------------------------------------------------------- goal + differences (G-FOCUS)

_GOAL_DIFFS = """You are a UX analyst looking at two versions of the same page from an A/B test: {ctx}.
The first screenshot(s) are Version X, the second Version Y.

Step 1. Infer the site operator's main goal for this page: the one action they most want a visitor to take here
(for example "start a free trial", "add the product to cart", "submit a quote request"), in 3-12 words.
Step 2. List the concrete, localized UI differences between Version X and Version Y that are relevant to that goal.
Each difference is one visible change in one place (an element's wording, color, size, position, presence, count or
layout), described factually as it appears in each version. Do not list abstract or subjective differences
("cleaner", "more modern", "better hierarchy"). Ignore placeholder content (lorem ipsum, sample products, stock photos
that merely differ), rendering glitches and smudges. At most 5, most goal-relevant first. If you see no real
difference, return an empty list.

Return JSON only:
{{"goal": "the operator's goal action, 3-12 words",
  "differences": [{{"element": "short name, e.g. main call-to-action button", "x": "how it is in Version X", "y": "how it is in Version Y"}}]}}"""


def _norm_tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in {"the", "a", "an", "of", "and", "button", "section"}}


def merge_diffs(lists: list[list[Diff]], cap: int = 6) -> list[Diff]:
    """Interleave canonical diff lists (a/b sides) from both orders; drop near-duplicate elements."""
    out: list[Diff] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i >= len(lst):
                continue
            d = lst[i]
            toks = _norm_tokens(d["element"])
            dup = any(
                toks and ot and len(toks & ot) / len(toks | ot) >= 0.5
                for ot in (_norm_tokens(o["element"]) for o in out)
            )
            if not dup:
                out.append(d)
    return out[:cap]


def _clean(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def _diffs_from(j: Any, order: Order) -> tuple[str, list[Diff]]:
    """Goal and diffs from one reply, mapped from X/Y to canonical a/b."""
    if not isinstance(j, dict):
        return "", []
    raw = j.get("differences")
    diffs: list[Diff] = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict) or not str(d.get("element") or "").strip():
            continue
        x, y = _clean(d.get("x"), 200), _clean(d.get("y"), 200)
        a, b = (x, y) if order == "ab" else (y, x)
        diffs.append({"element": _clean(d["element"], 80), "a": a, "b": b})
    return _clean(j.get("goal"), 120), diffs


async def extract_goal_and_diffs(ev_a: PairEvidence, ev_b: PairEvidence, ctx: dict[str, Any], *,
                                 call: Call | None = None, both_orders: bool = True,
                                 media_resolution: str | None = None, json_retries: int = 0,
                                 seed: int | None = None) -> dict[str, Any]:
    """Operator goal + concrete differences, extracted in both orders and merged, in canonical a/b terms.

    The goal comes from the first order that names one (A shown first), so both presentation orders are judged
    against the same goal. Returns {"goal", "diffs", "by_order", "errors"}.
    """
    call = call or default_call
    orders = ORDERS if both_orders else ORDERS[:1]

    async def one(order: Order) -> dict[str, Any]:
        first, second = _ordered(ev_a, ev_b, order)
        j, _, err = await _ask(call, f"goal|{order}", [_GOAL_DIFFS.format(ctx=_ctx_line(ctx)), *_version_parts(first, second)],
                               temperature=0.0, max_tokens=1200, media_resolution=media_resolution, seed=seed,
                               retries=json_retries, accept=lambda x: isinstance(x, dict))
        goal, diffs = _diffs_from(j, order)
        return {"goal": goal, "diffs": diffs, **({"error": err} if err else {})}

    got = await asyncio.gather(*(one(o) for o in orders))
    goal = next((g["goal"] for g in got if g["goal"]), "")
    return {"goal": goal, "diffs": merge_diffs([g["diffs"] for g in got]), "by_order": dict(zip(orders, got)),
            "errors": [g["error"] for g in got if g.get("error")]}


# ----------------------------------------------------------------- one persona, one order

_DEBIAS = """Judge like a real visitor, not a designer:
- More information, options or content is better ONLY if you personally need it for your goal; otherwise it is clutter.
- If you are short on time or price-sensitive, the simpler, faster path wins.
- Too many choices make people hesitate and leave (choice overload).
- Ignore anything that does not affect whether you would take the goal action."""


def _who(persona: dict[str, Any]) -> str:
    return f"You are {persona.get('name') or 'a visitor'}, {persona.get('role') or ''}. {persona.get('bio') or ''}".strip()


def _ab_prompt(persona: dict[str, Any], ctx: dict[str, Any], goal: str, diffs: list[Diff] | None,
               order: Order, debias: bool) -> str:
    page = f"{ctx.get('company') or 'this site'}'s {ctx.get('page_type') or 'page'}" + (
        f" ({ctx['platform']})" if ctx.get("platform") else "")
    action = (f"the site's goal action: {goal}" if goal else
              "the page's main next step (click the main button, add to cart, sign up, search, continue)")
    lines = [
        _who(persona),
        f"You came to {page} to: {persona.get('goal') or 'look around'}.",
        "",
        "Below are two versions of this page, Version X and Version Y. Look at each as if it were the page in front "
        "of you right now, as yourself (not as a designer).",
    ]
    if diffs:
        lines += ["", "The two versions differ only in these places; everything else is the same. Judge ONLY these "
                  "differences and ignore everything else:"]
        for i, d in enumerate(diffs, 1):
            x, y = (d["a"], d["b"]) if order == "ab" else (d["b"], d["a"])
            lines.append(f"{i}. {d['element']}: Version X: {x} | Version Y: {y}")
    if debias:
        lines += ["", _DEBIAS]
    lines += [
        "",
        f"First give your reasons, then rate EACH version from 1 to 10 on how likely you would be to take {action} "
        "on that version (1 = surely not, 10 = surely yes). Use different ratings if one version would work better for you.",
        "Return JSON only, with the keys in this order:",
        '{"reasons": "two or three sentences in your own voice comparing the versions on what matters to you",',
        ' "rating_x": 1-10, "rating_y": 1-10}',
    ]
    return "\n".join(lines)


def _products_prompt(persona: dict[str, Any], ctx: dict[str, Any], debias: bool) -> str:
    segment = str(ctx.get("segment") or "").strip()
    lines = [
        _who(persona),
        f"You are comparing two {'products for ' + segment if segment else 'competing products'}. "
        f"What you need done: {persona.get('goal') or 'find the product that fits you best'}.",
        "",
        "Below is what you found on each of two products, Product X and Product Y: screenshots of the pages you saw "
        "(the opening page first, then the last page of each job) and the steps you took. Look at each as yourself "
        "(not as a reviewer). A demo or signup wall counts only for what it cost you; judge what each product "
        "showed you it can do for your needs.",
    ]
    if debias:
        lines += ["", _DEBIAS]
    lines += [
        "",
        "First give your reasons, then rate EACH product from 1 to 10 on how likely you would be to choose it for "
        "what you need (sign up, start a trial, book a demo or buy) (1 = surely not, 10 = surely yes). Use different "
        "ratings if one product would work better for you.",
        "Return JSON only, with the keys in this order:",
        '{"reasons": "two or three sentences in your own voice comparing the products on what matters to you",',
        ' "rating_x": 1-10, "rating_y": 1-10}',
    ]
    return "\n".join(lines)


def judge_prompt(persona: dict[str, Any], ctx: dict[str, Any], goal: str, diffs: list[Diff] | None,
                 order: Order, debias: bool, framing: Framing = "ab") -> str:
    """The judge's text prompt for one persona and presentation order (screenshots follow it)."""
    if framing == "products":
        return _products_prompt(persona, ctx, debias)
    return _ab_prompt(persona, ctx, goal, diffs, order, debias)


def _judgment_ok(j: Any) -> bool:
    return isinstance(j, dict) and _rating(j.get("rating_x")) is not None and _rating(j.get("rating_y")) is not None


async def judge_pair(persona: dict[str, Any], ev_a: PairEvidence, ev_b: PairEvidence, goal: str = "",
                     diffs: list[Diff] | None = None, order: Order = "ab", temperature: float = 0.4,
                     debias: bool = False, *, ctx: dict[str, Any] | None = None, call: Call | None = None,
                     key: str = "", max_tokens: int = 700, media_resolution: str | None = None,
                     framing: Framing = "ab", json_retries: int = 0, seed: int | None = None) -> Judgment:
    """One persona rates both sides in one presentation order; ratings are mapped back to a/b.

    Never raises on a model error or bad reply: the judgment comes back with ``ok=False`` and ``error`` set.
    """
    first, second = _ordered(ev_a, ev_b, order)
    prompt = judge_prompt(persona, ctx or {}, goal, diffs, order, debias, framing)
    j, attempts, err = await _ask(
        call or default_call, key or f"judge|{order}|{persona.get('name')}", [prompt, *_version_parts(first, second, framing)],
        temperature=temperature, max_tokens=max_tokens, media_resolution=media_resolution, seed=seed,
        retries=json_retries, accept=_judgment_ok,
    )
    j = j if isinstance(j, dict) else {}
    rx, ry = _rating(j.get("rating_x")), _rating(j.get("rating_y"))
    ra, rb = (rx, ry) if order == "ab" else (ry, rx)
    ok = rx is not None and ry is not None
    return {"order": order, "persona": persona.get("name"), "rating_x": rx, "rating_y": ry, "rating_a": ra,
            "rating_b": rb, "reasons": _clean(j.get("reasons"), 500), "ok": ok, "attempts": attempts,
            "error": None if ok else err}


# ----------------------------------------------------------------- aggregation

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def aggregate(judgments: list[Judgment], personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Average each persona's (a - b) across orders, then soft-vote into p(A > B)."""
    per: list[PersonaResult] = []
    for k, p in enumerate(personas):
        mine = [j for j in judgments if (j["k"] == k if "k" in j else j["persona"] == p.get("name")) and j["ok"]]
        if not mine:
            continue
        d = statistics.fmean(j["rating_a"] - j["rating_b"] for j in mine)
        per.append({
            "persona": p.get("name"), "diff": d, "p_a": _sigmoid(d / SOFT_T),
            "by_order": {j["order"]: j["rating_a"] - j["rating_b"] for j in mine},
            "reasons": {j["order"]: j["reasons"] for j in mine},
        })
    order_view: dict[str, Any] = {}
    for o in ORDERS:
        oj = [j for j in judgments if j["order"] == o and j["ok"]]
        if not oj:
            continue
        mx = statistics.fmean(j["rating_x"] - j["rating_y"] for j in oj)
        order_view[o] = {
            "n": len(oj), "x_minus_y": mx, "pick": "X" if mx > 0 else "Y" if mx < 0 else "tie",
            "pick_ab": ("A" if (mx > 0) == (o == "ab") else "B") if mx != 0 else "tie",
            "n_x": sum(j["rating_x"] > j["rating_y"] for j in oj), "n_y": sum(j["rating_x"] < j["rating_y"] for j in oj),
        }
    return {**soft_vote([x["diff"] for x in per]), "personas": per, "orders": order_view, "n_personas": len(per)}


def soft_vote(diffs: list[float]) -> dict[str, Any]:
    """p(A > B) = mean of sigmoid(d / SOFT_T) over per-persona rating differences d (a - b), plus mean, SE, votes."""
    if not diffs:
        return {"p_a": 0.5, "mean_diff": 0.0, "se": 0.0, "winner": "tie", "votes": {"A": 0, "B": 0, "tie": 0}}
    mean = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else 0.0
    p_a = statistics.fmean(_sigmoid(d / SOFT_T) for d in diffs)
    votes = {"A": sum(d > 0 for d in diffs), "B": sum(d < 0 for d in diffs), "tie": sum(d == 0 for d in diffs)}
    winner = "A" if p_a > 0.5 + 1e-9 else "B" if p_a < 0.5 - 1e-9 else "tie"
    return {"p_a": p_a, "mean_diff": mean, "se": se, "winner": winner, "votes": votes}


def _bounded(call: Call, limit: int | None) -> Call:
    if not limit:
        return call
    sem = asyncio.Semaphore(limit)

    async def bounded(key: str, contents: list, **kw: Any) -> tuple[str, int, int]:
        async with sem:
            return await call(key, contents, **kw)

    return bounded


async def compare_pair(ev_a: PairEvidence, ev_b: PairEvidence, personas: list[dict[str, Any]] | None,
                       ctx: dict[str, Any], flags: PairFlags | None = None, *, call: Call | None = None,
                       max_concurrency: int | None = None) -> PairResult:
    """Which side would these personas act on? Returns p(A>B), mean diff +- SE, votes, rationale, raw judgments.

    ``personas`` (name, role, bio, goal) come from product code (:mod:`mvp.fast_plan`); when empty they are planned
    from ``ctx``. ``max_concurrency`` caps this comparison's in-flight calls on top of the shared thread pool.
    Model errors and bad replies become failed judgments (counted in ``failed_judgments``), never exceptions.
    """
    flags = flags or PairFlags()
    call = _bounded(call or default_call, max_concurrency)
    if not personas:
        personas = await plan_personas(ctx, call=call, seed=flags.seed)
    goal, diffs, gd = "", None, None
    if flags.goal_diffs:
        gd = await extract_goal_and_diffs(ev_a, ev_b, ctx, call=call, both_orders=flags.both_orders,
                                          media_resolution=flags.media_resolution, json_retries=flags.json_retries,
                                          seed=flags.seed)
        goal, diffs = gd["goal"], gd["diffs"] or None
    cells = [(o, k) for o in flags.orders for k in range(len(personas))]
    judgments: list[Judgment] = list(await asyncio.gather(*(
        judge_pair(personas[k], ev_a, ev_b, goal, diffs, o, flags.temperature, flags.debias, ctx=ctx, call=call,
                   key=f"judge|{o}|{k}", max_tokens=flags.max_tokens, media_resolution=flags.media_resolution,
                   framing=flags.framing, json_retries=flags.json_retries, seed=flags.seed)
        for o, k in cells
    )))
    for (_, k), j in zip(cells, judgments):
        j["k"] = k
    agg = aggregate(judgments, personas)
    w = agg["winner"]
    backers = [x for x in agg["personas"] if (x["diff"] > 0 if w == "A" else x["diff"] < 0 if w == "B" else False)]
    backers.sort(key=lambda x: -abs(x["diff"]))
    rationale = [f"{x['persona']}: {next(iter(x['reasons'].values()), '')}" for x in backers[:3]]
    errors = [j["error"] for j in judgments if j.get("error")] + list((gd or {}).get("errors") or [])
    return {
        **agg,
        "label_a": ev_a.label, "label_b": ev_b.label, "flags": flags.name(),
        "goal": goal, "diffs": diffs or [], "goal_diffs_by_order": (gd or {}).get("by_order"),
        "rationale": rationale, "judgments": judgments,
        "failed_judgments": sum(not j["ok"] for j in judgments),
        "errors": errors[:10],
    }
