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
import math
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
           "recommendation_score": (("nps", 0.0, 10.0),), "functionality_rating": (("functionality", 1.0, 5.0),),
           "value_for_money_rating": (("value", 1.0, 5.0),), "customer_support_rating": (("support", 1.0, 5.0),)}
OUT_SCALE = {"overall_rating": (1.0, 5.0), "ease_of_use_rating": (1.0, 5.0), "recommendation_score": (0.0, 10.0),
             "functionality_rating": (1.0, 5.0), "value_for_money_rating": (1.0, 5.0), "customer_support_rating": (1.0, 5.0)}

# The predictor prompt validated on held-out reviewers (experiments/staged_context/router_eval.py PRED + matched.PRED_SYSTEM,
# with thinking on). Its ratings are ignored: agent mode computes ratings from the data, which tested better.
WORDS_SYSTEM = ("You forecast a specific historical reviewer's reported experience of a software product from incomplete "
                "context. Never write a first-person testimonial. Return JSON only.")
WORDS_PROMPT = """Predict how THIS person experienced {product}. Their review is hidden; you only know the context below.

- Product: {product} ({url})
- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size}
- Time using {product}: {time_used}
- Task: {task}
- Previous product / alternatives: {previous}

Return JSON:
{{"ease_of_use_rating": 1-5, "functionality_rating": 1-5, "overall_rating": 1-5, "value_for_money_rating": 1-5,
 "customer_support_rating": 1-5, "recommendation_score": 0-10,
 "pros": [up to 3 short specific things they liked], "cons": [up to 3 short specific things that frustrated them],
 "overall_experience": "2-3 sentences summarising their experience, in third person"}}
{evidence}"""
WORDS_THINKING = 1024


def words_prompt(product: str, url: str, persona: dict[str, Any], task: str, evidence: str) -> str:
    role = str(persona.get("role") or persona.get("bio") or "")
    return WORDS_PROMPT.format(product=product, url=url or "no URL given", role_title=role or "not stated",
                               role_family=RS.role_family(role), industry=persona.get("industry") or "not stated",
                               company_size=persona.get("company_size") or "not stated",
                               time_used=persona.get("time_used") or "not stated", task=task or "not stated",
                               previous=persona.get("previous") or "not stated", evidence=evidence)


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


@lru_cache(maxsize=1)
def _segments() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("agent_mode_segments.json")).read_text())


def people_like_them(persona: dict[str, Any]) -> str:
    """The handoff's people-like-this-person section (tested in the held-out winner), from aggregate segment stats
    over Capterra reviews of 66 products (agent_mode_segments.json). Shrunk deviations, k=20, as ux_mcp did."""
    seg, levels = _segments(), persona_levels(persona)
    keys = {"role_family": "role_family", "size_fine": "company_size", "time_used": "time_used", "industry": "industry"}
    found = {}
    for f, v in levels.items():
        table = seg["factors"].get(keys[f], {})
        k = next((x for x in table if x.lower() == v.lower()), None)
        if k is not None:
            found[keys[f]] = (k, table[k])
    if not found:
        return ""
    lines = []
    for r, mu in seg["all"].items():
        dev, parts = 0.0, []
        for f, (k, st) in found.items():
            if r in st:
                m, n = st[r]
                dev += (m * n + 20 * mu) / (n + 20) - mu
                parts.append(f"{f} '{k}': {m:.2f} (n={n})")
        lo, hi = {"recommendation_score": (0, 10)}.get(r, (1, 5))
        lines.append(f"- {r}: all reviewers {mu:.2f}; " + "; ".join(parts) + f"; combined estimate {min(hi, max(lo, mu + dev)):.2f}")
    for f, (k, st) in found.items():
        lines.append(f"- unhappy share (overall<=3 or recommend<=6) for {f} '{k}': {st['unhappy']:.1%} vs {seg['unhappy_all']:.1%} overall")
    return "## People like this person (other software products)\n" + "\n".join(lines)


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


MOST_LIKELY_T = 0.25  # heldout_bench median rule, chosen on DEV (Capterra); MAE 0.55 on TEST


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
        # ratings are whole numbers skewed to the top, so the single most likely score sits above the mean
        rec["most_likely"] = int(min(hi, max(lo, math.ceil(rec["for_this_persona"] - MOST_LIKELY_T))))


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
    """One review with every field that carries the reviewer's view (summary text included: it tested best for the
    overall-experience output)."""
    head = (f"[{r.get('product') or '?'} | {r.get('source')}] role: {r.get('role') or '-'}; size: {r.get('size') or '-'}; "
            f"time used: {r.get('time_used') or '-'}; rating: {r.get('rating') or '-'}")
    body = [f"{label}: {RS.clean(r.get(k))[:600]}" for k, label in (("pros", "Liked"), ("cons", "Disliked"), ("text", "Review"))
            if RS.clean(r.get(k))]
    return "\n".join([head] + body)


def evidence_text(product: str, own: list[dict], rivals: list[dict], persona: dict,
                  ratings: dict[str, dict[str, Any]] | None = None) -> str:
    """Laid out like the held-out winner (own_reviews_bench `own_similar`): rivals' ratings and complaint topics, the
    most similar people's rival reviews, then the product's own rating line and its most similar earlier reviewers."""
    parts = [x for x in [people_like_them(persona)] if x]
    if rivals:
        names = sorted({str(x.get("product") or "") for x in rivals if x.get("product")})
        cons = [str(x.get("cons") or x.get("text") or "").lower() for x in rivals if x.get("cons") or x.get("text")]
        avg = "; ".join(f"{k} {sum(v) / len(v):.2f}" for k, v in ((k, _values(rivals, k)) for k in OUT_SCALE) if v)
        topics = "\n".join(f"- {k.replace('complaint_', '')}: {sum(bool(re.search(p, c)) for c in cons) / len(cons):.1%} mention it"
                           for k, p in RS.TOPICS.items()) if cons else "- (no complaint text)"
        parts.append(f"## Same-category competitors\nCompetitors: {', '.join(names)} ({len(rivals)} reviews).\n"
                     f"Average ratings: {avg}\nComplaint topics in their cons:\n{topics}")
        parts.append("## Reviews of competitor products by the most similar people\n" + "\n\n".join(_fmt(r) for r in _similar(rivals, persona)))
    if own:
        lines = []
        for k, rec in (ratings or {}).items():
            if rec.get("estimate") is not None and rec.get("n_own"):
                lines.append(f"- {k}: last {rec['n_own']} reviews of this product average {rec['own_mean']:.2f}; "
                             f"competitors {rec['rivals_mean'] if rec['rivals_mean'] is not None else 'n/a'}; combined estimate {rec['estimate']:.2f}"
                             + (f"; for people like this person {rec['for_this_persona']:.2f}" if rec.get("for_this_persona") is not None else ""))
        parts.append(f"## This product's own earlier reviews (other people; {len(own)} available)\nRatings:\n" + "\n".join(lines)
                     + "\n\nMost similar earlier reviewers:\n" + "\n\n".join(_fmt(r) for r in _similar(own, persona)))
    return "\nData:\n" + "\n\n".join(parts) if parts else ""


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


NAME_RIVALS_PROMPT = """Name the direct competitors of the product at {url}{about}: products a buyer would compare it
against for the same job and the same kind of customer. Real, currently sold software only, most direct first, using
the exact names they are listed under on G2 / Capterra / TrustRadius (established products with reviews are most useful;
include them even if the product is new). Do not include the product itself or another edition of it.
Return {{"competitors": ["name", ...]}} with up to {n} names."""


async def discover_rivals(url: str, about: str = "", llm_json=None, n: int = 6) -> list[str]:
    """Rival names for a product that has none given: the study planner's (web search + live-URL checks) plus up to n
    named by the model under their review-site names. The YC test found the planner alone often names 2 rivals that
    are not competitors or have no reviews, so more candidates go in and the identity gate keeps the real ones."""
    from mvp.fast_plan import compare_plan_from_url

    async def planner() -> list[str]:
        try:
            plan = await compare_plan_from_url(url) or {}
        except Exception:  # noqa: BLE001 - the named list still stands
            return []
        names = plan.get("competitor_names") or {}
        return [str(names.get(u) or "").strip() for u in plan.get("competitors") or [] if str(names.get(u) or "").strip()]

    async def named() -> list[str]:
        try:
            j = await (llm_json or _default_judge)(NAME_RIVALS_PROMPT.format(url=url, about=f" ({about})" if about else "", n=n))
        except Exception:  # noqa: BLE001
            return []
        return [str(x).strip() for x in (j.get("competitors") or []) if isinstance(x, str) and x.strip()][:n]

    a, b = await asyncio.gather(planner(), named())
    seen, out = set(), []
    for x in b + a:  # review-site names first: they are what the scrapers can find
        k = re.sub(r"[^a-z0-9]", "", x.lower())
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out[:8]


IDENTITY_PROMPT = """Product: {product} ({url}).
Review sites returned these reviews when searched for "{product}" (listed on the sites as: {found_as}):
{sample}

Are these reviews of THIS product, the one at {url}? Different products that share a name (another company's "{product}")
do not count. Return {{"same_product": true/false, "why": "<one sentence>"}}"""

RIVAL_PROMPT = """Product: {product} ({url}).
"{rival}" was named as a competitor. Review sites returned these reviews for "{rival}" (listed as: {found_as}):
{sample}

Return {{"reviews_are_of_named_product": true/false, "direct_competitor": "yes" | "partly" | "no", "why": "<one sentence>"}}.
"yes" = a buyer of {product} would seriously compare the two for the same job; "partly" = overlapping job or a different
buyer; "no" = a different job."""


def _sample(reviews: list[dict], k: int = 6) -> str:
    rows = [r for r in reviews if r.get("pros") or r.get("text") or r.get("cons")][:k]
    clip = lambda v: RS.clean(v)[:220] if v else "-"  # noqa: E731
    return "\n".join(f"- [{r.get('source')}; {r.get('role') or 'role n/a'}] liked: {clip(r.get('pros'))} | disliked: "
                     f"{clip(r.get('cons'))} | {clip(r.get('text'))}" for r in rows) or "(no review text)"


async def check_identity(product: str, url: str, own: list[dict], rivals: dict[str, list[dict]], judge) -> dict[str, Any]:
    """Model checks, in parallel (the YC test found same-name products and planner rivals that don't compete):
    own reviews must be of the product at `url`; each rival's reviews must be of that rival, and it must compete."""
    async def one(prompt: str) -> dict:
        try:
            j = await judge(prompt)
            return j if isinstance(j, dict) else {}
        except Exception as exc:  # noqa: BLE001 - an unchecked source is reported, not trusted
            return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    found = lambda revs: ", ".join(sorted({str(r.get("product") or "?") for r in revs}))[:200]  # noqa: E731
    jobs = []
    if own:
        jobs.append(one(IDENTITY_PROMPT.format(product=product, url=url, found_as=found(own), sample=_sample(own))))
    names = [n for n, revs in rivals.items() if revs]
    jobs += [one(RIVAL_PROMPT.format(product=product, url=url, rival=n, found_as=found(rivals[n]), sample=_sample(rivals[n])))
             for n in names]
    res = await asyncio.gather(*jobs)
    out = {"own": None, "rivals": {}}
    if own:
        j = res.pop(0)
        out["own"] = {"ok": j.get("same_product") is True, "why": j.get("why") or j.get("error") or "no answer"}
    for n, j in zip(names, res):
        ok = j.get("reviews_are_of_named_product") is True and j.get("direct_competitor") in ("yes", "partly")
        out["rivals"][n] = {"ok": ok, "direct": j.get("direct_competitor"), "why": j.get("why") or j.get("error") or "no answer"}
    return out


async def _default_judge(prompt: str) -> dict:
    from capability.gemini_config import extract_json, gemini_chat

    raw = await gemini_chat([{"role": "system", "content": "You know the B2B software market. Return JSON only."},
                             {"role": "user", "content": prompt}], temperature=0.0, json_mode=True, thinking_budget=512)
    j = extract_json(raw)
    return j if isinstance(j, dict) else {}


PROFILE_PROMPT = """{product} ({url}) is a new product. Real users of its direct competitors ({rivals}) wrote these reviews:
{sample}

From these reviews only, return JSON:
{{"use_cases": [5 concrete things people use products like this for, as short imperative tasks a new user of {product} could try, most common first],
 "what_users_value": [5 short specific things users of these products like most, most common first],
 "what_frustrates_users": [5 short specific complaints, most common first],
 "switching_reasons": [up to 3 reasons people say they chose or left one of these products, if stated]}}"""


def _mix(values: list[Any], top: int = 6) -> dict[str, float]:
    vals = [str(v).strip() for v in values if v not in (None, "") and str(v).strip() and str(v).strip().lower() != "unknown"]
    if not vals:
        return {}
    counts: dict[str, int] = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    return {k: round(c / len(vals), 3) for k, c in sorted(counts.items(), key=lambda kv: -kv[1])[:top]}


def likely_users(rivals: list[dict]) -> dict[str, Any]:
    """Who uses this kind of product: the counted mix of the direct competitors' reviewers. Held out, competitors'
    reviewer mix predicted a product's own mix 2-3x closer than a model guessing (staged_context usage.py) and closer
    than the all-products average (experiments/human_experience/mix_bench.py)."""
    return {"n_reviewers": len(rivals),
            "role_families": _mix([RS.role_family(str(r.get("role") or "")) for r in rivals if r.get("role")]),
            "company_sizes": _mix([r.get("size") for r in rivals]),
            "industries": _mix([str(r.get("industry") or "").lower() for r in rivals]),
            "review_sites": _mix([r.get("source") for r in rivals])}


async def product_profile(product: str, url: str, rivals_by_name: dict[str, list[dict]], judge) -> dict[str, Any]:
    """What an agent can know about a NEW product (no reviews of its own) from its checked direct competitors."""
    revs = [r for v in rivals_by_name.values() for r in v]
    out: dict[str, Any] = {"likely_users": likely_users(revs)}
    cons = [str(r.get("cons") or r.get("text") or "").lower() for r in revs if r.get("cons") or r.get("text")]
    if cons:
        out["complaint_topic_rates"] = {k.replace("complaint_", ""): round(sum(bool(re.search(p, c)) for c in cons) / len(cons), 3)
                                        for k, p in RS.TOPICS.items()}
    avg = {k: round(sum(v) / len(v), 2) for k, v in ((k, _values(revs, k)) for k in OUT_SCALE) if v}
    out["competitor_ratings"] = {n: {k: round(sum(v) / len(v), 2) for k, v in ((k, _values(rv, k)) for k in OUT_SCALE) if v}
                                 | {"reviews": len(rv)} for n, rv in rivals_by_name.items()}
    out["competitor_ratings_all"] = avg
    if revs:
        try:
            j = await judge(PROFILE_PROMPT.format(product=product, url=url or "-", rivals=", ".join(rivals_by_name),
                                                  sample=_sample(revs, 40)))
        except Exception as exc:  # noqa: BLE001 - the counted parts still stand
            j = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        for k in ("use_cases", "what_users_value", "what_frustrates_users", "switching_reasons"):
            out[k] = j.get(k) or []
        if j.get("error"):
            out["summary_error"] = j["error"]
    return out


async def predict_experience(*, product: str, url: str, persona: dict[str, Any], task: str = "",
                             competitors: list[str] | None = None, wait_s: float = 45.0, llm=None,
                             discover=None, judge=None) -> dict[str, Any]:
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
    errors = [e for v in got.values() if v for e in v.get("errors", [])]
    missing = [n for n in rivals if got.get(n) is not None and not got[n]["reviews"]]
    # identity gate: no product URL means own reviews can't be checked, so they are not used (said in evidence)
    ident = await check_identity(product, url, own if url else [], {n: got[n]["reviews"] for n in rivals if got.get(n)},
                                 judge or _default_judge)
    own_check = ident["own"] or ({"ok": False, "why": "no product_url given, so the reviews' identity can't be checked"}
                                 if own and not url else None)
    if own_check and not own_check["ok"]:
        own = []
    kept = [n for n, c in ident["rivals"].items() if c["ok"]]
    riv = [x for n in kept for x in got[n]["reviews"]]
    if not own and not riv:
        return {"mode": "agent", "status": "no_data", "pending": pending, "errors": errors,
                "own_reviews_check": own_check, "rivals_check": ident["rivals"],
                "reason": f"no usable reviews for {product}" + (f" or its rivals {rivals}" if rivals else "; name its competitors to use theirs")
                          + " (see own_reviews_check / rivals_check)"}
    profile = await product_profile(product, url, {n: got[n]["reviews"] for n in kept}, judge or _default_judge)
    ratings = rating_estimates(own, riv)
    personalize(ratings, persona)
    ev = evidence_text(product, own, riv, persona, ratings)
    words: dict[str, Any] = {}
    if llm is None:
        from capability.gemini_config import extract_json, gemini_chat

        async def llm(prompt: str) -> dict:  # noqa: F811 - default model call
            raw = await gemini_chat([{"role": "system", "content": WORDS_SYSTEM}, {"role": "user", "content": prompt}],
                                    temperature=0.7, json_mode=True, thinking_budget=WORDS_THINKING)
            j = extract_json(raw)
            return j if isinstance(j, dict) else {}
    try:
        words = await llm(words_prompt(product, url, persona, task, ev[:14000]))
    except Exception as exc:  # noqa: BLE001 - ratings still stand; say why the words are missing
        words = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {
        "mode": "agent", "status": "ok", "product": product, "persona": persona, "task": task,
        "new_product": not own,
        "product_profile": profile,
        "ratings": ratings,
        "pros": words.get("pros") or [], "cons": words.get("cons") or [],
        "overall_experience": words.get("overall_experience") or "",
        "words_error": words.get("error"),
        "evidence": {"own_reviews": len(own), "rival_reviews": len(riv), "rivals": rivals, "rivals_source": rivals_source,
                     "rivals_with_reviews": sorted({x["product"] for x in riv}),
                     "own_reviews_check": own_check, "rivals_check": ident["rivals"], "rivals_used": kept,
                     "rivals_without_reviews": missing, "still_scraping": pending, "errors": errors},
        "how_to_read": ("ratings.*.estimate is the expected level for users of this product (own recent reviews, shrunk to "
                        "rivals). for_this_persona adds small within-product offsets for this persona's role, company size, "
                        "time using the product and industry (persona_offsets lists them). Pros/cons are "
                        "written for this persona from the most similar reviewers. Nothing here was observed in a browser; "
                        "use human mode (usersim_start_session) to see the product first-hand."),
    }
