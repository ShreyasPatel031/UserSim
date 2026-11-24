"""X pre-launch buzz vs the published 00:05 line (pre-registered: results/x_buzz_arm3_prereg.md, amendment 1).
Lines per day: base = z(published 00:05 score as written that night); rerank = z(base) + w1 z(log1p(pre posts)) + w2 preannounce,
(w1, w2) chosen leave-one-day-out on the other days (most top-5 + top-3 hits; ties -> smaller w1, then w2); grok = Grok's frozen X-only
0030 top 10 (reference only: uses launch_day counts too). Placebo: x shuffled across launches within each day, 200 times.
usage: python x_buzz_arm3.py -> results/x_buzz_arm3.{json,md}"""
import json, os, subprocess, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
W1 = [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]; W2 = [0, 0.25, 0.5]; GRID = [(a, b) for a in W1 for b in W2]
PRIMARY_FROM = "2026-11-10"; BACKFILL = ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"]
BANNED = ("rank", "vote", "upvote", "comment", "dailyrank")   # no PH rank / vote field may feed the X inputs


def cut(d):
    return pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")


def x_rows(d):
    """pre-launch counts for day d: backfill for Nov 8-14 (window to the cut), else the 0010 file's pre_launch window. Asserts window <= cut."""
    out = {}
    if d in BACKFILL:
        for l in cat(f"{B}/raw/ph_at_launch/{d}/x_buzz_backfill.jsonl").splitlines():
            if not l.strip(): continue
            x = json.loads(l); assert pd.Timestamp(x["pre_window_end"]) <= cut(d), (d, x["pre_window_end"])
            out[str(x["launch_id"])] = {"posts": x.get("pre_post_count"), "pre": bool(x.get("maker_preannounced_ph_launch")),
                                        "partial": bool(x.get("window_partial")), "slug": x.get("slug")}
        return out, "backfill (pre window, count API)"
    L = json.loads(cat(f"{B}/raw/daily/{d}/today_0005.json") or "[]"); sid = {p["slug"]: str(p["id"]) for p in L}
    for l in cat(f"{B}/raw/ph_at_launch/{d}/x_buzz_0010.jsonl").splitlines():
        if not l.strip(): continue
        x = json.loads(l)
        if x.get("window") != "pre_launch": continue
        assert pd.Timestamp(x["window_end"]) <= cut(d), (d, x["window_end"])
        if x["slug"] in sid:
            out[sid[x["slug"]]] = {"posts": x.get("post_count"), "pre": bool(x.get("maker_preannounced_ph_launch")), "partial": False, "slug": x["slug"]}
    return out, "x_buzz_0010 pre_launch"


def base_rows(d):
    p = tempfile.mkdtemp() + "/f.parquet"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], capture_output=True).returncode: return None, None
    F = pd.read_parquet(p); F["id"] = F.id.astype(str)
    col = next(c for c in ("pred_arm3", "pred_arm2", "pred") if c in F and F[c].notna().all())
    return dict(zip(F.id, F[col].astype(float))), col


def arm3_rows(d):
    if d >= "2026-11-17":
        b, c = base_rows(d); return (b, c) if c == "pred_arm3" else (None, None)
    s = cat(f"{B}/results/shadow_arm3/{d}.json")
    if not s: return None, None
    j = json.loads(s)
    return ({r["id"]: r["pred_arm3"] for r in j["ranking"]}, "shadow_arm3") if j.get("status") == "ok" and j["ranking"] else (None, None)


z = lambda v: (v - v.mean()) / (v.std(ddof=0) or 1.0)


def frame(d, base, X):
    ids = sorted(base); df = pd.DataFrame({"id": ids, "base": [base[i] for i in ids]})
    df["posts"] = [X.get(i, {}).get("posts") for i in ids]; df["preann"] = [float(X.get(i, {}).get("pre", False)) for i in ids]
    df["x_missing"] = df.posts.isna()
    lx = np.log1p(df.posts.astype(float)); lx = lx.fillna(lx.median() if lx.notna().any() else 0.0)   # missing = day median, never 0
    df["zb"] = z(df.base); df["zx"] = z(lx); return df


def order(df, w):
    s = df.zb + w[0] * df.zx + w[1] * df.preann
    return df.assign(s=s).sort_values(["s", "id"], ascending=[False, True]).id.tolist()


def hits(o, true_rank):
    return [len(set(o[:k]) & {i for i, r in true_rank.items() if r <= k}) / k for k in (3, 5, 10)]


def lodo(days, D, TR, shuffle_rng=None):
    if shuffle_rng is not None:
        D = {d: D[d].assign(zx=shuffle_rng.permutation(D[d].zx.values), preann=shuffle_rng.permutation(D[d].preann.values)) for d in days}
    H = {d: {w: hits(order(D[d], w), TR[d]) for w in GRID} for d in days}
    res, ch = {}, {}
    for d in days:
        oth = [x for x in days if x != d]
        key = lambda w: (sum(H[x][w][1] + H[x][w][0] for x in oth), -w[0], -w[1])
        w = max(GRID, key=key); ch[d] = list(w); res[d] = (H[d][(0, 0)], H[d][w])
    return res, ch


def boot(D_, n=10000, seed=0):
    D_ = np.asarray(D_); rng = np.random.default_rng(seed)
    bs = np.array([D_[rng.integers(0, len(D_), len(D_))].mean() for _ in range(n)])
    return [round(100 * D_.mean(), 1), round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]


def analyse(days, D, TR):
    if len(days) < 3: return {"n_days": len(days), "note": "too few days"}
    res, ch = lodo(days, D, TR)
    base = np.array([res[d][0] for d in days]); rr = np.array([res[d][1] for d in days]); diff = rr - base
    out = {"n_days": len(days), "days": days, "base_3_5_10": [round(100 * v, 1) for v in base.mean(0)],
           "rerank_3_5_10": [round(100 * v, 1) for v in rr.mean(0)],
           "diff_top3": boot(diff[:, 0]), "diff_top5": boot(diff[:, 1]), "diff_top10": boot(diff[:, 2]), "lodo_choice": ch,
           "days_changed": {d: [round(100 * (res[d][1][k] - res[d][0][k]), 1) for k in range(3)] for d in days if res[d][1] != res[d][0]}}
    rng = np.random.default_rng(1); pl = []
    for _ in range(200):
        r2, _c = lodo(days, D, TR, rng); pl.append(np.mean([np.array(r2[d][1]) - np.array(r2[d][0]) for d in days], 0))
    out["placebo_mean_diff_3_5_10"] = [round(100 * v, 2) for v in np.mean(pl, 0)]
    for k, nm in ((0, "top3"), (1, "top5")):
        m, s = diff[:, k].mean(), diff[:, k].std(ddof=1)
        out[f"n_needed_{nm}"] = (int(np.ceil((1.96 * s / m) ** 2)) if m > 0 and s > 0 else None)
    return out


def main():
    TD = json.loads(cat(f"{B}/results/web/truth_daily.json"))["days"]
    cand = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-11-08", max(TD))]
    D, D3, TR, info = {}, {}, {}, {}
    for d in cand:
        if d not in TD: info[d] = "no truth"; continue
        X, xs = x_rows(d); b, bc = base_rows(d)
        if not X or b is None: info[d] = f"skip: x {len(X)} rows, base {bc}"; continue
        assert not any(any(t in k.lower() for t in BANNED) for v in X.values() for k in v), "PH rank/vote field in X inputs"
        TR[d] = {str(i): int(r) for i, r in TD[d]["ranks"].items()}
        D[d] = frame(d, b, X); a3, a3c = arm3_rows(d)
        if a3: D3[d] = frame(d, a3, X)
        info[d] = {"x_source": xs, "base": bc, "arm3": a3c, "launches": len(b), "x_matched": int((~D[d].x_missing).sum()),
                   "x_missing": int(D[d].x_missing.sum()), "partial_window": any(v["partial"] for v in X.values()),
                   "with_posts": int((D[d].posts.fillna(0) > 0).sum()), "preannounced": int(D[d].preann.sum())}
    prim = [d for d in sorted(D) if d >= PRIMARY_FROM and not info[d]["partial_window"]]
    allx = sorted(D)
    G = {}
    for d in sorted(TR):
        s = cat(f"{B}/results/grok_forecast/{d}_0030.json")
        if not s: continue
        L = json.loads(cat(f"{B}/raw/daily/{d}/today_0005.json") or "[]"); sid = {p["slug"]: str(p["id"]) for p in L}
        o = [sid.get(r["slug"]) for r in json.loads(s)["forecast"]]; o = [i for i in o if i]
        G[d] = [round(100 * v, 1) for v in hits(o, TR[d])]
    res = {"prereg": "results/x_buzz_arm3_prereg.md (amendment 1)", "days": info,
           "primary": analyse(prim, D, TR), "secondary_arm3_days": analyse(sorted(D3), D3, TR),
           "incl_partial_nov8_9": analyse(allx, D, TR),
           "grok_x_only_top10_reference": {"per_day_3_5_10": G, "mean": [round(float(np.mean([v[k] for v in G.values()])), 1) for k in range(3)] if G else None,
                                           "note": "uses launch_day counts to ~00:22 PT: not leak-free for 00:05; reference only"}}
    p = res["primary"]; ok = p.get("diff_top3", [0, 0])[1] > 0 or p.get("diff_top5", [0, 0])[1] > 0
    res["decision"] = "DEPLOY CANDIDATE (interval clear of 0 on top 3 or top 5)" if ok else "NOT CLEAR: scored forward shadow line"
    json.dump(res, open(R("x_buzz_arm3.json"), "w"), indent=1, default=str)
    md = ["# X pre-launch buzz vs the published 00:05 line", "", f"Decision: {res['decision']}", ""]
    for k in ("primary", "secondary_arm3_days", "incl_partial_nov8_9"):
        a = res[k]; md.append(f"## {k}: n = {a['n_days']} days")
        if "diff_top5" in a:
            md += [f"- base {a['base_3_5_10']} / rerank {a['rerank_3_5_10']} (top 3/5/10)",
                   f"- rerank - base, day bootstrap 95%: top 3 {a['diff_top3']}, top 5 {a['diff_top5']}, top 10 {a['diff_top10']}",
                   f"- placebo (x shuffled within day, 200x) mean diff: {a['placebo_mean_diff_3_5_10']}",
                   f"- LODO weights per day: {a['lodo_choice']}; days changed: {a['days_changed']}",
                   f"- n days needed for a clear result at this effect: top 3 {a['n_needed_top3']}, top 5 {a['n_needed_top5']}"]
        md.append("")
    md += ["## Grok X-only frozen top 10 (reference, not leak-free for 00:05)", f"- per day: {G}", f"- mean: {res['grok_x_only_top10_reference']['mean']}"]
    open(R("x_buzz_arm3.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
