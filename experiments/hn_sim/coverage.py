"""Coverage report for the Show HN window: posts per day, product type, comments, snapshots, history size, and the
model's 'known' check on the deep posts. Product type: Gemini Flash-Lite reads title, URL and post text.

    python coverage.py
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import arms as A
import llm
import store as S
from judge import deep_posts

TYPE = """A Show HN post. Title: {title}
URL: {url}
Text: {text}
What does the URL link to? One of:
- web_app: a product or tool you can use in a web browser right away (app, game, interactive site, web service with signup)
- download: a desktop/mobile app, browser extension or hardware you must install or buy
- code: a repository, library, CLI, framework or model weights
- content: a blog post, article, paper, video, or a static page about something
- other
Return {{"type": "..."}}"""


def main():
    p = S.read("hn_posts").drop_duplicates("post_id")
    with ThreadPoolExecutor(32) as ex:
        ty = list(ex.map(lambda r: llm.call("post_type", TYPE.format(title=r["title"], url=r["url"],
                                                                     text=(r["text"] or "")[:600]),
                                            model=llm.LITE).get("type"), p.to_dict("records")))
    p = p.assign(ptype=ty)
    c = S.read("hn_comments")
    tl = c[(c.role == "thread") & ~c.is_maker].groupby("post_id").author.nunique()
    p = p.assign(top_level=p.post_id.map(tl).fillna(0).astype(int))
    S.write("hn_posts", p.assign(observed_on=S.now())[["post_id", "ptype", "top_level", "observed_on"]]
            .assign(kind="coverage_v1"))
    dp = deep_posts()
    with ThreadPoolExecutor(16) as ex:
        kn = dict(zip(dp.post_id, ex.map(lambda r: A.known(r), dp.to_dict("records"))))
    ppl = S.read("hn_people")
    hc = ppl[ppl.get("kind") == "history_count"].drop_duplicates(["post_id", "person"])
    usd = llm.flush_spend("hn_coverage", f"{len(p)} posts typed, {len(dp)} known checks")
    out = {
        "window": f"{p.day.min()}..{p.day.max()}", "posts": len(p), "posts_per_day_mean": round(len(p) / p.day.nunique(), 1),
        "posts_per_day_min_max": [int(p.groupby('day').size().min()), int(p.groupby('day').size().max())],
        "type_share": p.ptype.value_counts(normalize=True).round(3).to_dict(),
        "share_10plus_toplevel": round((p.top_level >= 10).mean(), 4),
        "n_10plus_toplevel": int((p.top_level >= 10).sum()),
        "n_web_app_and_10plus": int(((p.top_level >= 10) & (p.ptype == "web_app")).sum()),
        "deep_posts": len(dp), "deep_types": dp.post_id.map(dict(zip(p.post_id, p.ptype))).value_counts().to_dict(),
        "deep_known_by_model": int(sum(kn.values())),
        "commenters": len(hc), "share_20plus_earlier": round((hc.earlier_comments >= 20).mean(), 3),
        "share_50plus_earlier": round((hc.earlier_comments >= 50).mean(), 3),
        "median_earlier": float(hc.earlier_comments.median()),
        "posts_with_5plus_eligible_twins": int((hc[hc.earlier_comments >= 20].groupby("post_id").size() >= 5).sum()),
        "usd": round(usd, 4),
    }
    print(json.dumps(out, indent=1))
    print("known:", [i for i, k in kn.items() if k])
    return out


if __name__ == "__main__":
    main()
