"""PH-FWD12 (orchestrator 09:45Z Nov 23): paired forward scoring of every shadow line against the published arm3.
Lines: arm3 (published 00:05, pred_arm3), arm2 (pred_arm2), LM (pred), it8, arrivals, promo_posts (frozen w = 0.1 rule),
Grok X-buzz top 10 (00:30 PT file). Each line uses only its own frozen file for day d.
Leak checks:
  - write time (bucket object time, or the file's written_at if earlier is not claimed) must be before WRITE_CUT_PT on d.
    The literal 00:05 PT cut would drop every line, the published arm3 included (its parquet lands ~00:18 PT), so the cut
    is 03:45 PT: before PH's hidden-order read and before votes are shown. Files written later are dropped and listed.
  - no line reads the 03:45 hidden-order read (none of these files take it as an input).
Truth: results/web/truth_daily.json (first warehouse part written after the PT day's close; daily_rank).
Metrics per line: daily top 3/5/10 hit % (our top k with final rank <= k; unranked picks are misses), Spearman of line
order vs final rank on ranked launches in the line (full-order lines only), paired difference vs arm3 on days both are
scored, 95% day-clustered bootstrap (10,000 draws, seed 0), days needed for the interval to clear zero at the observed
effect (n * (1.96 * se / |diff|)^2).
usage: python shadow_forward_paired.py -> results/shadow_forward_paired_v1.json"""
import json, os, subprocess, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"
KS = (3, 5, 10); WRITE_CUT_PT = "03:45"; NB = 10000
TMP = tempfile.mkdtemp()


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)


def obj_time(p):
    r = sh("gsutil", "ls", "-l", p)
    if r.returncode: return None
    ln = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith("TOTAL")]
    return pd.Timestamp(ln[0].split()[1]) if ln else None


def get(p, name):
    loc = os.path.join(TMP, name)
    return loc if sh("gsutil", "-q", "cp", p, loc).returncode == 0 else None


def cut(d):
    return pd.Timestamp(f"{d} {WRITE_CUT_PT}", tz="America/Los_Angeles").tz_convert("UTC")


def score(order, tr):
    """order: ids best first; tr: Series id -> final rank (ranked launches)."""
    r = {f"top{k}": 100.0 * len(set(order[:k]) & set(tr.index[tr <= k])) / k for k in KS}
    c = [i for i in order if i in tr.index]
    r["spearman"] = float(pd.Series(range(len(c)), index=c).rank().corr(tr.reindex(c).rank(), method="pearson")) if len(c) >= 5 else None
    return r


def main():
    days = [json.loads(l)["day"] for l in open(os.path.join(HERE, "results", "shadow_forward.jsonl"))]
    T = json.loads(sh("gsutil", "cat", f"{B}/results/web/truth_daily.json").stdout)["days"]
    promo = {json.loads(l)["day"]: json.loads(l) for l in open(os.path.join(HERE, "results", "promo_posts_shadow.jsonl"))}
    rows, drops, missing = {}, [], []
    for d in days:
        if T.get(d, {}).get("status") != "counts": missing.append([d, "all", "no final ranks"]); continue
        tr = pd.Series({str(k): float(v) for k, v in T[d]["ranks"].items()}).sort_values()
        C = cut(d); got = {}

        def keep(line, wt, order, full=True):
            if order is None: missing.append([d, line, "no file"]); return
            if wt is None or wt >= C:
                drops.append({"day": d, "line": line, "written": str(wt), "cut": str(C)}); return
            s = score(order, tr)
            if not full: s["spearman"] = None
            got[line] = s
        fp = f"{B}/raw/daily/{d}/forecast_{d}.parquet"; ft = obj_time(fp); f = get(fp, f"f_{d}.parquet")
        F = pd.read_parquet(f) if f else None
        if F is not None:
            F["id"] = F.id.astype(str)
            for line, col in (("arm3", "pred_arm3"), ("arm2", "pred_arm2"), ("LM", "pred")):
                ok = col in F and F[col].notna().mean() >= 0.9
                keep(line, ft, F.sort_values([col, "id"], ascending=[False, True]).id.tolist() if ok else None)
        for line, folder, rk in (("it8", "shadow_it8", "ev_rank"), ("arrivals", "shadow_arrivals", "arr_rank")):
            p = f"{B}/results/{folder}/ev_{d}.parquet"; loc = get(p, f"{line}_{d}.parquet")
            X = pd.read_parquet(loc) if loc else None
            if X is not None: X["id"] = X.id.astype(str)
            keep(line, obj_time(p) if loc else None, X.sort_values(rk).id.tolist() if X is not None else None)
        pr = promo.get(d)
        keep("promo_posts", pd.Timestamp(pr["written_at"]) if pr else None, [str(i) for i in pr["shadow_order"]] if pr else None)
        gp = f"{B}/results/grok_forecast/{d}_0030.json"; g = get(gp, f"g_{d}.json"); order = None; gt = None
        if g:
            G = json.load(open(g)); gt = max(pd.Timestamp(G["written_at"]), obj_time(gp))
            lu = get(f"{B}/raw/daily/{d}/today_0005.json", f"lu_{d}.json")
            L = json.load(open(lu)) if lu else []
            L = L.get("posts", L) if isinstance(L, dict) else L
            slug = {str(p.get("slug")): str(p.get("id")) for p in L if isinstance(p, dict)}
            order = [slug.get(str(x.get("slug")), "slug:" + str(x.get("slug"))) for x in sorted(G["forecast"], key=lambda x: x["rank"])]
            n_unmapped = sum(o.startswith("slug:") for o in order)
            if n_unmapped: missing.append([d, "grok", f"{n_unmapped} of {len(order)} slugs not in the 00:05 line-up (counted as misses)"])
        keep("grok_xbuzz", gt, order, full=False)
        rows[d] = {"ranked": int(len(tr)), "lines": got}
    lines = ["arm3", "arm2", "LM", "it8", "arrivals", "promo_posts", "grok_xbuzz"]
    rng = np.random.default_rng(0); out = {}
    for ln in lines:
        ds = [d for d in rows if ln in rows[d]["lines"]]
        o = {"n_days": len(ds), "days": ds}
        for m in [f"top{k}" for k in KS] + ["spearman"]:
            v = [rows[d]["lines"][ln][m] for d in ds if rows[d]["lines"][ln][m] is not None]
            o[m] = round(float(np.mean(v)), 1 if m != "spearman" else 3) if v else None
        if ln != "arm3":
            pd_ = [d for d in ds if "arm3" in rows[d]["lines"]]; o["paired_days"] = len(pd_); o["vs_arm3"] = {}
            for m in [f"top{k}" for k in KS] + ["spearman"]:
                x = np.array([rows[d]["lines"][ln][m] - rows[d]["lines"]["arm3"][m] for d in pd_
                              if rows[d]["lines"][ln][m] is not None and rows[d]["lines"]["arm3"][m] is not None], float)
                if len(x) < 2: o["vs_arm3"][m] = None; continue
                bs = x[rng.integers(0, len(x), (NB, len(x)))].mean(1); lo, hi = np.percentile(bs, [2.5, 97.5]); diff = x.mean(); se = bs.std()
                need = int(np.ceil(len(x) * (1.96 * se / abs(diff)) ** 2)) if diff else None
                o["vs_arm3"][m] = {"n": int(len(x)), "diff": round(float(diff), 3 if m == "spearman" else 1),
                                   "ci95": [round(float(lo), 3 if m == "spearman" else 1), round(float(hi), 3 if m == "spearman" else 1)],
                                   "days_needed_to_clear_zero": need, "more_days_needed": (max(0, need - len(x)) if need else None)}
            top = [o["vs_arm3"].get(f"top{k}") for k in KS]
            better = [k for k, t in zip(KS, top) if t and t["ci95"][0] > 0]
            worse = [k for k, t in zip(KS, top) if t and t["ci95"][1] < 0]
            o["decision"] = ("PROPOSE FOR DEPLOY (better on top " + ",".join(map(str, better)) + ")") if better and not worse else \
                            ("DROP from nightly shadow (worse on top " + ",".join(map(str, worse)) + ")") if worse and not better else "KEEP RUNNING (interval covers 0)"
        out[ln] = o
    res = {"experiment": "PH-FWD12", "asked": "orchestrator 09:45Z Nov 23", "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
           "truth": "results/web/truth_daily.json (first warehouse part after the PT day's close; daily_rank)",
           "write_cut": f"{WRITE_CUT_PT} PT of the day (literal 00:05 PT would drop the published arm3 itself, written ~00:18 PT)",
           "bootstrap": f"day-clustered, {NB} draws, seed 0", "lines": out, "dropped_late_files": drops, "missing": missing,
           "per_day": rows}
    json.dump(res, open(os.path.join(HERE, "results", "shadow_forward_paired_v1.json"), "w"), indent=1, default=str)
    for ln in lines:
        o = out[ln]; v = o.get("vs_arm3", {})
        f = lambda m: (f"{v[m]['diff']:+} [{v[m]['ci95'][0]:+}, {v[m]['ci95'][1]:+}] need {v[m]['days_needed_to_clear_zero']}" if v.get(m) else "-")
        print(ln, o["n_days"], o["top3"], o["top5"], o["top10"], o["spearman"], "|", f("top3"), "|", f("top5"), "|", f("top10"), "|", f("spearman"), "|", o.get("decision", "baseline"))
    print("drops", len(drops), [(x["day"], x["line"], x["written"][:16]) for x in drops]); print("missing", missing)


if __name__ == "__main__":
    main()
