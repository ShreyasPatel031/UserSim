"""The four pilot arms on one Show HN post. Every arm writes the same number of top-level comments (N per post).

A twins    one per real commenter (people with MIN_HISTORY+ earlier comments), card from their own comments dated
           before the post, browser run in Atelier human mode, then the comment that person would post
B generic  Atelier's planned personas (mvp.fast_plan.compare_plan_from_url, the website's planner), same browser run
           and writing step
C page     no browser, no personas: a model reads the post text and the landing page (fast_plan's page reader)
D shuffled twins built from the commenters of a different pilot post, run on this product

Twins never see the thread they predict: cards use only comments with created_at before the post (and before the
donor post for D). The browser task and the writing prompt are the same for A, B and D."""
from __future__ import annotations

import asyncio
import json
import random

import pandas as pd

import browser
import llm
import store as S

N = 5
MIN_HISTORY = 20
MAX_ACTIONS = 12

CARD = """Here are the most recent Hacker News comments by one person (newest first), each with the story it was on.
{comments}

Describe this person as a Hacker News reader, only from these comments:
{{"who": "<role, stack, domain, what they work on; 1-2 sentences; say 'unknown' where the comments don't show it>",
  "style": "<how they give feedback: what they usually question, praise or push back on; tone and length>",
  "quotes": ["<3 short verbatim quotes that show how they react to things>"],
  "persona": "<2 sentences in the second person for a simulated user: who you are and what you care about>"}}"""

TASK = """You saw this post on Hacker News (Show HN) and clicked through:
Title: {title}
Post text: {text}
Try the product the way you would: do its core job for real, then try two deeper features or anything the post asks
readers to try. Note what works, what breaks and what confuses you."""

WRITE = """You are this Hacker News reader:
{who}

You read this Show HN post:
Title: {title}
URL: {url}
Post text: {text}

You then tried the product yourself. What you saw:
{obs}
Your notes: {notes}

Write the top-level comment you would post in the thread, in your own voice and length (HN comments are often one or
two sentences). Then name its single main point.
Return {{"comment": "...", "main_point": "<under 15 words>"}}"""

PAGE = """A Show HN post:
Title: {title}
URL: {url}
Post text: {text}

The landing page says:
{page}

Write the {n} top-level comments that different Hacker News readers would most likely post on this thread, each in a
realistic HN voice and length, each from a different reader. Return {{"comments": [{{"comment": "...", "main_point": "<under 15 words>"}}]}}"""

KNOWN = """Do you know this specific product or this Hacker News post from your training data (not just the general
idea)? Title: {title}  URL: {url}
Return {{"known": true/false, "what_you_know": "<one sentence or empty>"}}"""


def known(post: dict) -> bool:
    j = llm.call("known_check", KNOWN.format(title=post["title"], url=post["url"]), model=llm.FLASH)
    return bool(j.get("known"))


def history(author: str, post_id: int, before: int) -> list[dict]:
    c = S.read("hn_comments")
    h = c[(c.role == "history") & (c.author == author) & (c.created_at_i < before)].drop_duplicates("comment_id")
    return h.sort_values("created_at_i", ascending=False).head(50).to_dict("records")


def card(author: str, before: int, hist: list[dict]) -> dict:
    txt = "\n".join(f"- [{str(h['created_at'])[:10]}] on \"{h['story_title']}\": {h['text'][:500]}" for h in hist
                    if h["created_at_i"] < before)
    j = llm.call("twin_card", CARD.format(comments=txt), model=llm.LITE, temperature=0.0)
    return {"person": author, "cutoff": before, "n_comments": len(hist), **{k: j.get(k) for k in ("who", "style",
                                                                                                    "quotes", "persona")}}


def card_text(cd: dict) -> str:
    q = "\n".join(f'  "{x}"' for x in (cd.get("quotes") or [])[:3])
    return f"{cd.get('who')}\nHow you give feedback: {cd.get('style')}\nThings you have said:\n{q}"


def obs_text(r: dict) -> str:
    lines = [f"- [{o.get('kind', '').replace('product_', '')}] {o.get('what')}" for o in r.get("observations") or []
             if o.get("kind") != "agent_failure"]
    if r.get("error"):
        lines.append(f"- (the browser could not open the product: {r['error'][:150]})")
    return "\n".join(lines) or "- (nothing usable: the product did not load or work)"


def write(post: dict, who: str, run: dict, seed: int) -> dict:
    j = llm.call("write_comment", WRITE.format(who=who, title=post["title"], url=post["url"],
                                               text=(post["text"] or "")[:1500], obs=obs_text(run),
                                               notes=str(run.get("notes") or "")[:800]),
                 model=llm.FLASH, temperature=0.7, seed=seed)
    return {"comment": str(j.get("comment") or ""), "main_point": str(j.get("main_point") or "")}


def generic_personas(url: str) -> list[dict]:
    """Atelier's website planner (6 personas); metered by reading usageMetadata from its Vertex responses."""
    import capability.gemini_config as G
    from mvp.fast_plan import compare_plan_from_url
    orig = G._extract_text

    def metered(body):
        u = body.get("usageMetadata") or {}
        inp, out = u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
        m = llm._meter["generic_planner"]
        m[0] += 1; m[1] += inp; m[2] += out; m[3] += inp / 1e6 * 0.30 + out / 1e6 * 2.50  # noqa: E702  (Flash)
        return orig(body)
    G._extract_text = metered
    try:
        p = asyncio.run(compare_plan_from_url(url, timeout=90)) or {}
    finally:
        G._extract_text = orig
    return [x for x in p.get("personas") or [] if isinstance(x, dict) and x.get("bio")]


def page_only(post: dict, seed: int = 0) -> list[dict]:
    from mvp.fast_plan import _page_read, prompt_text
    try:
        page = prompt_text(asyncio.run(_page_read(post["url"])), 2500)
    except Exception as exc:  # noqa: BLE001
        page = f"(page could not be read: {type(exc).__name__})"
    j = llm.call("page_only", PAGE.format(title=post["title"], url=post["url"], text=(post["text"] or "")[:1500],
                                          page=page, n=N), model=llm.FLASH, temperature=0.7, seed=seed)
    cs = [c for c in j.get("comments") or [] if isinstance(c, dict) and c.get("comment")][:N]
    return [{"comment": str(c["comment"]), "main_point": str(c.get("main_point") or "")} for c in cs]


def pick_people(post: dict, seed: int = 0) -> list[str]:
    """N top-level commenters with MIN_HISTORY+ earlier comments, in a fixed random order."""
    ppl = S.read("hn_people")
    hc = ppl[(ppl.get("kind") == "history_count") & (ppl.post_id == post["post_id"])]
    ok = sorted(hc.loc[hc.earlier_comments >= MIN_HISTORY, "person"].unique())
    random.Random(f"{seed}|{post['post_id']}").shuffle(ok)
    return ok[:N]
