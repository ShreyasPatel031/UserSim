"""promo_: pre-launch promotion per launch from data/promo_search.jsonl (Gemini + Google Search).
Only posts/coverage dated before launch day count. Then a residual test like signal_test.py: does each feature explain
what the current model gets wrong (within-day Spearman with real-minus-predicted percentile, bootstrap 95% CI)?
Output: data/promo_features.json, results/promo_signal.csv"""
import json, os, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def num(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, dict):
        v = [num(y) for y in x.values()]
        v = [y for y in v if y is not None]
        return sum(v) if v else None
    m = re.search(r"([\d.,]+)\s*([kKmM]?)", str(x or ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)


def money(s):
    m = re.search(r"\$\s*([\d.,]+)\s*(million|m|billion|b|k|thousand)?", str(s or ""), re.I)
    if not m:
        return 0.0
    v = float(m.group(1).replace(",", "") or 0)
    u = (m.group(2) or "").lower()
    return v * (1e6 if u in ("million", "m") else 1e9 if u in ("billion", "b") else 1e3 if u in ("k", "thousand") else 1)


def feats(r):
    d, res = r["day"], r.get("result") or {}
    posts = [p for p in res.get("posts") or [] if isinstance(p, dict) and (p.get("date") or "9") < d]
    cov = [c for c in res.get("coverage") or [] if isinstance(c, dict) and (c.get("date") or "9") < d]
    plat = lambda k: sum(1 for p in posts if (p.get("platform") or "").lower() == k)
    f = {"promo_posts": len(posts), "promo_posts_launch": sum(bool(p.get("about_launch")) for p in posts),
         "promo_posts_li": plat("linkedin"), "promo_posts_x": plat("x"),
         "promo_posts_founder": sum((p.get("author_role") or "") == "founder" for p in posts),
         "promo_reactions": float(np.log1p(sum(num(p.get("reactions")) or 0 for p in posts))),
         "promo_cov": len(cov), "promo_cov_press": sum(c.get("type") == "press" for c in cov),
         "promo_cov_hn": sum(c.get("type") == "hackernews" for c in cov),
         "promo_cov_reddit": sum(c.get("type") == "reddit" for c in cov),
         "promo_n_sources": len(r.get("sources") or []),
         "promo_founder_li": float(np.log1p(num(res.get("founder_linkedin_followers")) or 0)),
         "promo_company_li": float(np.log1p(num(res.get("company_linkedin_followers")) or 0)),
         "promo_founder_x": float(np.log1p(num(res.get("founder_x_followers")) or 0)),
         "promo_funding": float(np.log1p(money(res.get("funding")))),  # may include rounds announced after launch
         "promo_company_age": (int(d[:4]) - int(str(res.get("company_founded"))[:4]))
         if re.match(r"^\d{4}", str(res.get("company_founded") or "")) else np.nan}
    return f


def main():
    rows = {}
    for l in open(f"{D}/promo_search.jsonl"):
        r = json.loads(l)
        rows[r["id"]] = feats(r)
    json.dump(rows, open(f"{D}/promo_features.json", "w"))
    if "--test" not in sys.argv:     # the daily forecast only needs the features
        return
    P = pd.read_csv(f"{R}/predictions.csv", usecols=["id", "day", "dailyRank", "pred"]); P["id"] = P.id.astype(str)
    F = pd.DataFrame.from_dict(rows, orient="index"); F.index.name = "id"
    P = P.merge(F.reset_index(), on="id", how="inner")
    P["res"] = P.groupby("day").dailyRank.rank(pct=True, ascending=False) - P.groupby("day").pred.rank(pct=True)
    out = []
    for c in F.columns:
        rs = np.array([spearmanr(g[c], g.res)[0] for _, g in P.groupby("day") if g[c].nunique() > 1 and len(g) > 5])
        rs = rs[~np.isnan(rs)]
        if len(rs) < 10:
            continue
        b = np.random.default_rng(0).choice(rs, (2000, len(rs))).mean(1)
        lo, hi = np.percentile(b, [2.5, 97.5])
        out.append({"feature": c, "rho_vs_error": round(rs.mean(), 3), "ci": f"{lo:.3f}–{hi:.3f}",
                    "significant": bool(lo > 0 or hi < 0), "days": len(rs), "nonzero_share": round(float((P[c].fillna(0) != 0).mean()), 2)})
    out = pd.DataFrame(out).sort_values("rho_vs_error", key=abs, ascending=False)
    out.to_csv(f"{R}/promo_signal.csv", index=False)
    print(len(P), "launches"); print(out.to_string(index=False))


if __name__ == "__main__":
    main()
