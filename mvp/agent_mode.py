"""Agent mode: predict how a kind of user will experience a product from review data alone (no browser).

What it uses, and why (held-out results in experiments/human_experience/results/):
- Ratings: the product's OWN most recent reviews (last 100), shrunk toward its rivals' average with k=10
  (heldout_bench: beat every rivals-only / people-like-them prior on all four Capterra and G2 held-out sets).
  With no own reviews, the rivals' average. Per-person factors (role, size, tenure, industry) and the model's own
  guess added nothing to ratings once the level was right (calibrate.py), so ratings are not personalised.
- Persona adjustment: within-product offsets per role / company size / time using the product / industry, learned
  across Capterra products (agent_mode_offsets.json, from personalize.py). Small but held out: it raised per-person
  rank within a product (recommend Spearman 0.00 -> 0.13, ease 0.02 -> 0.10) and cut RMSE on 6 of 7 test sets.
  Time using the product carries most of it: free-trial users recommend about 0.5 points lower than the product's mean.
- Words (pros, cons, overall experience): a model writes them for this persona from the reviews of the most similar
  people, on the product itself and on its rivals, plus the rivals' complaint-topic rates (review-context handoff).
All review data comes from live scrapes (mvp.review_context.live_reviews) of the product and its named rivals. If
something is missing the result says what, and nothing is substituted.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from mvp import review_context as RC
from mvp import review_signals as RS

LAST = 100  # own reviews used for the rating level
K = 10.0  # shrinkage toward the rivals' average, in reviews
SIMILAR = 8
# live-scrape fields -> output scale; G2's 1-7 ease is rescaled to 1-5
RATINGS = {"overall_rating": (("rating", 1.0, 5.0),), "ease_of_use_rating": (("ease", 1.0, 5.0), ("ease_1_7", 1.0, 7.0)),
           "recommendation_score": (("nps", 0.0, 10.0),)}
OUT_SCALE = {"overall_rating": (1.0, 5.0), "ease_of_use_rating": (1.0, 5.0), "recommendation_score": (0.0, 10.0)}

WORDS_PROMPT = """Predict how THIS kind of user will experience {product}, from reviews by real users. Do not invent
features; use only what the evidence supports.

- Product: {product} ({url})
- Persona: {persona}
- Task: {task}

{evidence}

Return JSON:
{{"pros": [up to 3 short specific things this user will likely like],
 "cons": [up to 3 short specific things that will likely frustrate them],
 "overall_experience": "2-3 sentences, third person",
 "likely_frictions": [up to 3 short specific sentences about problems similar users report]}}"""


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _values(reviews: list[dict], out: str) -> list[float]:
    lo_o, hi_o = OUT_SCALE[out]
    vals = []
    for r in reviews:
        for key, lo, hi in RATINGS[out]:
            v = _num(r.get(key))
            if key != "nps" and v == 0:  # the Capterra scrape uses 0 for "not rated"; an NPS of 0 is real
                v = None
            if v is not None and lo <= v <= hi:
                vals.append(lo_o + (v - lo) * (hi_o - lo_o) / (hi - lo))
                break
    return vals


def rating_estimates(own: list[dict], rivals: list[dict]) -> dict[str, dict[str, Any]]:
    """Per output: expected rating = (sum of last-LAST own + K * rivals mean) / (n_own + K). Own reviews are taken in
    the order the scrapers return them (most recent first)."""
    out = {}
    for name in OUT_SCALE:
        mine = _values(own, name)[:LAST]
        theirs = _values(rivals, name)
        if not mine and not theirs:
            out[name] = {"estimate": None, "basis": "no ratings in the scraped reviews"}
            continue
        prior = sum(theirs) / len(theirs) if theirs else None
        if mine and prior is not None:
            est, basis = (sum(mine) + K * prior) / (len(mine) + K), "own reviews shrunk to rivals"
        elif mine:
            est, basis = sum(mine) / len(mine), "own reviews only (no rival ratings)"
        else:
            est, basis = prior, "rivals only (no own reviews)"
        out[name] = {"estimate": round(est, 2), "basis": basis, "n_own": len(mine), "n_rivals": len(theirs),
                     "own_mean": round(sum(mine) / len(mine), 2) if mine else None,
                     "rivals_mean": round(prior, 2) if prior is not None else None}
    return out


@lru_cache(maxsize=1)
def _offsets() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("agent_mode_offsets.json")).read_text())


TENURE_ALIASES = {"trial": "I used a free trial", "free trial": "I used a free trial", "new": "Less than 6 months",
                  "<6 months": "Less than 6 months", "6-12 months": "6-12 months", "1-2 years": "1-2 years", "2+ years": "2+ years"}


def _size_band(v: str) -> str | None:
    """'11-50', '11-50 employees', '30 people' -> Capterra's band; None if it can't be read."""
    t = str(v or "").lower().replace(",", "")
    if "self" in t:
        return "Self-employed"
    m = re.search(r"\d+", t)
    if not m:
        return None
    n = int(m.group())
    for hi, band in ((10, "1-10 employees"), (50, "11-50 employees"), (200, "51-200 employees"), (500, "201-500 employees"),
                     (1000, "501-1,000 employees"), (5000, "1,001-5,000 employees"), (10000, "5,001-10,000 employees")):
        if n <= hi:
            return band
    return "10,001+ employees"


def persona_levels(persona: dict[str, Any]) -> dict[str, str]:
    """The persona's factor levels as the offsets table names them (only the ones that could be read)."""
    out = {}
    fam = RS.role_family(persona.get("role") or "")
    if fam != "unknown":
        out["role_family"] = fam
    if persona.get("company_size") and _size_band(persona["company_size"]):
        out["size_fine"] = _size_band(persona["company_size"])
    tu = str(persona.get("time_used") or "").strip()
    if tu:
        out["time_used"] = TENURE_ALIASES.get(tu.lower(), tu)
    if persona.get("industry"):
        out["industry"] = str(persona["industry"]).strip()
    return out


def personalize(ratings: dict[str, dict[str, Any]], persona: dict[str, Any]) -> None:
    """Adds for_this_persona = estimate + weight * sum of the persona's within-product offsets (in place)."""
    levels = persona_levels(persona)
    for name, rec in ratings.items():
        cfg = _offsets()["outputs"].get(name)
        if rec.get("estimate") is None or not cfg:
            continue
        used = {}
        for f, v in levels.items():
            table = cfg["factors"].get(f, {})
            key = next((k for k in table if k.lower() == v.lower()), None)
            if key is not None:
                used[f"{f}={key}"] = table[key]
        lo, hi = OUT_SCALE[name]
        rec["for_this_persona"] = round(min(hi, max(lo, rec["estimate"] + cfg["weight"] * sum(used.values()))), 2)
        rec["persona_offsets"] = used


def _similar(reviews: list[dict], persona: dict, k: int = SIMILAR) -> list[dict]:
    role = RS.role_family(persona.get("role") or persona.get("bio") or "")
    size = str(persona.get("company_size") or "").lower()
    ind = str(persona.get("industry") or "").lower()

    def score(r):
        return (3 * (RS.role_family(str(r.get("role") or "")) == role and role != "unknown")
                + 2 * bool(size and size in str(r.get("size") or "").lower())
                + bool(ind and ind in str(r.get("industry") or "").lower()))
    return sorted(reviews, key=lambda r: -score(r))[:k]


def _fmt(r: dict) -> str:
    head = f"[{r.get('product') or '?'} | {r.get('source')}] role: {r.get('role') or '-'}; size: {r.get('size') or '-'}; rating: {r.get('rating') or '-'}"
    if r.get("text"):
        return head + f"\nReview: {RS.clean(r.get('text'))[:700]}"
    return head + f"\nLiked: {RS.clean(r.get('pros'))[:400]}\nDisliked: {RS.clean(r.get('cons'))[:400]}"


def evidence_text(product: str, own: list[dict], rivals: list[dict], persona: dict) -> str:
    parts = []
    if own:
        parts.append(f"## Reviews of {product} by the most similar people\n" + "\n\n".join(_fmt(r) for r in _similar(own, persona)))
    if rivals:
        cons = [str(x.get("cons") or x.get("text") or "").lower() for x in rivals if x.get("cons") or x.get("text")]
        if cons:
            parts.append("## Complaint topics in rivals' reviews\n" + "\n".join(
                f"- {k.replace('complaint_', '')}: {sum(bool(re.search(p, c)) for c in cons) / len(cons):.0%}" for k, p in RS.TOPICS.items()))
        parts.append("## Reviews of rival products by the most similar people\n" + "\n\n".join(_fmt(r) for r in _similar(rivals, persona)))
    return "\n\n".join(parts)


def gather(product: str, rivals: list[str], wait_s: float) -> dict[str, Any]:
    """Start (or reuse) live scrapes of the product and its rivals; wait up to wait_s for them."""
    names = [product] + [r for r in rivals if r and r != product]
    RC.prefetch(names)
    deadline = time.monotonic() + max(0.0, wait_s)
    got = {n: RC.cached_live_reviews(n) for n in names}
    while any(v is None for v in got.values()) and time.monotonic() < deadline:
        time.sleep(3)
        got = {n: (v if v is not None else RC.cached_live_reviews(n)) for n, v in got.items()}
    return got


async def discover_rivals(url: str) -> list[str]:
    """Rival names from the study planner (web search + live-URL checks), as the browser studies get them."""
    from mvp.fast_plan import compare_plan_from_url

    plan = await compare_plan_from_url(url) or {}
    names = plan.get("competitor_names") or {}
    return [str(names.get(u) or "").strip() for u in plan.get("competitors") or [] if str(names.get(u) or "").strip()]


async def predict_experience(*, product: str, url: str, persona: dict[str, Any], task: str = "",
                             competitors: list[str] | None = None, wait_s: float = 45.0, llm=None,
                             discover=None) -> dict[str, Any]:
    """The agent-mode result. status: ok | pending (scrapes still running; call again) | no_data | disabled.

    No competitors given and a URL given: rivals are discovered with the study planner (said in evidence)."""
    product, rivals = (product or "").strip(), [c.strip() for c in (competitors or []) if c and c.strip()]
    rivals_source = "given" if rivals else "none"
    if not product:
        return {"mode": "agent", "status": "no_data", "reason": "product name is required (it is what the scrapers search for)"}
    if not RC.enabled():
        return {"mode": "agent", "status": "disabled", "reason": "MVP_REVIEW_CONTEXT=0"}
    if not RC.apify_token():
        return {"mode": "agent", "status": "no_data", "reason": "APIFY_TOKEN is not set on the server, so no reviews can be scraped"}
    if not rivals and url:
        try:
            rivals = await (discover or discover_rivals)(url)
            rivals_source = "discovered by the study planner" if rivals else "planner found none"
        except Exception as exc:  # noqa: BLE001 - proceed on the product's own reviews; say so
            rivals_source = f"discovery failed: {type(exc).__name__}"
    got = await asyncio.to_thread(gather, product, rivals, wait_s)
    pending = [n for n, v in got.items() if v is None]
    if got.get(product) is None:
        return {"mode": "agent", "status": "pending", "pending": pending,
                "reason": "live review scrapes take 1-2 minutes; call usersim_predict_experience again with the same arguments"}
    own = got[product]["reviews"]
    riv = [x for n in rivals if got.get(n) for x in got[n]["reviews"]]
    errors = [e for v in got.values() if v for e in v.get("errors", [])]
    missing = [n for n in rivals if got.get(n) is not None and not got[n]["reviews"]]
    if not own and not riv:
        return {"mode": "agent", "status": "no_data", "pending": pending, "errors": errors,
                "reason": f"no reviews found for {product}" + (f" or its rivals {rivals}" if rivals else "; name its competitors to use theirs")}
    ratings = rating_estimates(own, riv)
    personalize(ratings, persona)
    ev = evidence_text(product, own, riv, persona)
    words: dict[str, Any] = {}
    if llm is None:
        from capability.gemini_config import extract_json, gemini_chat

        async def llm(prompt: str) -> dict:  # noqa: F811 - default model call
            raw = await gemini_chat([{"role": "system", "content": "You predict user experience from review evidence. Return JSON only."},
                                     {"role": "user", "content": prompt}], temperature=0.3, json_mode=True)
            j = extract_json(raw)
            return j if isinstance(j, dict) else {}
    try:
        words = await llm(WORDS_PROMPT.format(product=product, url=url or "-", persona=json.dumps(persona, ensure_ascii=False),
                                              task=task or "not stated", evidence=ev[:12000]))
    except Exception as exc:  # noqa: BLE001 - ratings still stand; say why the words are missing
        words = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {
        "mode": "agent", "status": "ok", "product": product, "persona": persona, "task": task,
        "ratings": ratings,
        "pros": words.get("pros") or [], "cons": words.get("cons") or [],
        "overall_experience": words.get("overall_experience") or "", "likely_frictions": words.get("likely_frictions") or [],
        "words_error": words.get("error"),
        "evidence": {"own_reviews": len(own), "rival_reviews": len(riv), "rivals": rivals, "rivals_source": rivals_source,
                     "rivals_with_reviews": sorted({x["product"] for x in riv}),
                     "rivals_without_reviews": missing, "still_scraping": pending, "errors": errors},
        "how_to_read": ("ratings.*.estimate is the expected level for users of this product (own recent reviews, shrunk to "
                        "rivals). for_this_persona adds small within-product offsets for this persona's role, company size, "
                        "time using the product and industry (persona_offsets lists them). Pros/cons are "
                        "written for this persona from the most similar reviewers. Nothing here was observed in a browser; "
                        "use human mode (usersim_start_session) to see the product first-hand."),
    }
