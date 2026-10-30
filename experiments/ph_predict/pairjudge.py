"""Teach Gemini what wins: same-day launch pairs with matched reach (reach-only predictions within 0.15 log votes).
Gemini sees each pair's launch pages (name, tagline, topics, media, video, description, maker's first comment) and
says which got more votes. Zero-shot vs taught with K real example pairs from EARLIER months (winner marked).
Tested on pairs from the last two months only. 50% = coin flip.
usage: python pairjudge.py [n_test] [k_examples] -> results/pairjudge.json"""
import json, os, random, re, sys, glob, gzip, html
import numpy as np, pandas as pd
import llm
from page_score import first_comments, launches

PROMPT = """Two Product Hunt launches on the same day, from teams with about the same reach. Judge only the launch pages:
which one got more upvotes?
{examples}
Now this pair:
Launch A
{a}

Launch B
{b}

Reply with JSON only: {{"winner": "A" or "B", "reason": "<the page difference that decides it, one sentence>"}}"""


def page(p, first):
    media = p.get("media") or []
    return (f"Name: {p['name']}\nTagline: {p.get('tagline') or ''}\nTopics: {', '.join(e['node']['name'] for e in p['topics']['edges'])}\n"
            f"Media: {len(media)} items, video: {'yes' if any(m.get('type') == 'video' for m in media) else 'no'}\n"
            f"Description: {(p.get('description') or '')[:500]}\nMaker's first comment: {(first.get(p['slug']) or 'none')[:500]}")


def pairs(P, days):
    out = []
    for d, g in P[P.day.isin(days)].groupby("day"):
        g = g.to_dict("records")
        out += [(a, b) for i, a in enumerate(g) for b in g[i + 1:] if abs(a["fixed"] - b["fixed"]) < 0.15 and a["logv"] != b["logv"]]
    return out


def main(n_test, k):
    P = pd.read_parquet("results/ctrl_preds.parquet")
    rows = launches()
    teams = {p["slug"]: {m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")} for p in rows.values()}
    first = first_comments(teams)
    days = sorted(P.day.unique()); test_days = [d for d in days if d >= "2026-09-01"]; train_days = [d for d in days if d < "2026-09-01"]
    rng = random.Random(0)
    test = rng.sample(pairs(P, test_days), n_test); train = pairs(P, train_days)
    res = {}
    for mode in ("zero_shot", f"taught_{k}"):
        hits = []
        for a, b in test:
            ex = ""
            if mode != "zero_shot":
                for c, e in enumerate(rng.sample(train, k)):
                    x, y = (e[0], e[1]) if rng.random() < 0.5 else (e[1], e[0])
                    ex += f"\nExample {c + 1}\nLaunch A\n{page(rows[x['id']], first)}\n\nLaunch B\n{page(rows[y['id']], first)}\nWinner: {'A' if x['logv'] > y['logv'] else 'B'}\n"
            x, y = (a, b) if rng.random() < 0.5 else (b, a)
            txt = llm.call(PROMPT.format(examples=ex or "", a=page(rows[x["id"]], first), b=page(rows[y["id"]], first)), max_tokens=200)
            try:
                v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
            except Exception:  # noqa: BLE001
                continue
            hits.append((v.get("winner") == "A") == (x["logv"] > y["logv"]))
        h = np.array(hits, float); bs = [np.random.default_rng(1).choice(h, len(h)).mean() for _ in range(1)]
        r2 = np.random.default_rng(0); bs = [r2.choice(h, len(h)).mean() for _ in range(2000)]
        res[mode] = {"right": round(100 * h.mean(), 1), "ci95": [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)], "n": len(h)}
        print(mode, res[mode], llm.USAGE, flush=True)
    res["usd"] = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 3)
    json.dump(res, open("results/pairjudge.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300, int(sys.argv[2]) if len(sys.argv) > 2 else 8)
