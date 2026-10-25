"""Descriptive factor table: for each feature, the daily top-5 rate in its top vs bottom third (or yes vs no),
overall and per product type. Uses all collected launches; descriptive, not a backtest."""
import numpy as np, pandas as pd
import features as F, run as RN

FEATS = {
    "ph_hunter_followers": "Hunter's PH followers", "hist_hunter_top5": "Hunter's past top-5 rate",
    "hist_maker_top5": "Makers' past top-5 rate", "ph_self_hunted": "Self-hunted (maker posted it)",
    "ph_n_makers": "Number of makers", "ph_maker_min_age_d": "Newest maker account age",
    "ph_hunter_age_d": "Hunter account age", "ph_n_media": "Gallery items", "ph_has_video": "Has a video",
    "ph_desc_len": "Description length", "ph_tagline_len": "Tagline length", "ph_weekday": "Weekend launch",
    "x_hunter_followers": "Hunter's X followers", "x_maker_max_followers": "Top maker's X followers",
    "x_company_followers": "Company X followers", "x_any_verified": "Any verified X account",
    "dom_age_d": "Domain age", "dom_tld_ai": ".ai domain", "dom_has_site": "Own website found",
    "dom_wb_has_before": "Site archived before launch", "web_text_words": "Homepage word count",
    "web_has_pricing": "Homepage shows pricing", "web_has_testimonials": "Homepage has social proof",
    "web_has_waitlist": "Waitlist only", "web_has_github": "Links to GitHub", "web_has_appstore": "App Store link",
    "hn_n": "On Hacker News before launch", "llm_brand": "LLM: known brand", "llm_pitch": "LLM pitch score",
}


def lift(df, f):
    x = df[f]
    if f == "ph_weekday":
        x = (x >= 5).astype(float)
    x = x.dropna()
    if x.nunique() < 2 or len(x) < 60:
        return np.nan, np.nan, len(x)
    y = df.loc[x.index, "top5"]
    if x.nunique() == 2:
        hi, lo = y[x == x.max()].mean(), y[x == x.min()].mean()
    else:
        q1, q2 = x.quantile([1 / 3, 2 / 3])
        hi, lo = y[x > q2].mean(), y[x <= q1].mean()
    return hi, lo, len(x)


if __name__ == "__main__":
    df = RN.load_llm(F.build())
    df["llm_brand"] = df.get("llm_brand")
    df["top5"] = (df.dailyRank <= 5).astype(float)
    df["ptype"] = df.topics.apply(RN.ptype)
    rows = []
    for f, name in FEATS.items():
        if f not in df:
            continue
        r = {"factor": name, "feature": f}
        hi, lo, n = lift(df, f)
        r.update(all_hi=hi, all_lo=lo, all_n=n)
        for t, g in df.groupby("ptype"):
            hi, lo, n = lift(g, f)
            r[f"{t}"] = hi / lo if lo and lo > 0 else np.nan
        rows.append(r)
    out = pd.DataFrame(rows)
    out["ratio"] = out.all_hi / out.all_lo
    out.sort_values("ratio", ascending=False).to_csv(F.D + "/../results/factors.csv", index=False)
    print(out.sort_values("ratio", ascending=False).round(2).to_string())
