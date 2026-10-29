"""Gemini reads each story's title and domain and estimates how likely it is to reach the HN front page top 10 that
day. 40 stories per call, in random order (not by time or score). Stored as hn_scores kind=llm_title.

    python llm_title.py 2026-10-01 2026-10-27 [flash|lite]
"""
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import pandas as pd

import llm
import store as S
import top10 as T

PROMPT = """You know Hacker News well. Below are stories just submitted to Hacker News. For each, estimate the chance
(0-100) that it reaches the top 10 of the Hacker News front page at some point. Most submissions get almost no
votes: on a typical day about 30 of ~1,000 reach the top 10. Judge only from the title and the site.

{items}

Return {{"scores": {{"<id>": <0-100>, ...}}}} with every id."""


def main(a, b, model="flash"):
    p = T.stories()
    p = p[(p.day >= a) & (p.day < b)]
    rows = p[["post_id", "title", "url"]].to_dict("records")
    random.Random(0).shuffle(rows)
    batches = [rows[i:i + 40] for i in range(0, len(rows), 40)]
    M = llm.FLASH if model == "flash" else llm.LITE

    def one(bt):
        items = "\n".join(f"{r['post_id']}: {r['title']} ({urlparse(r['url'] if isinstance(r['url'], str) else '').netloc.removeprefix('www.') or 'text post'})"
                          for r in bt)
        j = llm.call("llm_title", PROMPT.format(items=items), model=M, max_tokens=4096)
        sc = j.get("scores") or {}
        return [(r["post_id"], sc.get(str(r["post_id"]))) for r in bt]
    with ThreadPoolExecutor(32) as ex:
        got = [x for xs in ex.map(one, batches) for x in xs]
    D = pd.DataFrame(got, columns=["post_id", "score"])
    D["score"] = pd.to_numeric(D.score, errors="coerce")
    S.write("hn_scores", D.assign(kind="llm_title", model=M, made_on=S.now()))
    usd = llm.flush_spend("hn_llm_title", f"{len(rows)} titles {a}..{b} ({M})")
    print(f"{len(D)} titles, {D.score.isna().mean():.1%} missing, ${usd:.3f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
