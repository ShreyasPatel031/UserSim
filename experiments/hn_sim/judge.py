"""Label real (and simulated) top-level comments: one main kind + the specific point, plus up to 2 more points.

    python judge.py label            # every non-maker top-level comment on the deep posts -> judge_labels
    python judge.py sample 50        # 50 comments for the hand check (stratified by post)
    python judge.py agree <hand.json>
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import llm
import store as S

KINDS = ["praise", "question", "bug", "confusion", "pricing", "feature_ask", "competitor_comparison", "doubt",
         "other"]
LABEL = """A Show HN post and one top-level comment on it.

Post: {title}
URL: {url}
Post text: {text}

Comment by a reader:
\"\"\"{comment}\"\"\"

Label the comment's main point with ONE kind:
- praise: likes the product or something about it
- question: asks how it works / what it does / plans
- bug: something broken or not working when they tried it
- confusion: unclear UI, copy or purpose; could not figure something out
- pricing: price, business model, free tier, cost
- feature_ask: asks for or suggests a feature or change
- competitor_comparison: compares with or names an existing product / prior art
- doubt: doubts the need, the approach, trust, privacy, safety or legality
- other: off-topic, a joke, a personal story or a tangent not about this product

Then write the specific point in a short phrase (under 15 words), concrete to this product
(e.g. "dark mode toggle missing", "similar to Excalidraw", "crashes on Firefox when exporting").
If the comment makes other distinct points about the product, add up to 2 more.
Return {{"kind": "...", "point": "...", "more": [{{"kind": "...", "point": "..."}}]}}"""


def label_one(post: dict, text: str) -> dict:
    j = llm.call("judge_label", LABEL.format(title=post["title"], url=post["url"], text=(post["text"] or "")[:1500],
                                             comment=text[:3000]), model=llm.FLASH, thinking=512,
                 system="You label Hacker News comments precisely. Return JSON only.")
    pts = [{"kind": j.get("kind"), "point": j.get("point")}] + [m for m in j.get("more") or [] if isinstance(m, dict)][:2]
    pts = [p for p in pts if p.get("kind") in KINDS and p.get("point")]
    return {"kind": pts[0]["kind"] if pts else None, "point": pts[0]["point"] if pts else None,
            "points": json.dumps(pts)}


def deep_posts() -> pd.DataFrame:
    """The posts fetch.py deep pulled commenter histories for."""
    c = S.read("hn_comments")
    p = S.read("hn_posts").drop_duplicates("post_id")
    return p[p.post_id.isin(c.loc[c.role == "history", "post_id"])]


def label() -> None:
    posts = {r["post_id"]: r for r in deep_posts().to_dict("records")}
    c = S.read("hn_comments")
    th = c[(c.role == "thread") & ~c.is_maker & c.post_id.isin(posts)].drop_duplicates("comment_id")
    have = S.read("judge_labels")
    if len(have):
        th = th[~th.comment_id.isin(have.loc[have.source == "real", "comment_id"])]
    rows = th.to_dict("records")
    with ThreadPoolExecutor(32) as ex:
        labs = list(ex.map(lambda r: label_one(posts[r["post_id"]], r["text"]), rows))
    out = pd.DataFrame([{"source": "real", "post_id": r["post_id"], "comment_id": r["comment_id"], "author": r["author"],
                         "judge": llm.FLASH, "prompt": "label_v1", **lab, "labelled_on": S.now()}
                        for r, lab in zip(rows, labs)])
    S.write("judge_labels", out)
    usd = llm.flush_spend("hn_judge_label", f"{len(rows)} real top-level comments labelled")
    print(f"labelled {len(out)}  ${usd:.3f}")
    print(out.kind.value_counts(normalize=True).round(3).to_dict())


if __name__ == "__main__":
    if sys.argv[1] == "label":
        label()
