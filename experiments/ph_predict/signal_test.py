"""Which new sources carry signal beyond the current model? September–October launches.

Per feature:
  lift   daily top-5 rate when the feature is high (top third, or present) vs low (bottom third, or absent)
  rho    within-day rank correlation with the real result
  resid  within-day rank correlation with what the current model got wrong (real minus predicted percentile):
         the ADDED signal; a feature the model already captures scores about 0 here
Each feature is tagged:
  pre    known before launch day (usable for a forecast)
  post   from launch day itself (who showed up and commented): an upper bound on what knowing the audience is worth
Output: results/signal.csv, printed table sorted by |resid|."""
import gzip, json, os, re
from collections import Counter, defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
import commenters as K

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LAUNCH_WORDS = re.compile(r"(?i)product ?hunt|producthunt|\blaunch(ing|ed)?\b|we'?re live|upvote|support us|go live")


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    out = []
    if not os.path.exists(path):
        return out
    with op(path, "rt") as f:
        for l in f:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:  # noqa: BLE001
        return np.nan


def li_parse(html):
    m = re.search(r"([\d,]+) followers", html)
    e = re.search(r'"numberOfEmployees":\{"value":(\d+)', html)
    f = re.search(r"Founded.{0,300}?<dd[^>]*>\s*(\d{4})", html, re.S)
    return {"followers": num(m.group(1)) if m else np.nan, "employees": num(e.group(1)) if e else np.nan,
            "founded": num(f.group(1)) if f else np.nan}


def features():
    pred = pd.read_csv(f"{R}/predictions.csv", usecols=["id", "day", "dailyRank", "pred"])
    pred["id"] = pred.id.astype(str)
    H = {x["id"]: x for x in json.load(open(f"{D}/sepoct_handles.json"))}
    df = pred[pred.id.isin(H)].copy().reset_index(drop=True)
    df["slug"] = df.id.map(lambda i: H[i]["slug"])
    feats = defaultdict(dict)
    tags = {}

    def put(i, name, val, tag):
        feats[i][name] = val
        tags[name] = tag

    # --- commenters and their segments
    prof = {p["username"]: p for p in jl(f"{D}/ph_profiles.jsonl.gz")}
    seg = {s["username"]: (s["labels"] or {}) for s in jl(f"{D}/segments.jsonl")}
    PX = {x["handle"].lower(): (x.get("profile") or {}) for x in jl(f"{D}/commenter_x.jsonl.gz")}  # commenters' own X
    cm = K.load_comments()
    team = {}  # makers + hunter: their own (often scheduled, pre-launch) comments are not audience
    import glob
    for f in glob.glob(f"{D}/days/2026-09-*.json") + glob.glob(f"{D}/days/2026-10-*.json"):
        for p in json.load(open(f)):
            team[p["id"]] = {m["username"] for m in p.get("makers") or []} | {(p.get("user") or {}).get("username")}
    for _, r in df.iterrows():
        rows = [c for c in (cm.get(r.slug) or {}).get("rows", [])
                if c["username"] and c["username"] in prof and c["username"] not in team.get(r.id, set())]
        pre = [c for c in rows if (c["created"] or "")[:10] < r.day]
        for tag, sub in (("post", rows), ("pre", pre)):
            users = list(dict.fromkeys(c["username"] for c in sub))
            p = f"seg_{tag}_"
            put(r.id, p + "n_people", len(users), tag)
            if not users:
                continue
            labs = [seg.get(u, {}) for u in users]
            for field, vals in (("role", ["founder_exec", "engineer", "marketing_growth", "product", "designer", "investor", "data_ml"]),
                                ("company_type", ["own_startup", "startup_employee", "big_tech", "enterprise", "freelancer"]),
                                ("domain", ["ai_ml", "developer_tools", "saas_b2b", "marketing", "design"])):
                c = Counter(l.get(field) for l in labs)
                for v in vals:
                    put(r.id, f"{p}{field}_{v}_n", c[v], tag)
                    put(r.id, f"{p}{field}_{v}_share", c[v] / len(users), tag)
            put(r.id, p + "builder_share", np.mean([bool(l.get("builder")) for l in labs]), tag)
            put(r.id, p + "senior_share", np.mean([l.get("seniority") in ("founder_c_level", "senior_lead") for l in labs]), tag)
            ps = [prof[u] for u in users]
            put(r.id, p + "followers_sum_log", np.log1p(sum(num(x.get("followers")) or 0 for x in ps)), tag)
            put(r.id, p + "followers_max_log", np.log1p(max(num(x.get("followers")) or 0 for x in ps)), tag)
            put(r.id, p + "votes_median_log", np.log1p(np.nanmedian([num(x.get("votes")) for x in ps])), tag)
            put(r.id, p + "maker_share", np.mean([bool(x.get("is_maker")) for x in ps]), tag)
            put(r.id, p + "has_linkedin_share", np.mean([any(l["kind"] == "linkedin" for l in x["links"]) for x in ps]), tag)
            put(r.id, p + "has_x_share", np.mean([bool(x.get("twitter")) for x in ps]), tag)
            xf = [num((PX.get((x.get("twitter") or "").lower().lstrip("@")) or {}).get("followers")) for x in ps]
            put(r.id, p + "x_followers_sum_log", np.log1p(np.nansum(xf)) if np.isfinite(xf).any() else 0.0, tag)
            put(r.id, p + "x_followers_max_log", np.log1p(np.nanmax(xf)) if np.isfinite(xf).any() else 0.0, tag)
            yrs = [2026 - int(str(x.get("created") or "2026")[:4]) for x in ps]
            put(r.id, p + "account_age_median", float(np.median(yrs)), tag)
    # --- X: makers' and company posts in the 14 days before launch (counts are clean; engagement totals are today's)
    X = {x["handle"].lower(): x for x in jl(f"{D}/x_posts.jsonl.gz")}
    for _, r in df.iterrows():
        h = H[r.id]
        lo = (pd.Timestamp(r.day) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        for who, handles in (("maker", h["makers_x"]), ("company", [h["company_x"]] if h["company_x"] else [])):
            posts = [p for hd in handles for p in (X.get(hd.lower().lstrip("@"), {}) or {}).get("posts", [])
                     if lo <= p["created_at"] < r.day]
            ann = [p for p in posts if LAUNCH_WORDS.search(p.get("text") or "")]
            put(r.id, f"x_{who}_posts_14d", len(posts), "pre")
            put(r.id, f"x_{who}_launch_posts_14d", len(ann), "pre")
            put(r.id, f"x_{who}_launch_views_log", np.log1p(sum((p.get("views") or 0) for p in ann)), "pre")
            put(r.id, f"x_{who}_views_14d_log", np.log1p(sum((p.get("views") or 0) for p in posts)), "pre")
            prof_x = [(X.get(hd.lower().lstrip("@"), {}) or {}).get("profile") or {} for hd in handles]
            put(r.id, f"x_{who}_followers_log", np.log1p(sum(num(p.get("followers")) or 0 for p in prof_x)), "pre")
    # --- LinkedIn company pages (launch and competitors)
    LI = {}
    for r in jl(f"{D}/li_pages.jsonl.gz"):
        if r.get("status") == 200:
            LI[r["url"].rstrip("/").rsplit("/", 1)[-1].lower()] = li_parse(r["html"])
    C = json.load(open(f"{D}/competitors.json")) if os.path.exists(f"{D}/competitors.json") else {}
    CX = {x["handle"].lower(): (x.get("profile") or {}) for x in jl(f"{D}/competitor_x.jsonl.gz")}
    for _, r in df.iterrows():
        h = H[r.id]
        own = LI.get((h["linkedin"] or "").strip("/").split("/")[0].lower(), {})
        put(r.id, "li_followers_log", np.log1p(own.get("followers", np.nan)), "pre")
        put(r.id, "li_employees_log", np.log1p(own.get("employees", np.nan)), "pre")
        put(r.id, "li_company_age", 2026 - own.get("founded", np.nan), "pre")
        comps = C.get(r.id, [])
        cli = [LI.get((c.get("linkedin") or "").lower(), {}).get("followers", np.nan) for c in comps]
        cxf = [num(CX.get((c.get("x") or "").lower().lstrip("@"), {}).get("followers")) for c in comps]
        put(r.id, "comp_li_followers_max_log", np.log1p(np.nanmax(cli)) if np.isfinite(cli).any() else np.nan, "pre")
        put(r.id, "comp_x_followers_max_log", np.log1p(np.nanmax(cxf)) if np.isfinite(cxf).any() else np.nan, "pre")
        put(r.id, "comp_x_followers_sum_log", np.log1p(np.nansum(cxf)) if np.isfinite(cxf).any() else np.nan, "pre")
    F = pd.DataFrame.from_dict(feats, orient="index")
    df = df.join(F, on="id")
    return df, tags


def score(df, tags):
    df = df.copy()
    df["top5"] = (df.dailyRank <= 5).astype(float)
    df["real_pct"] = df.groupby("day").dailyRank.rank(pct=True, ascending=False)
    df["pred_pct"] = df.groupby("day").pred.rank(pct=True)
    df["resid"] = df.real_pct - df.pred_pct
    out = []
    for f, tag in tags.items():
        x = df[f]
        ok = x.notna()
        if ok.sum() < 80 or x[ok].nunique() < 2:
            continue
        sub = df[ok]
        if x[ok].nunique() <= 3 or (x[ok] > 0).mean() < 0.4:
            hi, lo = sub.top5[sub[f] > 0].mean(), sub.top5[sub[f] <= 0].mean()
        else:
            q1, q2 = sub[f].quantile([1 / 3, 2 / 3])
            hi, lo = sub.top5[sub[f] > q2].mean(), sub.top5[sub[f] <= q1].mean()
        rho = np.nanmean([spearmanr(g[f], g.real_pct)[0] for _, g in sub.groupby("day") if len(g) > 5 and g[f].nunique() > 1])
        rs = np.array([spearmanr(g[f], g.resid)[0] for _, g in sub.groupby("day") if len(g) > 5 and g[f].nunique() > 1])
        rs = rs[np.isfinite(rs)]
        res = rs.mean() if len(rs) else np.nan
        b = np.random.default_rng(0).choice(rs, (2000, len(rs))).mean(1) if len(rs) > 1 else np.array([np.nan])
        ci = (np.percentile(b, 2.5), np.percentile(b, 97.5))
        out.append({"feature": f, "when": tag, "coverage": round(ok.mean(), 2), "top5_high": round(hi, 3),
                    "top5_low": round(lo, 3), "rho": round(rho, 3), "resid": round(res, 3),
                    "resid_lo": round(ci[0], 3), "resid_hi": round(ci[1], 3), "days": len(rs),
                    "significant": bool(len(rs) >= 15 and (ci[0] > 0 or ci[1] < 0))})
    return pd.DataFrame(out).sort_values("resid", key=lambda s: -s.abs())


if __name__ == "__main__":
    df, tags = features()
    s = score(df, tags)
    s.to_csv(f"{R}/signal.csv", index=False)
    df.to_csv(f"{D}/signal_features.csv", index=False)
    pd.set_option("display.width", 200)
    print("significant (95% interval excludes 0, >=15 days):")
    print(s[s.significant].to_string(index=False))
    print("\nselected sources:")
    print(s[s.feature.str.match(r"^(comp_|li_|x_|seg_post_n_people|seg_pre_n_people)")].to_string(index=False))
