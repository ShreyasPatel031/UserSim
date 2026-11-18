"""Arm-3 live top-3 miss anatomy (pre-registered: results/arm3_miss_anatomy_prereg.md).
For each live arm-3 day with truth: misses = true top 3 not in arm-3's 00:05 top 3; bucket (a) a 00:05 input at/above arm-3's own top-3
minimum and non-zero, (b) not (a) but top 3 at 03:45 by hidden api_rank, n_c or u_out, (c) neither. Counts only (launch ids).
usage: python miss_anatomy_arm3.py -> results/arm3_miss_anatomy.{json,md}"""
import json, os, subprocess, tempfile
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
IN0005 = ["ph_hunter_followers", "x_maker_sum_followers", "x_company_followers", "promo_reactions", "promo_posts"]
H345 = ["api_rank", "n_c", "u_out", "cv_sum"]


def arm3(d):
    p = tempfile.mkdtemp() + "/f.parquet"
    if subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/forecast_{d}.parquet", p], capture_output=True).returncode: return None, None
    F = pd.read_parquet(p); F["id"] = F.id.astype(str)
    if "pred_arm3" in F and F.pred_arm3.notna().all() and str(F.get("published_model", pd.Series([""])).iloc[0]) == "arm3":
        return F, "published pred_arm3"
    s = cat(f"{B}/results/shadow_arm3/{d}.json")
    if s and json.loads(s).get("status") == "ok":
        m = {r["id"]: r["pred_arm3"] for r in json.loads(s)["ranking"]}; F["pred_arm3"] = F.id.map(m)
        if F.pred_arm3.notna().all(): return F, "shadow_arm3"
    return None, None


def main():
    TD = json.loads(cat(f"{B}/results/web/truth_daily.json"))["days"]
    out, rows = {}, []
    for d in [x.strftime("%Y-%m-%d") for x in pd.date_range("2026-11-16", max(TD))]:
        if d not in TD: continue
        F, src = arm3(d)
        if F is None: out[d] = "no arm-3 score"; continue
        tr = {str(i): int(r) for i, r in TD[d]["ranks"].items()}
        F = F.sort_values(["pred_arm3", "id"], ascending=[False, True]).reset_index(drop=True); F["a3_rank"] = range(1, len(F) + 1)
        P = json.loads(cat(f"{B}/results/early_forecast/{d}_P345.json") or "{}").get("forecast", [])
        H = pd.DataFrame(P); H = H.assign(id=H.id.astype(str)).set_index("id") if len(H) else pd.DataFrame(columns=H345)
        top_a3 = F[F.a3_rank <= 3]; true3 = [i for i, r in tr.items() if r <= 3]
        hr = {c: (H[c].rank(ascending=(c == "api_rank"), method="min") if c in H else pd.Series(dtype=float)) for c in ("api_rank", "n_c", "u_out")}
        for i in true3:
            if i in set(top_a3.id): continue
            r = F[F.id == i]
            if not len(r): rows.append({"day": d, "id": i, "true_rank": tr[i], "bucket": "not in 00:05 line-up"}); continue
            r = r.iloc[0]; feats = {c: (None if pd.isna(r.get(c)) else round(float(r[c]), 3)) for c in IN0005 if c in F}
            mins = {c: float(top_a3[c].min()) for c in IN0005 if c in F}
            a_hits = [c for c in feats if feats[c] is not None and feats[c] > 0 and feats[c] >= mins[c]]
            h = {c: (None if i not in H.index or pd.isna(H.loc[i].get(c)) else float(H.loc[i][c])) for c in H345 if c in H}
            b_hits = [c for c in ("api_rank", "n_c", "u_out") if i in hr[c].index and hr[c][i] <= 3]
            bucket = "a" if a_hits else ("b" if b_hits else ("c" if len(H) else "c (no 03:45 file)"))
            rows.append({"day": d, "id": i, "true_rank": tr[i], "a3_rank": int(r.a3_rank), "a3_source": src, "inputs_0005": feats,
                         "a3_top3_min_0005": {c: round(v, 3) for c, v in mins.items()}, "a_features": a_hits, "h345": h,
                         "b_signals": b_hits, "bucket": bucket, "known": bool(r.get("known", False))})
        out[d] = {"source": src, "launches": len(F), "a3_top3_hits": len(set(top_a3.id) & set(true3)), "p345": bool(len(H))}
    n = len(rows); bk = pd.Series([r["bucket"][0] for r in rows]).value_counts().to_dict() if n else {}
    af = pd.Series([c for r in rows if r["bucket"] == "a" for c in r["a_features"]]).value_counts().to_dict() if n else {}
    bf = pd.Series([c for r in rows if r["bucket"] == "b" for c in r["b_signals"]]).value_counts().to_dict() if n else {}
    res = {"prereg": "results/arm3_miss_anatomy_prereg.md", "days": out, "n_days": sum(isinstance(v, dict) for v in out.values()),
           "misses": n, "bucket_counts": bk, "bucket_shares": {k: round(v / n, 3) for k, v in bk.items()} if n else {},
           "bucket_a_features": af, "bucket_b_signals": bf, "rows": rows}
    json.dump(res, open(R("arm3_miss_anatomy.json"), "w"), indent=1, default=str)
    md = ["# Arm-3 live top-3 miss anatomy", "", f"- days {res['n_days']}: {out}", f"- misses {n}; buckets {bk}; shares {res['bucket_shares']}",
          f"- bucket (a) features (00:05 input at/above arm-3's top-3 minimum): {af}", f"- bucket (b) 03:45 signals (top 3 by): {bf}", ""]
    for r in rows:
        md.append(f"- {r['day']} id {r['id']} true #{r['true_rank']} arm3 #{r.get('a3_rank')} bucket {r['bucket']} a={r.get('a_features')} b={r.get('b_signals')}")
    open(R("arm3_miss_anatomy.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
