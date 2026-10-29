"""Plan A vs plan B, tested on products that launched twice from the same website (same team and network, different
page, day and effort). For each pair of consecutive launches: did the later one do better than the earlier one
(within-day rank percentile)? Predicted by:
  changeable   the out-of-sample lift from page + day + effort inputs (ctrl.py), later minus earlier
  page_only    the lift from page inputs alone
  fixed        the fixed-inputs prediction change (reach and network grow between launches): the baseline to beat
  gemini       Gemini shown both launch pages side by side (dates and results hidden), asked which will do better
Score: share of pairs where the predicted direction is right (50% = coin flip), with a 95% interval.
usage: python relaunch.py -> results/relaunch.json"""
import json, os, pickle, random, re
import numpy as np, pandas as pd
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SKIP = {"", "github.com", "apps.apple.com", "chromewebstore.google.com", "chrome.google.com", "play.google.com", "producthunt.com",
        "x.com", "notion.site", "vercel.app"}
PROMPT = """Two Product Hunt launches of the same product, by the same team, in random order. Judge only the launch pages:
which will finish higher on its day's leaderboard?

Launch A
{a}

Launch B
{b}

Reply with JSON only: {{"better": "A" or "B", "why": "<one sentence on the page difference that decides it>"}}"""


def page(r):
    return (f"Name: {r['name']}\nTagline: {r['tagline']}\nTopics: {', '.join(r['topics'])}\nMedia items: {int(r['ph_n_media'] or 0)}, video: "
            f"{'yes' if r['ph_has_video'] == 1 else 'no'}\nDescription: {(r['description'] or '')[:700]}")


def interval(hits):
    hits = np.array(hits, float); rng = np.random.default_rng(0)
    bs = [rng.choice(hits, len(hits)).mean() for _ in range(2000)]
    return round(100 * hits.mean(), 1), [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]


def main():
    df = pickle.load(open(f"{D}/build_cache.pkl", "rb"))
    P = pd.read_parquet("results/ctrl_preds.parquet")
    df = df.merge(P[["id", "fixed", "fixed+page", "fixed+day", "fixed+effort", "all"]], on="id")
    df = df[df.dailyRank.notna()].copy()
    df["pct"] = df.groupby("day").dailyRank.rank(pct=True, ascending=False)      # 1 = top of the day
    df["prod"] = df.domain.fillna("").str.lower().str.replace(r"^www\.", "", regex=True)
    df = df[~df["prod"].isin(SKIP)]
    pairs = []
    for _, g in df.sort_values("day").groupby("prod"):
        rows = g.to_dict("records")
        pairs += [(a, b) for a, b in zip(rows, rows[1:]) if a["day"] != b["day"]]
    res = {"pairs": len(pairs)}
    real = [b["pct"] > a["pct"] for a, b in pairs]
    pick = lambda f: [(f(b) - f(a) > 0) == r for (a, b), r in zip(pairs, real)]
    res["changeable"] = interval(pick(lambda r: r["all"] - r["fixed"]))
    res["page_only"] = interval(pick(lambda r: r["fixed+page"] - r["fixed"]))
    res["day_only"] = interval(pick(lambda r: r["fixed+day"] - r["fixed"]))
    res["effort_only"] = interval(pick(lambda r: r["fixed+effort"] - r["fixed"]))
    res["fixed"] = interval(pick(lambda r: r["fixed"]))
    res["full_model"] = interval(pick(lambda r: r["all"]))
    rnd = random.Random(0); hits = []; why = []
    for (a, b), r in zip(pairs, real):
        flip = rnd.random() < 0.5
        x, y = (b, a) if flip else (a, b)
        txt = llm.call(PROMPT.format(a=page(x), b=page(y)), max_tokens=200)
        try:
            v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        except Exception:  # noqa: BLE001
            continue
        later_better_pred = (v.get("better") == "A") == flip      # A shown = later launch when flipped
        hits.append(later_better_pred == r); why.append(v.get("why"))
    res["gemini"] = interval(hits); res["gemini_n"] = len(hits)
    res["later_did_better_share"] = round(100 * np.mean(real), 1)
    json.dump(res, open("results/relaunch.json", "w"), indent=1)
    print(json.dumps(res, indent=1)); print("gemini usage", llm.USAGE)


if __name__ == "__main__":
    main()
