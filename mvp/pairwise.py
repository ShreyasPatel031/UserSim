"""Shared pairwise A/B judge: which of two versions of a page would these visitors act on?

One code path serves the product (comparison of two sites / two versions from run screenshots) and the
WiserUI-Bench harness (bench/wiserui/run_bench.py). Every component sits behind a flag in :class:`PairFlags`,
so ablation arms differ only in flags:

- ``both_orders``: judge (A, B) and (B, A) and average, which cancels position bias.
- ``goal_diffs``: first infer the site operator's goal and a list of concrete, localized differences
  (G-FOCUS, arXiv 2505.05026v1 Appendix E), in both orders, merged; personas then judge only those differences.
- ``debias``: SimAB-style instructions (more is better only if needed, simplicity under time/price pressure,
  choice overload, ignore goal-irrelevant factors).

Versions are always shown under neutral labels "Version X" / "Version Y". Each persona writes its reasons first,
then rates EACH version 1-10 on how likely it is to take the goal action. Ratings are averaged across orders per
persona and aggregated softly into p(A > B), with the mean rating difference and its standard error.

Model calls go through ``call(key, contents, temperature=..., max_tokens=...) -> (text, tokens_in, tokens_out)``;
the default uses :func:`mvp.e2e_ui_run.gemini_generate` (Vertex gemini-2.5-flash, thinking off, JSON, 429 backoff).
Callers may inject their own (cache, ledger, mock).
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

PAIRWISE_MODEL = os.environ.get("MVP_PAIRWISE_MODEL", "gemini-2.5-flash")
# Soft vote: a persona's mean rating difference d (in rating points) counts as sigmoid(d / SOFT_T) for A.
SOFT_T = 1.5

Call = Callable[..., Awaitable[tuple[str, int, int]]]


@dataclass
class PairEvidence:
    """One side of a comparison: a label for humans, 1+ screenshots (PNG/JPEG bytes), optional url and text."""

    label: str
    screenshots: list[bytes] = field(default_factory=list)
    url: str = ""
    summary: str = ""


@dataclass
class PairFlags:
    both_orders: bool = True
    goal_diffs: bool = False
    debias: bool = False
    temperature: float = 0.4
    max_tokens: int = 700
    media_resolution: str | None = None  # "high" only works with one image per call

    def name(self) -> str:
        return "+".join(
            ["both" if self.both_orders else "one", "ratings"]
            + (["goal_diffs"] if self.goal_diffs else [])
            + (["debias"] if self.debias else [])
        )


ORDERS = ("ab", "ba")


# ----------------------------------------------------------------- model access

async def default_call(key: str, contents: list, *, temperature: float, max_tokens: int,
                       media_resolution: str | None = None) -> tuple[str, int, int]:
    from mvp.e2e_ui_run import gemini_generate

    return await asyncio.to_thread(
        gemini_generate, contents, model=PAIRWISE_MODEL, temperature=temperature, max_tokens=max_tokens,
        json_mode=True, media_resolution=media_resolution,
    )


def parse_json(text: str) -> Any:
    m = re.search(r"[\[{].*[\]}]", text or "", re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except Exception:  # noqa: BLE001
        return None


def _rating(v: Any) -> float | None:
    try:
        x = float(str(v).strip().split("/")[0])
    except (TypeError, ValueError):
        return None
    if math.isnan(x):
        return None
    return max(1.0, min(10.0, x))


def _ctx_line(ctx: dict[str, Any]) -> str:
    bits = [str(ctx.get("company") or "").strip(), str(ctx.get("page_type") or "page").strip()]
    extra = ", ".join(x for x in (ctx.get("industry"), ctx.get("platform")) if x)
    line = " ".join(b for b in bits if b)
    return f"{line} ({extra})" if extra else line


def _version_parts(first: PairEvidence, second: PairEvidence) -> list:
    """Neutral labels: the first shown is always Version X, the second Version Y."""
    parts: list = []
    for name, ev in (("Version X", first), ("Version Y", second)):
        head = f"{name}:" + (f" (text on the page: {ev.summary[:1500]})" if ev.summary else "")
        parts.append(head)
        parts.extend(ev.screenshots)
    return parts


def _ordered(ev_a: PairEvidence, ev_b: PairEvidence, order: str) -> tuple[PairEvidence, PairEvidence]:
    return (ev_a, ev_b) if order == "ab" else (ev_b, ev_a)


# ----------------------------------------------------------------- personas (product code: mvp.fast_plan)

async def plan_personas(ctx: dict[str, Any], *, call: Call | None = None, n: int | None = None) -> list[dict[str, Any]]:
    """Six visitors for this page from context only (mvp.fast_plan.ab_personas)."""
    from mvp.fast_plan import ab_personas, ab_personas_prompt

    call = call or default_call
    text, _, _ = await call("planner", [ab_personas_prompt(ctx)], temperature=0.3, max_tokens=2048)
    return ab_personas(parse_json(text) or {}, ctx, n)


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


def merge_diffs(lists: list[list[dict[str, str]]], cap: int = 6) -> list[dict[str, str]]:
    """Interleave canonical diff lists (a/b sides) from both orders; drop near-duplicate elements."""
    out: list[dict[str, str]] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for lst in lists:
            if i >= len(lst):
                continue
            d = lst[i]
            toks = _norm_tokens(d["element"])
            dup = False
            for o in out:
                ot = _norm_tokens(o["element"])
                if toks and ot and len(toks & ot) / len(toks | ot) >= 0.5:
                    dup = True
                    break
            if not dup:
                out.append(d)
    return out[:cap]


async def extract_goal_and_diffs(ev_a: PairEvidence, ev_b: PairEvidence, ctx: dict[str, Any], *,
                                 call: Call | None = None, both_orders: bool = True,
                                 media_resolution: str | None = None) -> dict[str, Any]:
    """Operator goal + concrete differences, extracted in both orders and merged, in canonical a/b terms."""
    call = call or default_call
    orders = ORDERS if both_orders else ORDERS[:1]

    async def one(order: str) -> dict[str, Any]:
        first, second = _ordered(ev_a, ev_b, order)
        text, tin, tout = await call(f"goal|{order}", [_GOAL_DIFFS.format(ctx=_ctx_line(ctx)), *_version_parts(first, second)],
                                     temperature=0.0, max_tokens=1200, media_resolution=media_resolution)
        j = parse_json(text) or {}
        diffs = []
        for d in (j.get("differences") or []) if isinstance(j, dict) else []:
            if not isinstance(d, dict) or not str(d.get("element") or "").strip():
                continue
            x, y = " ".join(str(d.get("x") or "").split())[:200], " ".join(str(d.get("y") or "").split())[:200]
            a, b = (x, y) if order == "ab" else (y, x)
            diffs.append({"element": " ".join(str(d["element"]).split())[:80], "a": a, "b": b})
        goal = " ".join(str((j or {}).get("goal") or "").split())[:120] if isinstance(j, dict) else ""
        return {"goal": goal, "diffs": diffs}

    got = await asyncio.gather(*(one(o) for o in orders))
    goal = next((g["goal"] for g in got if g["goal"]), "")
    return {"goal": goal, "diffs": merge_diffs([g["diffs"] for g in got]), "by_order": dict(zip(orders, got))}


# ----------------------------------------------------------------- one persona, one order

_DEBIAS = """Judge like a real visitor, not a designer:
- More information, options or content is better ONLY if you personally need it for your goal; otherwise it is clutter.
- If you are short on time or price-sensitive, the simpler, faster path wins.
- Too many choices make people hesitate and leave (choice overload).
- Ignore anything that does not affect whether you would take the goal action."""


def judge_prompt(persona: dict[str, Any], ctx: dict[str, Any], goal: str, diffs: list[dict[str, str]] | None,
                 order: str, debias: bool) -> str:
    who = f"You are {persona.get('name') or 'a visitor'}, {persona.get('role') or ''}. {persona.get('bio') or ''}".strip()
    page = f"{ctx.get('company') or 'this site'}'s {ctx.get('page_type') or 'page'}" + (
        f" ({ctx['platform']})" if ctx.get("platform") else "")
    action = (f"the site's goal action: {goal}" if goal else
              "the page's main next step (click the main button, add to cart, sign up, search, continue)")
    lines = [
        who,
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


async def judge_pair(persona: dict[str, Any], ev_a: PairEvidence, ev_b: PairEvidence, goal: str = "",
                     diffs: list[dict[str, str]] | None = None, order: str = "ab", temperature: float = 0.4,
                     debias: bool = False, *, ctx: dict[str, Any] | None = None, call: Call | None = None,
                     key: str = "", max_tokens: int = 700, media_resolution: str | None = None) -> dict[str, Any]:
    """One persona rates both versions in one presentation order; ratings are mapped back to a/b."""
    call = call or default_call
    first, second = _ordered(ev_a, ev_b, order)
    prompt = judge_prompt(persona, ctx or {}, goal, diffs, order, debias)
    text, _, _ = await call(key or f"judge|{order}|{persona.get('name')}", [prompt, *_version_parts(first, second)],
                            temperature=temperature, max_tokens=max_tokens, media_resolution=media_resolution)
    j = parse_json(text)
    j = j if isinstance(j, dict) else {}
    rx, ry = _rating(j.get("rating_x")), _rating(j.get("rating_y"))
    ra, rb = (rx, ry) if order == "ab" else (ry, rx)
    return {"order": order, "persona": persona.get("name"), "rating_x": rx, "rating_y": ry, "rating_a": ra,
            "rating_b": rb, "reasons": " ".join(str(j.get("reasons") or "").split())[:500], "ok": rx is not None and ry is not None}


# ----------------------------------------------------------------- aggregation

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def aggregate(judgments: list[dict[str, Any]], personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Average each persona's (a - b) across orders, then soft-vote into p(A > B)."""
    per: list[dict[str, Any]] = []
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
    if not per:
        return {"p_a": 0.5, "mean_diff": 0.0, "se": 0.0, "winner": "tie", "votes": {"A": 0, "B": 0, "tie": 0},
                "personas": [], "orders": order_view, "n_personas": 0}
    diffs = [x["diff"] for x in per]
    mean = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else 0.0
    p_a = statistics.fmean(x["p_a"] for x in per)
    votes = {"A": sum(d > 0 for d in diffs), "B": sum(d < 0 for d in diffs), "tie": sum(d == 0 for d in diffs)}
    winner = "A" if p_a > 0.5 + 1e-9 else "B" if p_a < 0.5 - 1e-9 else "tie"
    return {"p_a": p_a, "mean_diff": mean, "se": se, "winner": winner, "votes": votes, "personas": per,
            "orders": order_view, "n_personas": len(per)}


async def compare_pair(ev_a: PairEvidence, ev_b: PairEvidence, personas: list[dict[str, Any]] | None,
                       ctx: dict[str, Any], flags: PairFlags | None = None, *, call: Call | None = None) -> dict[str, Any]:
    """Which version would these personas act on? Returns p(A>B), mean diff +- SE, votes, rationale, raw judgments."""
    flags = flags or PairFlags()
    call = call or default_call
    if not personas:
        personas = await plan_personas(ctx, call=call)
    goal, diffs, gd = "", None, None
    if flags.goal_diffs:
        gd = await extract_goal_and_diffs(ev_a, ev_b, ctx, call=call, both_orders=flags.both_orders,
                                          media_resolution=flags.media_resolution)
        goal, diffs = gd["goal"], gd["diffs"] or None
    orders = ORDERS if flags.both_orders else ORDERS[:1]
    judgments = await asyncio.gather(*(
        judge_pair(p, ev_a, ev_b, goal, diffs, o, flags.temperature, flags.debias, ctx=ctx, call=call,
                   key=f"judge|{o}|{k}", max_tokens=flags.max_tokens, media_resolution=flags.media_resolution)
        for o in orders for k, p in enumerate(personas)
    ))
    for (o, k), j in zip([(o, k) for o in orders for k in range(len(personas))], judgments):
        j["k"] = k
    agg = aggregate(list(judgments), personas)
    w = agg["winner"]
    backers = [x for x in agg["personas"] if (x["diff"] > 0 if w == "A" else x["diff"] < 0 if w == "B" else False)]
    backers.sort(key=lambda x: -abs(x["diff"]))
    rationale = [f"{x['persona']}: {next(iter(x['reasons'].values()), '')}" for x in backers[:3]]
    return {
        **agg,
        "label_a": ev_a.label, "label_b": ev_b.label, "flags": flags.name(),
        "goal": goal, "diffs": diffs or [], "goal_diffs_by_order": (gd or {}).get("by_order"),
        "rationale": rationale, "judgments": list(judgments),
        "failed_judgments": sum(not j["ok"] for j in judgments),
    }
