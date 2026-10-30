"""Michael Taylor's HN persona experiment (every.to, "I cloned 2,000 Hacker News users to predict viral posts"),
rebuilt so it can be compared and combined with the scoreboard models.

His setup: personas from real HN commenters' comments; each persona decides which headlines it would upvote; one
day (Mar 12, 2025), 1,147 headlines, 50/50 front page vs not; 60% accuracy (coin flip 50%). No code was published.

Here:
  personas  the N most active commenters before the test day; card from their last 50 comments (Flash-Lite), as in
            arms.CARD; nothing dated on or after the test day
  ballot    the test day's headlines (title + site), balanced: the day's top 100 by final points (front-page proxy)
            and an equal number of random others; shuffled per persona, in chunks of CHUNK; each persona returns the
            headlines it would upvote
  score     votes per headline -> predicted front page = top half; accuracy on the balanced set (his metric), plus
            AUC; compared with the scoreboard's post-only model score on the same headlines when available

    python persona_vote.py <day> [n_personas=200] [chunk=100]
"""
from __future__ import annotations

import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import numpy as np
import pandas as pd

import llm
import store as S
import top100 as H

CARD = """Here are recent Hacker News comments by one person (newest first), each with the story it was on.
{comments}

Write a persona of this person as a Hacker News reader, in the second person, 120 words max: what they work on, what
topics and kinds of stories they care about, what they find boring or annoying, and what makes them upvote."""

VOTE = """{persona}

You are browsing the Hacker News "new" page. Here are submissions (title and site). Which would you upvote? Be as
selective as you really are: most people upvote only a few stories a day.

{items}

Return {{"upvote": [<numbers of the stories you would upvote>]}}"""


def personas(day: str, n: int) -> list[dict]:
    c = H.comments()
    t = int(pd.Timestamp(day, tz="UTC").timestamp())
    c = c[(c.created_at_i < t) & (c.created_at_i >= t - 180 * 86400)]
    top = c.person.value_counts().head(n).index
    p = H.stories().set_index("post_id").title
    out = []
    for u in top:
        h = c[c.person == u].sort_values("created_at_i", ascending=False).head(50)
        out.append({"person": u, "comments": [(p.get(s, ""), cid) for s, cid in zip(h.story_id, h.comment_id)]})
    return out


def card(u: dict, texts: dict) -> str:
    lines = "\n".join(f"- on \"{title}\": {texts.get(cid, '')[:300]}" for title, cid in u["comments"] if texts.get(cid))
    j = llm.call("taylor_card", CARD.format(comments=lines or "(no text)"), model=llm.LITE)
    return str(j.get("persona") or j.get("text") or next((v for v in j.values() if isinstance(v, str)), ""))


def comment_texts(ids: list[int]) -> dict:
    """Comment text from BigQuery (the cache has ids only)."""
    from auth import vertex_credentials
    from google.cloud import bigquery
    c = bigquery.Client(project="project-amer-scs-sandbox", credentials=vertex_credentials())
    job = c.query("SELECT id, text FROM `bigquery-public-data.hacker_news.full` WHERE id IN UNNEST(@ids)",
                  job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("ids", "INT64", ids)]))
    df = job.result().to_dataframe()
    gb = (job.total_bytes_billed or 0) / 1e9
    S.spend("hn_bigquery_taylor", gb / 1000 * 6.25, f"{gb:.1f} GB comment texts for persona cards")
    import html as _h
    import re
    return {int(i): _h.unescape(re.sub(r"<[^>]+>", " ", t or "")) for i, t in zip(df.id, df.text)}


def ballot(day: str, seed: int = 0) -> pd.DataFrame:
    p = H.stories()
    d = p[p.day == day].copy()
    d["rk"] = d.points.rank(ascending=False, method="first")
    pos = d[d.rk <= 100]                       # stories that reach the front page in a day: roughly the top 100
    neg = d[d.rk > 30].sample(len(pos), random_state=seed)
    b = pd.concat([pos.assign(front=1), neg.assign(front=0)])
    b["site"] = b.url.fillna("").map(lambda u: urlparse(u).netloc.removeprefix("www.") or "news.ycombinator.com")
    return b[["post_id", "title", "site", "front", "points"]].reset_index(drop=True)


def vote(persona: str, b: pd.DataFrame, seed: int, chunk: int) -> list[int]:
    idx = list(range(len(b)))
    random.Random(seed).shuffle(idx)
    got = []
    for i in range(0, len(idx), chunk):
        part = idx[i:i + chunk]
        items = "\n".join(f"{k + 1}. {b.title[j]} ({b.site[j]})" for k, j in enumerate(part))
        j = llm.call("taylor_vote", VOTE.format(persona=persona, items=items), model=llm.LITE, temperature=0.7, seed=seed)
        for v in j.get("upvote") or []:
            try:
                if 1 <= int(v) <= len(part):
                    got.append(int(b.post_id[part[int(v) - 1]]))
            except (TypeError, ValueError):
                continue
    return got


def main(day: str, n: int = 200, chunk: int = 100) -> None:
    b = ballot(day)
    ps = personas(day, n)
    texts = comment_texts([cid for u in ps for _, cid in u["comments"]])
    with ThreadPoolExecutor(32) as ex:
        cards = list(ex.map(lambda u: card(u, texts), ps))
    with ThreadPoolExecutor(32) as ex:
        votes = list(ex.map(lambda k: vote(cards[k], b, k, chunk), range(len(ps))))
    tally = pd.Series([x for v in votes for x in v]).value_counts()
    b["votes"] = b.post_id.map(tally).fillna(0)
    b["pred_front"] = (b.votes.rank(method="first", ascending=False) <= len(b) / 2).astype(int)
    acc = float((b.pred_front == b.front).mean())
    from sklearn.metrics import roc_auc_score
    auc = float(roc_auc_score(b.front, b.votes))
    usd = llm.flush_spend("hn_taylor_personas", f"{day}: {len(ps)} personas x {len(b)} headlines")
    out = {"day": day, "personas": len(ps), "headlines": len(b), "accuracy": round(acc, 3), "auc": round(auc, 3),
           "votes_per_persona": round(float(np.mean([len(v) for v in votes])), 1), "usd": round(usd, 3)}
    print(json.dumps(out))
    b.to_parquet(os.path.join(S.LOCAL, f"taylor_{day}_{len(ps)}.parquet"), index=False)
    S.write("hn_scores", pd.DataFrame([{**out, "kind": "taylor_personas", "made_on": S.now()}]))


if __name__ == "__main__":
    main(sys.argv[1], *[int(x) for x in sys.argv[2:]])
