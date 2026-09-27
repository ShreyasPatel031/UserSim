"""Shared pairwise A/B judge: which of two versions of a page would these visitors act on?

One code path serves the product (comparison of two sites / two versions from run screenshots) and the
WiserUI-Bench harness (bench/wiserui/run_bench.py). Every component sits behind a flag in :class:`PairFlags`,
so ablation arms differ only in flags:

- ``both_orders``: judge (A, B) and (B, A) and average, which cancels position bias.
- ``goal_diffs``: first infer the site operator's goal and a list of concrete, localized differences
  (G-FOCUS, arXiv 2505.05026v1 Appendix E), in both orders, merged; personas then judge only those differences.
- ``debias``: SimAB-style instructions (more is better only if needed, simplicity under time/price pressure,
  choice overload, ignore goal-irrelevant factors).
- ``argue_both``: the rest of G-FOCUS (Appendix E Parts 3-4): assume the first version is more persuasive for the
  goal and give reasons; separately assume the second is; an evaluator ranks the contradicting reasons by importance
  and names the better version. Replaces the 1-10 ratings. ``v1_prompts`` also swaps steps 1-2 for the paper's
  Part 1 (goal) and Part 2 (difference localization) prompts, run per presentation order; ``use_personas=False``
  runs one neutral evaluator (the paper), otherwise each persona argues and evaluates as that visitor.

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
    # strict_orders: with goal_diffs + both_orders, each presentation order uses ONLY the goal/diffs extracted in that
    # order (no merge across orders), so the two per-order picks are fully independent (paper-style per-order eval).
    strict_orders: bool = False
    # G-FOCUS steps 3-4 (see module docstring). Only read when argue_both is set, so older arms are unchanged.
    argue_both: bool = False
    v1_prompts: bool = False  # steps 1-2 with the v1 Appendix E Part 1/2 prompts (per order, text output)
    use_personas: bool = True  # False: a single neutral evaluator, as in the paper
    argue_temperature: float = 1.0  # the paper ran every model at temperature 1 (Appendix F)

    def name(self) -> str:
        return "+".join(
            ["both" if self.both_orders else "one", "ratings"]
            + (["goal_diffs"] if self.goal_diffs else [])
            + (["debias"] if self.debias else [])
            + (["strict"] if self.strict_orders else [])
            + ((["argue_both"] + (["v1"] if self.v1_prompts else []) + ([] if self.use_personas else ["single"]))
               if self.argue_both else [])
        )


ORDERS = ("ab", "ba")


# ----------------------------------------------------------------- model access

async def default_call(key: str, contents: list, *, temperature: float, max_tokens: int,
                       media_resolution: str | None = None, json_mode: bool = True) -> tuple[str, int, int]:
    from mvp.e2e_ui_run import gemini_generate

    return await asyncio.to_thread(
        gemini_generate, contents, model=PAIRWISE_MODEL, temperature=temperature, max_tokens=max_tokens,
        json_mode=json_mode, media_resolution=media_resolution,
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


# ----------------------------------------------------------------- G-FOCUS steps 1-4 (arXiv 2505.05026v1, Appendix E)
# Prompts are the v1 appendix text; only the placeholders are filled. With a persona, the sentence "Assume that a user
# is currently engaging with the page" names that visitor, and the evaluator also concludes from their point of view
# and gives a 1-5 confidence (used to break ties between personas).

_V1_HEAD = """The two screenshots show two different versions of the same page.
FYI, the page is from the company called '{company}' whose industry domain is {industry}.
The page type is {page_type} on {web_mobile} environment."""

_V1_GOAL = """Your task is to think about the goal of the site operator for the given UIs.

{head}

Based on the two UIs and the industry and page type, what is the main goal of the site operator for this page?

Answer strictly in the following format:
[Goal]
<goal of the site operator considering industry and page type>"""

_V1_DIFFS = """You are an expert in designing UI/UX for web/apps.

{head}

Your task is to find the crucial and major UI differences between the two versions.

To do that,
(1) Reflect what would be the fundamental and crucial design priorities on the current page, if the goal of the site operator on the current page is as follows:
{goal}
(2) "See" the provided screenshots of the page, focusing on the key UI areas related to what you have reflected as your prioritized design principles.
(3) For each key UI area, localize it by imagining patches and highlight main UI differences within the patches of the versions.

Be aware:
- Mention key differences in terms of the given goal and design priorities.
- Do not mention differences in an abstract nor subjective way.
(example to avoid: "First UI has more prominent visual clutter." -> "more prominent": subjective expression, "visual clutter": abstract expression)
- Avoid mentioning differences which can be placeholders that can differ by example cases.
(example to avoid: "First UI has product image of apple, Second UI has banana." -> product images can be just placeholders)
- Prefer to infer comprehensive differences that can be inferred by combining multiple UI components from the images and given information.

You must give the answer and give the answer strictly in the following format:
[Design priorities]
1. <Key priority>
2. <Key priority>
...
[UI areas to focus]
1. <Key UI area>
2. <Key UI area>
...
[Key UI differences]
First UI <Key UI difference>, Second UI <Key UI difference>.
First UI <Key UI difference>, Second UI <Key UI difference>.
..."""

_V1_USER = "Assume that a user is currently engaging with the page shown in the screenshot."

_V1_REASON = """You are an expert in designing UI/UX for web/apps.

{head}

{user}
Inferred main goal of the site operator is as follows:
{goal}

Already found key UI differences between the two versions are as follows:
{ui_diff}

Then, assuming {which} version was more visually persuasive in terms of achieving the inferred goal, you should make reasonable reasons for such result.

Your reply should strictly follow the format.:
[Evaluation]
1. <Rationale of the evaluation in sentences>
2. <Rationale of the evaluation in sentences>
..."""

_V1_EVAL = """You are an expert in designing UI/UX for web/apps.

{head}

{user}
Inferred main goal of the site operator is as follows:
{goal}

Already found key UI differences between the two versions are as follows:
{ui_diff}

Then, we have made possible reasons of why first version would have been more visually persuasive in terms of achieving the inferred goal:
{first_reason}

We also made possible reasons of why second version would have been more visually persuasive in terms of achieving the inferred goal:
{second_reason}

Considering all these possible reasons, your task is to conclude which version would be visually persuasive in terms of achieving the inferred goal.{pov}
Reasons' decisions of first/second version are all different, so you should think carefully reminding:
(1) Reasons may contradict each other, then you should decide which is more reasonable.
(2) Then make your own rankings between the evaluations based on importance for making a final decision.
(3) Based on the rankings, conclude which version would be visually persuasive in terms of achieving the inferred goal with a precise overall rationale that only contains key points that you think are crucial.

Here, such precise overall rationale should be consisted of key points mentioning:
(1) which UI difference was key to the winning version's success and
(2) how each UI difference affected the winning version positively

Your reply should strictly follow the format:
[Importance Ranking]
1. <First/Second + Reason # (e.g. First 2)> - <Why you think this reason is the most important>
2. <First/Second + Reason # (e.g. Second 3)> - <Why you think this reason is the second important>
...
[Conclusion]
Better version: <First/Second>{conf_fmt}
Key Rationale:
* <UI Difference>: <Positive effects>
* ... (if multiple)"""

GFOCUS_JUDGE = {"name": "G-FOCUS evaluator", "role": "", "bio": "", "goal": ""}


def _v1_head(ctx: dict[str, Any]) -> str:
    wm = ctx.get("web_mobile") or ("mobile" if "mobile" in str(ctx.get("platform") or "").lower() else "web")
    return _V1_HEAD.format(company=ctx.get("company") or "", industry=ctx.get("industry") or "",
                           page_type=ctx.get("page_type") or "page", web_mobile=wm)


def _v1_user(persona: dict[str, Any] | None) -> str:
    if not persona:
        return _V1_USER
    who = f"{persona.get('name') or 'a visitor'}, {persona.get('role') or ''}. {persona.get('bio') or ''}".strip()
    return (f"Assume that the following user is currently engaging with the page shown in the screenshot: {who} "
            f"They came to this page to: {persona.get('goal') or 'look around'}.")


def _section(text: str, head: str, stop: tuple[str, ...] = ()) -> str:
    """Text after ``[head]`` up to the next [Section] header (or one of ``stop``); the whole text if absent."""
    t = (text or "").replace("**", "")
    m = re.search(r"\[\s*" + re.escape(head) + r"\s*\]\s*:?", t, re.I)
    if not m:
        return t.strip()
    rest = t[m.end():]
    n = re.search(r"\n\s*\[[A-Z][^\]\n]{2,40}\]", rest)
    return (rest[: n.start()] if n else rest).strip()


def parse_v1_verdict(text: str) -> tuple[str | None, int | None]:
    """(``"First"`` / ``"Second"`` / None, confidence 1-5 or None) from an Evaluator reply."""
    t = (text or "").replace("**", "").replace("*", " ")
    m = re.findall(r"Better\s+version\s*:?\s*(First|Second)", t, re.I)
    pick = m[-1].capitalize() if m else None
    if pick is None:
        concl = _section(t, "Conclusion")
        hits = re.findall(r"\b(First|Second)\b", concl[:200], re.I) if concl != t.strip() else []
        pick = hits[0].capitalize() if hits and len({h.lower() for h in hits}) == 1 else None
    c = re.search(r"Confidence\s*:?\s*([1-5])", t, re.I)
    return pick, (int(c.group(1)) if c else None)


def diffs_text(diffs: list[dict[str, str]] | None, order: str) -> str:
    """Canonical a/b diffs rendered in the paper's "First UI ..., Second UI ..." lines for one presentation order."""
    out = []
    for d in diffs or []:
        x, y = (d["a"], d["b"]) if order == "ab" else (d["b"], d["a"])
        out.append(f"{d['element']}: First UI {x}, Second UI {y}.")
    return "\n".join(out) or "(no clear differences found)"


def _v1_images(first: PairEvidence, second: PairEvidence) -> list:
    """As in the paper's inference code: the prompt, then the first and the second screenshot(s), unlabelled."""
    return [*first.screenshots, *second.screenshots]


async def v1_goal_and_diffs(first: PairEvidence, second: PairEvidence, ctx: dict[str, Any], order: str, *,
                            call: Call, temperature: float = 1.0,
                            media_resolution: str | None = None) -> dict[str, Any]:
    """G-FOCUS Part 1 (goal) then Part 2 (goal-conditioned key UI differences) for ONE presentation order."""
    head = _v1_head(ctx)
    gtext, _, _ = await call(f"v1goal|{order}", [_V1_GOAL.format(head=head), *_v1_images(first, second)],
                             temperature=temperature, max_tokens=600, media_resolution=media_resolution, json_mode=False)
    goal = " ".join(_section(gtext, "Goal").split())[:600]
    dtext, _, _ = await call(f"v1diff|{order}", [_V1_DIFFS.format(head=head, goal=goal), *_v1_images(first, second)],
                             temperature=temperature, max_tokens=2048, media_resolution=media_resolution, json_mode=False)
    return {"goal": goal, "diffs_text": _section(dtext, "Key UI differences")[:4000], "raw_diffs": dtext[:6000]}


async def argue_and_evaluate(first: PairEvidence, second: PairEvidence, ctx: dict[str, Any], goal: str, ui_diff: str,
                             order: str, *, persona: dict[str, Any] | None, call: Call, key: str,
                             temperature: float = 1.0, media_resolution: str | None = None,
                             retries: int = 2) -> dict[str, Any]:
    """G-FOCUS Part 3 (reasons assuming first wins; separately, second wins) and Part 4 (Evaluator) for one order."""
    head, user = _v1_head(ctx), _v1_user(persona)
    imgs = _v1_images(first, second)

    async def reason(which: str) -> str:
        text, _, _ = await call(f"{key}|reason_{which}", [_V1_REASON.format(
            head=head, user=user, goal=goal, ui_diff=ui_diff, which=which), *imgs],
            temperature=temperature, max_tokens=1500, media_resolution=media_resolution, json_mode=False)
        return _section(text, "Evaluation")[:4000]

    r1, r2 = await asyncio.gather(reason("first"), reason("second"))
    prompt = _V1_EVAL.format(
        head=head, user=user, goal=goal, ui_diff=ui_diff, first_reason=r1, second_reason=r2,
        pov=" Conclude from this user's point of view." if persona else "",
        conf_fmt="\nConfidence: <1-5, how sure this user is>" if persona else "")
    pick, conf, text = None, None, ""
    for attempt in range(1 + max(0, retries)):  # the paper's code re-asks when the answer format is missing
        text, _, _ = await call(f"{key}|evaluator" + (f"|r{attempt}" if attempt else ""), [prompt, *imgs],
                                temperature=temperature, max_tokens=2048, media_resolution=media_resolution,
                                json_mode=False)
        pick, conf = parse_v1_verdict(text)
        if pick:
            break
    w = float(conf or 1) if persona else 1.0
    rx, ry = ((w, 0.0) if pick == "First" else (0.0, w) if pick == "Second" else (None, None))
    ra, rb = (rx, ry) if order == "ab" else (ry, rx)
    return {"order": order, "persona": (persona or GFOCUS_JUDGE).get("name"), "pick": pick, "confidence": conf,
            "rating_x": rx, "rating_y": ry, "rating_a": ra, "rating_b": rb, "ok": pick is not None,
            "reasons": " ".join(_section(text, "Conclusion").split())[:500],
            "reasons_first": r1[:2000], "reasons_second": r2[:2000], "evaluator": text[:4000]}


async def compare_pair_gfocus(ev_a: PairEvidence, ev_b: PairEvidence, personas: list[dict[str, Any]] | None,
                              ctx: dict[str, Any], flags: PairFlags, *, call: Call) -> dict[str, Any]:
    """Full G-FOCUS: goal, goal-conditioned differences, argue both sides, Evaluator; per judge and order.

    Each judge-order gives a pick (as rating_x/rating_y = weight/0, weight = persona confidence or 1), so
    :func:`aggregate` yields per-order picks (confidence-weighted persona vote) and an order-free p(A>B).
    With ``v1_prompts`` or ``strict_orders`` each order only sees the goal/differences extracted in that order.
    """
    orders = ORDERS if flags.both_orders else ORDERS[:1]
    judges = [GFOCUS_JUDGE]
    if flags.use_personas:
        judges = personas or await plan_personas(ctx, call=call)
    t = flags.argue_temperature
    per_order: dict[str, dict[str, Any]] = {}
    if flags.v1_prompts or not flags.goal_diffs:
        got = await asyncio.gather(*(v1_goal_and_diffs(*_ordered(ev_a, ev_b, o), ctx, o, call=call, temperature=t,
                                                       media_resolution=flags.media_resolution) for o in orders))
        per_order = dict(zip(orders, got))
    else:
        gd = await extract_goal_and_diffs(ev_a, ev_b, ctx, call=call, both_orders=flags.both_orders,
                                          media_resolution=flags.media_resolution)
        for o in orders:
            g, d = ((gd["by_order"].get(o, {}).get("goal", ""), gd["by_order"].get(o, {}).get("diffs"))
                    if flags.strict_orders else (gd["goal"], gd["diffs"]))
            per_order[o] = {"goal": g, "diffs_text": diffs_text(d, o), "diffs": d}
    cells = [(o, k, p) for o in orders for k, p in enumerate(judges)]
    judgments = await asyncio.gather(*(
        argue_and_evaluate(*_ordered(ev_a, ev_b, o), ctx, per_order[o]["goal"], per_order[o]["diffs_text"], o,
                           persona=p if flags.use_personas else None, call=call,
                           key=f"argue|{o}|{k if flags.use_personas else 'single'}", temperature=t,
                           media_resolution=flags.media_resolution)
        for o, k, p in cells))
    for (o, k, _), j in zip(cells, judgments):
        j["k"] = k
    agg = aggregate(list(judgments), judges)
    w = agg["winner"]
    backers = [j for j in judgments if j["ok"] and ((j["rating_a"] > j["rating_b"]) if w == "A" else
                                                   (j["rating_a"] < j["rating_b"]) if w == "B" else False)]
    return {
        **agg,
        "label_a": ev_a.label, "label_b": ev_b.label, "flags": flags.name(),
        "goal": per_order[orders[0]]["goal"], "diffs": [], "goal_diffs_by_order": per_order,
        "rationale": [f"{j['persona']}: {j['reasons']}" for j in backers[:3]], "judgments": list(judgments),
        "failed_judgments": sum(not j["ok"] for j in judgments),
    }


async def compare_pair(ev_a: PairEvidence, ev_b: PairEvidence, personas: list[dict[str, Any]] | None,
                       ctx: dict[str, Any], flags: PairFlags | None = None, *, call: Call | None = None) -> dict[str, Any]:
    """Which version would these personas act on? Returns p(A>B), mean diff +- SE, votes, rationale, raw judgments."""
    flags = flags or PairFlags()
    call = call or default_call
    if flags.argue_both:
        return await compare_pair_gfocus(ev_a, ev_b, personas, ctx, flags, call=call)
    if not personas:
        personas = await plan_personas(ctx, call=call)
    goal, diffs, gd = "", None, None
    if flags.goal_diffs:
        gd = await extract_goal_and_diffs(ev_a, ev_b, ctx, call=call, both_orders=flags.both_orders,
                                          media_resolution=flags.media_resolution)
        goal, diffs = gd["goal"], gd["diffs"] or None
    orders = ORDERS if flags.both_orders else ORDERS[:1]
    per_order = {o: (goal, diffs) for o in orders}
    if gd and flags.strict_orders:
        per_order = {o: (gd["by_order"].get(o, {}).get("goal", ""), gd["by_order"].get(o, {}).get("diffs") or None)
                     for o in orders}
    judgments = await asyncio.gather(*(
        judge_pair(p, ev_a, ev_b, per_order[o][0], per_order[o][1], o, flags.temperature, flags.debias, ctx=ctx, call=call,
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
