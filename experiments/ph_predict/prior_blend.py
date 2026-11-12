"""Which 00:05 prior gives the best hidden-rank blend before the reveal? (orchestrator 12:47Z Nov 12; REPLAY, counts only)
Days: pre-reveal replay days with a clean 00:05 score (clean_live_rows clean_v3 / shadow pred_clean) and hourly hidden ranks.
Priors: published (deployed 00:05 LM), clean, clean_thread_z, clean_stack (results/thread_live_model_z.json, within-day z;
thread features at 00:05 PT: comments_ts + api_replies created <= 00:05, hunter = daily JSON post.user.id, unknown -> day mean).
Blend = w x hidden API rank position + (1 - w) x prior position, w fixed 0.25 / 0.5 / 0.75 at 00:30 / 01:00 / 02:00 PT
(latest vote_snapshots rank_now read <= the point). usage: python prior_blend.py -> results/prior_blend.md"""
import json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B, lm_scores
TMP = os.environ.get("TMPDIR", "/tmp")
PTS = (("00:30", 0.5, 0.25), ("01:00", 1.0, 0.5), ("02:00", 2.0, 0.75))


def get(path, d):
    p = os.path.join(d, os.path.basename(path).replace("*", "all"))
    return p if subprocess.run(["gsutil", "-q", "cp", path, p], stderr=subprocess.DEVNULL).returncode == 0 else None


def thread(day, ids):
    d = tempfile.mkdtemp(dir=TMP); rows = []
    cp = get(f"{B}/raw/ph_at_launch/{day}/live/comments_ts.jsonl", d)
    if cp:
        for l in open(cp):
            r = json.loads(l)
            rows.append((str(r["launch_id"]), r.get("comment_id"), str(r.get("commenter_user_id") or r.get("user_id") or ""), r.get("created_at"), r.get("parent_id")))
    rd = os.path.join(d, "rep"); os.makedirs(rd)
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{B}/raw/ph_at_launch/{day}/api_replies/*.jsonl", rd + "/"], stderr=subprocess.DEVNULL)
    for f in os.listdir(rd):
        for l in open(os.path.join(rd, f)):
            r = json.loads(l)
            rows.append((str(r.get("post_id")), r.get("comment_id"), str(r.get("commenter_user_id") or ""), r.get("createdAt"), r.get("parentId")))
    C = pd.DataFrame(rows, columns=["id", "cid", "u", "c", "parent"]).drop_duplicates("cid")
    C["ts"] = pd.to_datetime(C.c, utc=True, errors="coerce")
    C = C[C.ts <= pd.Timestamp(day + " 00:05", tz="America/Los_Angeles").tz_convert("UTC")].sort_values("ts")
    dp = get(f"{B}/raw/daily/{day}/{day}.json", d)
    hun = {str(x["id"]): str((x.get("user") or {}).get("id") or "") for x in json.load(open(dp))} if dp else {}
    out = []
    for i in ids:
        g = C[C.id == i]; tops = g[g.parent.isna()]; fa = tops.u.iloc[0] if len(tops) else None; h = hun.get(i, "")
        out.append({"id": i, "th_has_first": float(fa is not None), "th_hunter_first": float(bool(fa) and fa == h) if h else np.nan,
                    "th_n_pre": float(g[g.u != h].u.nunique()) if h else np.nan})
    E = pd.DataFrame(out)
    for c in ("th_hunter_first", "th_n_pre"):
        E[c] = E[c].fillna(E[c].mean() if E[c].notna().any() else 0.0)
    return E.set_index("id"), len(C), int(sum(1 for i in ids if not hun.get(i)))


def main():
    from pipeline import warehouse as W
    R = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots', do_sync=False); V["a"] = pd.to_datetime(V.a, utc=True)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows.parquet")); CL["id"] = CL.id.astype(str)
    ZM = json.load(open(os.path.join(HERE, "results", "thread_live_model_z.json")))["models"]
    days = [d for d in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11")]
    res, info = [], {}
    for day in days:
        truth = R[R.day == day].sort_values("daily_rank").id.tolist(); ids = sorted(truth)
        cl = dict(zip(CL[CL.day == day].id, CL[CL.day == day].clean_v3))
        sp = os.path.join(HERE, "results", "shadow_makerfix", f"{day}.json")
        if not cl and os.path.exists(sp):
            SF = pd.DataFrame(json.load(open(sp))["forecast"])
            if "pred_clean" in SF:
                cl = dict(zip(SF.id.astype(str), SF.pred_clean))
        lm = lm_scores(day)
        if not cl or not lm:
            info[day] = "skipped: no clean 00:05 score" if not cl else "skipped: no published LM"; continue
        E, nc, hm = thread(day, ids)
        E["honest"] = pd.Series(cl).reindex(ids).fillna(min(cl.values()) - 0.1).values
        zd = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
        pri = {"published": pd.Series({i: lm.get(i, -99) for i in ids}), "clean": E.honest}
        E["slug_num_l"] = 1.0
        for nm in ("clean_thread_z", "clean_stack"):
            pri[nm] = sum(zd(E[f]) * c for f, c in ZM[nm]["coef"].items())
        info[day] = {"comments_le_0005": nc, "hunter_unknown": hm}
        t0 = pd.Timestamp(day + " 00:00", tz="America/Los_Angeles").tz_convert("UTC"); g = V[V.d == day]
        for lab, h, w in PTS:
            S = g[g.a <= t0 + pd.Timedelta(hours=h)].sort_values("a").groupby("id").rank_now.last()
            if S.empty:
                continue
            api = pd.Series({i: S.get(i, 999) for i in ids}).rank(method="first")
            orders = {}
            for nm, s in pri.items():
                pp = (-s.reindex(ids)).rank(method="first")
                orders[nm] = (w * api + (1 - w) * pp + 1e-6 * pp).sort_values().index.tolist()
            for nm, o in orders.items():
                r = {"day": day, "point": lab, "prior": nm, "source": "replay"}
                for k in (3, 5, 10):
                    r[f"top{k}"] = len(set(o[:k]) & set(truth[:k]))
                r["p1"] = int(o[0] in truth[:3]); r["same_top3_as_published"] = int(set(o[:3]) == set(orders["published"][:3]))
                r["same_top10_as_published"] = int(set(o[:10]) == set(orders["published"][:10])); res.append(r)
    X = pd.DataFrame(res)
    T = X.groupby(["point", "prior"]).agg(days=("day", "nunique"), top3=("top3", "sum"), top5=("top5", "sum"), top10=("top10", "sum"),
                                          p1_in_top3=("p1", "sum"), same_top3_as_pub=("same_top3_as_published", "sum"),
                                          same_top10_as_pub=("same_top10_as_published", "sum")).reset_index()
    md = ["# Pre-reveal blend: which 00:05 prior (REPLAY; hits summed over days)", "", f"Days: {json.dumps(info)}", "",
          "Hits out of 3 / 5 / 10 per day, summed; p1_in_top3 = days our #1 finished top 3; same_* = days the blend's top set equals the published-prior blend's.", "",
          T.to_string(index=False)]
    open(os.path.join(HERE, "results", "prior_blend.md"), "w").write("\n".join(md) + "\n")
    X.to_csv(os.path.join(HERE, "results", "prior_blend_rows.csv"), index=False)
    print("\n".join(md))


if __name__ == "__main__":
    main()
