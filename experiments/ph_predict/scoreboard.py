"""Daily north-star scoreboard for the website's track record (orchestrator 23:45Z Nov 11). One row per (day, point,
method) with top 3/5/10 overlap vs the final daily rank (k-overlap / k x 100, the forecast's own line-up), and a summary
of running means per (point, method, source). Rebuilt from scratch each run, so it is always consistent.

Points / sources:
  0005 published   warehouse forecasts model=launch_model (the deployed 00:05 forecast), live, Oct 25 on
  0005 makerfix    results/shadow_makerfix/<day>.json rank_makerfix (shadow, live from Nov 11); rank_unfixed beside it
  P1..P4           results/early_forecast/<day>_P*.json: pred_rank (ridge), pred_rank_api, pred_rank_blend (live from Nov 12);
                   replay rows (CF_DRY files, source=replay) for Nov 2-10 if present in results/early_forecast_replay_P/
  R0..R4           results/early_forecast/<day>_R*.json (raw votes), live; written_at after the point time -> source=late
Final ranks: warehouse launches.daily_rank, only days before today (PT). Days are PT dates.
usage: python scoreboard.py -> results/web/scoreboard.json (+ gs://.../results/web/scoreboard.json)"""
import glob, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
POINT_T = {"P1": 1, "P2": 2, "P3": 3, "P345": 3.75, "P4": 4}


def ov(pred_ids, real_ids, k):
    return len(set(pred_ids[:k]) & set(real_ids[:k])) / k * 100


# orchestrator audit 05:00Z Nov 12: a 00:05 call counts as live only if written within 30 min of 00:05 PT; P / R points
# within 90 min of their data cut; the maker / no-llm shadows are written after 01:00 PT from 00:05 inputs by design
LATE_0005 = pd.Timedelta(minutes=30)
LATE_POINT = pd.Timedelta(minutes=90)


def main():
    from pipeline import warehouse as W
    today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
    R = W.query(f"SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-25' AND day < '{today}'", do_sync=False)
    real = {d: g.sort_values("daily_rank") for d, g in R.groupby("day")}
    rows = []

    def add(day, point, method, source, ranked_ids, written_at=None):
        g = real.get(day)
        if g is None:
            return
        ids = list(dict.fromkeys(ranked_ids))   # the forecast's order; launches it did not rank can never be hit
        if len(set(ids) & set(g.id)) < 10:
            return
        sub = g.id.tolist()   # the day's full final ranking (the number-of-record convention)
        t3 = set(sub[:3])
        rows.append({"day": day, "point": point, "method": method, "source": source, "n": len(ids), "written_at": written_at,
                     **{f"top{k}": round(ov(ids, sub, k), 1) for k in (3, 5, 10)},
                     # per-pick record: our #1 / #2 / #3 in the final top 3, and #1 = the winner
                     "p1_top3": float(ids[0] in t3), "p2_top3": float(ids[1] in t3), "p3_top3": float(ids[2] in t3), "exact1": float(ids[0] == sub[0])})

    F = W.query("SELECT forecast_date d, CAST(launch_id AS VARCHAR) id, predicted_rank pr, updated_at u FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    for d, g in F.groupby("d"):
        g = g[g.u == g.u.min()]   # the first (published) run of the day; Nov 1 was run twice
        due = pd.Timestamp(d + " 00:05", tz="America/Los_Angeles")
        wa = pd.Timestamp(g.u.iloc[0]); wa = wa.tz_localize("UTC") if wa.tzinfo is None else wa
        add(d, "0005", "published", "live" if wa <= due + LATE_0005 else "late", g.sort_values("pr").id.tolist(), wa.isoformat())
    for p in sorted(glob.glob(os.path.join(HERE, "results", "shadow_makerfix", "*.json"))):
        S = json.load(open(p)); f = pd.DataFrame(S["forecast"])
        add(S["day"], "0005", "makerfix_shadow", "shadow", f.sort_values("rank_makerfix").id.tolist(), S["written_at"])
        add(S["day"], "0005", "unfixed_replay", "shadow", f.sort_values("rank_unfixed").id.tolist(), S["written_at"])
        if "rank_nollm" in f:
            add(S["day"], "0005", "nollm_shadow", "shadow", f.sort_values("rank_nollm").id.tolist(), S["written_at"])
        if "rank_clean" in f:
            add(S["day"], "0005", "clean_shadow", "shadow", f.sort_values("rank_clean").id.tolist(), S["written_at"])
        if "rank_clean_avg" in f:
            add(S["day"], "0005", "clean_avg_shadow", "shadow", f.sort_values("rank_clean_avg").id.tolist(), S["written_at"])
        if "rank_clean_nosite" in f:
            add(S["day"], "0005", "clean_nosite_shadow", "shadow", f.sort_values("rank_clean_nosite").id.tolist(), S["written_at"])
    # Grok Bot's frozen X-buzz forecasts (orchestrator 00:25Z Nov 13): results/grok_forecast/<day>_0030.json / _0200.json, top 10 by slug;
    # source live only if written before the reveal (~04:00 PT); slugs mapped to ids through raw/daily/<day>/today_0005.json
    gd = os.path.join(HERE, "results", "grok_forecast"); os.makedirs(gd, exist_ok=True)
    subprocess.run(["gsutil", "-q", "-m", "cp", "-n", f"{B}/results/grok_forecast/*.json", gd + "/"], stderr=subprocess.DEVNULL)
    for gp in sorted(glob.glob(os.path.join(gd, "*.json"))):
        try:
            G = json.load(open(gp)); d = G["day"]; tp = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"sb_lineup_{d}.json")   # line-up holds usernames: never inside the repo
            if not os.path.exists(tp):
                subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/daily/{d}/today_0005.json", tp], stderr=subprocess.DEVNULL)
            sl = {x["slug"]: str(x["id"]) for x in json.load(open(tp))}
            ids = [sl[r["slug"]] for r in sorted(G["forecast"], key=lambda r: r["rank"]) if r.get("slug") in sl]
            reveal = pd.Timestamp(d, tz="America/Los_Angeles") + pd.Timedelta(hours=4)
            src_g = "live" if pd.Timestamp(G["written_at"]) < reveal else "late"
            add(d, {"0030": "P030", "0200": "P2"}.get(G.get("point"), "P030"), f"grok_{G.get('point')}", src_g, ids, G["written_at"])
        except Exception as e:  # noqa: BLE001
            print("grok skipped", gp, repr(e)[:120])
    for src, pat in (("live", os.path.join(HERE, "results", "early_forecast", "*.json")), ("replay", os.path.join(HERE, "results", "early_forecast_replay_P", "*.json"))):
        for p in sorted(glob.glob(pat)):
            E = json.load(open(p)); f = pd.DataFrame(E.get("forecast", []))
            if f.empty:
                continue
            pt, d = E["point"], E["day"]
            s = src
            if src == "live":
                due = pd.Timestamp(E["data_up_to"]) if E.get("data_up_to") else None
                if due is not None and pd.Timestamp(E["written_at"]) > due + LATE_POINT:
                    s = "late"
            if pt.startswith("P"):
                for m, c in (("comment_ridge", "pred_rank"), ("api_rank", "pred_rank_api"), ("blend", "pred_rank_blend"), ("best", "pred_rank_best"),
                             ("depth", "pred_rank_depth"), ("best_clean", "pred_rank_best_clean"), ("best_mix", "pred_rank_best_mix"),
                             ("e5", "pred_rank_e5"), ("clean_thread", "pred_rank_clean_thread"), ("clean_thread_z", "pred_rank_clean_thread_z"), ("clean_stack", "pred_rank_clean_stack"), ("clean_nosite_thread", "pred_rank_clean_nosite_thread"), ("clean_nosite_tb", "pred_rank_clean_nosite_tb"), ("hr", "pred_rank_hr"), ("hr_clean", "pred_rank_hr_clean"), ("hybrid", "pred_rank_hybrid"), ("mrep", "pred_rank_mrep"), ("eh", "pred_rank_eh"), ("clean_nosite_hf", "pred_rank_clean_nosite_hf"), ("h25_th", "pred_rank_h25_th"), ("best_cnosite", "pred_rank_best_cnosite"), ("best_mix_th", "pred_rank_best_mix_th"), ("best_thread", "pred_rank_best_thread"), ("best_w25", "pred_rank_best_w25")):
                    # replay days without any pre-reveal API rank (Nov 2, 3: api_ranked 0) have no PH order: those rows are excluded
                    if m in ("api_rank", "blend", "best", "depth", "best_clean", "best_mix", "best_mix_th", "best_w25", "best_thread") and E.get("api_ranked", 1) == 0:
                        continue
                    # QA 10:00Z Nov 12: per-column status; backfilled columns score under their own source, blank ones not at all
                    cs = (E.get("column_status") or {}).get(c, {}).get("status", "")
                    if cs == "blank":
                        continue
                    s_c = "backfill" if cs.startswith("backfilled") else s
                    ex = set(map(str, E.get("withdrawn_excluded", [])))
                    if c in f and f[c].notna().any():
                        add(d, pt, m, s_c, [i for i in f.dropna(subset=[c]).sort_values(c).id.astype(str).tolist() if i not in ex], E["written_at"])
            else:
                add(d, pt, "raw_votes", s, f.sort_values("pred_rank").id.astype(str).tolist(), E["written_at"])
                for m, c in (("r0blend_neartie", "pred_rank_r0blend"), ("r0blend_mean", "pred_rank_r0mean")):
                    if c in f:
                        add(d, pt, m, s, f.sort_values(c).id.astype(str).tolist(), E["written_at"])
    # the site's P order is pred_rank_best: its replay record (api_depth.py, hourly hidden API rank on Nov 2-10, weights chosen
    # on the same days -> IN-SAMPLE) as source replay_in_sample; P1 = 01:00 read w 0.5, P2 / P3 = 02:00 / 03:00 reads w 0.75,
    # P4 = the 03:00 read (no pre-04:00 hourly read later than that). Per-pick fields from the replay are not held (NaN).
    ad = os.path.join(HERE, "results", "api_depth.json")
    if os.path.exists(ad):
        for r in json.load(open(ad)).get("rows", []):
            for pt, h, cand in (("P1", 1, "wmean_0.5"), ("P2", 2, "wmean_0.75"), ("P3", 3, "wmean_0.75"), ("P4", 4, "wmean_0.75")):
                if r["h"] == h and r["cand"] == cand and r["day"] in real:
                    rows.append({"day": r["day"], "point": pt, "method": "best", "source": "replay_in_sample", "n": None, "written_at": None,
                                 "top3": round(r["t3"], 1), "top5": round(r["t5"], 1), "top10": round(r["t10"], 1),
                                 "p1_top3": r.get("p1", np.nan), "p2_top3": r.get("p2", np.nan), "p3_top3": r.get("p3", np.nan), "exact1": r.get("exact", np.nan)})
    X = pd.DataFrame(rows).sort_values(["day", "point", "method"])
    summ = []
    for (pt, m, s), g in X.groupby(["point", "method", "source"]):
        row = {"point": pt, "method": m, "source": s, "days": int(len(g)), "first_day": g.day.min(), "last_day": g.day.max(),
               **{f"mean_top{k}": round(float(g[f"top{k}"].mean()), 1) for k in (3, 5, 10)},
               **{f"{c}_rate": round(100 * float(g[c].mean()), 1) for c in ("p1_top3", "p2_top3", "p3_top3", "exact1")},
               **{f"{c}_count": f"{int(g[c].sum())} of {len(g)}" for c in ("p1_top3", "p2_top3", "p3_top3", "exact1")}}
        rng_ = np.random.default_rng(0)
        for k in (3, 5, 10):   # 95% day-bootstrap interval, only when at least 5 days are scored (else null)
            c = _boot(g[f"top{k}"], rng_)
            row[f"ci_top{k}"] = [round(float(c[0]), 1), round(float(c[1]), 1)] if c is not None else None
        summ.append(row)
    actual = {d: g.head(10).id.tolist() for d, g in real.items()}
    # TODAY-ROWS BUG flag (orchestrator 16:38Z Nov 14): from Oct 26 every 00:05 model score (and the P points that use it as their prior) was
    # built with stale data/today/ rows in the hunter history (pipeline_patches/20261114_today_rows). Set TODAY_BUG_FIXED to the first night the
    # fix runs live; days from then on are not flagged.
    TODAY_BUG_FROM, TODAY_BUG_FIXED = "2026-10-26", os.environ.get("TODAY_BUG_FIXED") or None
    flag_txt = "built on polluted hunter-history inputs (today-rows bug, " + (f"fixed {TODAY_BUG_FIXED})" if TODAY_BUG_FIXED else "fix not yet live)")
    hit = (X.day >= TODAY_BUG_FROM) & ((X.day < TODAY_BUG_FIXED) if TODAY_BUG_FIXED else True) & (X.point.astype(str).eq("0005") | X.point.astype(str).str.startswith("P") | X.method.astype(str).str.contains("weekly|monthly"))
    X["input_flag"] = pd.Series([flag_txt if h else None for h in hit], index=X.index, dtype=object)
    day_flags = {d_: flag_txt for d_ in sorted(X.day[hit].unique())}
    # which model produced each published 00:05 row (explanation audit, orchestrator Nov 14): old full model Oct 25 - Nov 12, clean_nosite
    # Nov 13 - 14 (model switch, model_switch.clean_from), arm 2 from Nov 15 (Shreyas Nov 13: "if its better on backtest deploy")
    def _model(r_):
        if str(r_.point) != "0005" or r_.method != "published": return None
        return "old full model" if r_.day <= "2026-11-12" else "clean_nosite" if r_.day <= "2026-11-14" else "arm 2"
    X["model"] = pd.Series([_model(r_) for r_ in X.itertuples()], index=X.index, dtype=object)
    out = {"built_at": pd.Timestamp.now(tz="UTC").isoformat(),
           "definition": "topK = share of the forecast's top K that finished in the day's final daily top K (all ranked launches of the day), x100; days are PT dates",
           "sources": {"live": "00:05 forecast written within 30 min of 00:05 PT; P / R points within 90 min of their data cut",
                       "late": "honest data cut but written later than that (not a live call)",
                       "shadow": "shadow lines written after 01:00 PT from inputs stamped <= 00:05 (by design; not a live call)",
                       "replay": "re-run afterwards with only data up to the point time",
                       "replay_in_sample": "replay whose recipe weights were chosen on the same days (pred_rank_best on Nov 2-10)"},
           "per_pick": "p1/p2/p3_top3 = our #1/#2/#3 pick finished in the final top 3; exact1 = our #1 was the winner",
           "time_shown": "written_at (when the forecast file was written), not the data cut",
           "summary": summ, "rows": X.to_dict("records"), "actual_top10": actual,
           "day_flags": day_flags, "input_flag": "rows of the 00:05 forecast, the pre-reveal P points, weekly / monthly lines (all read a 00:05 score) on flagged days; R / C and velocity V points use votes only (velocity_shadow.py reads no 00:05 score) and are not flagged"}
    os.makedirs(os.path.join(HERE, "results", "web"), exist_ok=True)
    # orchestrator 12:47Z Nov 12: running clean vs deployed block, re-read at 25 and 50 live days (model-switch decision).
    # deployed = the published 00:05 forecast (live rows); clean = shadow_makerfix pred_clean when written, else the
    # clean_live_rows replay with 00:05 inputs (source marked per day)
    try:
        from pipeline import warehouse as W_
        Rk = W_.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
        clean = {}
        lp = os.path.join(HERE, "results", "clean_live_rows.parquet")
        if os.path.exists(lp):
            CLr = pd.read_parquet(lp)
            for d_, g_ in CLr.groupby("day"):
                clean[d_] = (g_.sort_values("clean_v3", ascending=False).id.astype(str).tolist(), "replay_0005_inputs")
        for f_ in glob.glob(os.path.join(HERE, "results", "shadow_makerfix", "*.json")):
            SF = pd.DataFrame(json.load(open(f_))["forecast"])
            if "pred_clean" in SF and SF.pred_clean.notna().any():
                clean[os.path.basename(f_)[:10]] = (SF.sort_values("pred_clean", ascending=False).id.astype(str).tolist(), "shadow")
        pub = {r["day"]: r for r in out["rows"] if r["point"] == "0005" and r["method"] == "published" and r["source"] == "live"}
        # model switch (orchestrator 00:26Z Nov 13): from results/model_switch.json "clean_from" day on, the published forecast IS
        # the clean model; "deployed" then means the OLD model's nightly shadow replay (shadow_makerfix rank_unfixed)
        msw = os.path.join(HERE, "results", "model_switch.json")
        sw_from = json.load(open(msw)).get("clean_from") if os.path.exists(msw) else None
        if sw_from:
            old_ = {r["day"]: r for r in out["rows"] if r["point"] == "0005" and r["method"] == "unfixed_replay" and r["day"] >= sw_from}
            for d_, r_ in old_.items():
                pub[d_] = r_
                if d_ in pub and any(x["day"] == d_ and x["method"] == "published" and x["source"] == "live" for x in out["rows"]):
                    pr_ = next(x for x in out["rows"] if x["day"] == d_ and x["method"] == "published" and x["source"] == "live")
                    clean.setdefault(d_, None)
            out["model_switch"] = {"clean_from": sw_from, "deployed_after_switch": "old model, shadow replay (unfixed_replay)",
                                   "clean_after_switch": "published forecast"}
        rows_cd = []
        if sw_from:
            for r_ in out["rows"]:
                if r_["point"] == "0005" and r_["method"] == "published" and r_["source"] == "live" and r_["day"] >= sw_from:
                    clean[r_["day"]] = ("__published__", "published (clean model deployed)")
        for d_, (o_, src_) in sorted((k, v) for k, v in clean.items() if v is not None):
            t_ = Rk[Rk.day == d_].sort_values("daily_rank").id.tolist()
            if d_ not in pub or len(t_) < 3:
                continue
            if o_ == "__published__":   # clean side = the published row's own scores
                pr_ = next(x for x in out["rows"] if x["day"] == d_ and x["method"] == "published" and x["source"] == "live")
                rows_cd.append({"day": d_, "clean_source": src_, "clean_top3": pr_["top3"], "clean_p1_top3": float(pr_["p1_top3"]) * 100,
                                "clean_exact1": float(pr_["exact1"]) * 100, "deployed_top3": pub[d_]["top3"],
                                "deployed_p1_top3": float(pub[d_]["p1_top3"]) * 100, "deployed_exact1": float(pub[d_]["exact1"]) * 100})
                continue
            rows_cd.append({"day": d_, "clean_source": src_, "clean_top3": len(set(o_[:3]) & set(t_[:3])) / 3 * 100, "clean_p1_top3": float(o_[0] in t_[:3]) * 100,
                            "clean_exact1": float(o_[0] == t_[0]) * 100, "deployed_top3": pub[d_]["top3"], "deployed_p1_top3": float(pub[d_]["p1_top3"]) * 100,
                            "deployed_exact1": float(pub[d_]["exact1"]) * 100})   # rows hold these two as 0/1
        Dcd = pd.DataFrame(rows_cd)
        out["clean_vs_deployed"] = {"days": int(len(Dcd)), "reread_at": [25, 50],
                                    "mean": Dcd.drop(columns=["day", "clean_source"]).mean().round(1).to_dict() if len(Dcd) else {},
                                    "clean_sources": Dcd.clean_source.value_counts().to_dict() if len(Dcd) else {}, "per_day": rows_cd}
    except Exception as e_:
        out["clean_vs_deployed"] = {"error": repr(e_)[:200]}
    # orchestrator 09:12Z Nov 12: pre-registered forward check of clean_thread's signal (thread_coef.py), embedded as is
    tc = os.path.join(HERE, "results", "web", "thread_coef.json")
    subprocess.run([sys.executable, os.path.join(HERE, "thread_coef.py")], cwd=HERE)   # refresh first (best effort)
    if os.path.exists(tc):
        out["clean_thread_coef"] = json.load(open(tc))
    p = os.path.join(HERE, "results", "web", "scoreboard.json"); json.dump(out, open(p, "w"), indent=1, default=str)
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/scoreboard.json"], check=True)
    import heartbeat; heartbeat.beat("scoreboard", None, None, "ok")
    north_star(X)
    print(json.dumps(summ, indent=0))


# backtest number beside each live line (source files in results/; update here when a backtest is re-run)
BACKTEST = {
    ("0005", "published"): ("-", "no clean backtest: the deployed model trains on inputs that need a named maker, which our API v2 reads return redacted at 00:05 but named for the day's #1 in reads after the day (the Product Hunt page itself shows the full team on launch day) (leaked 63.0 / 69.3 / 75.0). Clean equivalent: see clean_shadow"),
    ("0005", "clean_shadow"): ("56.1 / 67.5 / 74.4", "honest_preds_v2 (no input that needs a named maker), month-forward, ALL 255 scored days Mar 1 - Nov 10, truth = official daily top k (launches excluded from the test count as misses); Apr-Oct 214 days 57.6 / 68.2 / 74.6; the stricter 214-day set with the full top 10 in the test gives 53.7 / 64.6 / 75.4 (leak_check_v2.md). Live-days replay 61.9 / 67.1 / 76.4 on 14 days vs deployed 57.1 (clean_live.md)"),
    ("0005", "makerfix_shadow"): ("-", "the earlier 60.2 / 68.6 / 75.7 (maker_resolve.md) used the leaking maker-profile cache; no clean backtest"),
    ("P1", "best"): ("66.7 / 66.7 / 78.3", "REPLAY, 6 days (Nov 2-10), leave-one-day-out choice: 0.5 x API rank + 0.5 x LM rank (api_depth.md); LM 38.9 / 60.0 / 76.7"),
    ("P2", "best"): ("72.2 / 76.7 / 80.0", "REPLAY, 6 days, LODO: 0.75 x API rank + 0.25 x LM rank (api_depth.md)"),
    ("P3", "best"): ("83.3 / 80.0 / 80.0", "REPLAY, 6 days, LODO: 0.75 x API + 0.25 x LM (P4 uses the same 03:00 read in the replay)"),
    ("P4", "best"): ("83.3 / 80.0 / 80.0", "REPLAY, 6 days, as P3 (hourly reads; the live P4 uses the 04:00 15-min read)"),
    ("P1", "comment_ridge"): ("63.9 / 71.7 / 76.1", "identity-free comment ridge (no team split; pred_rank from Nov 12) over the clean LM (honest_preds_v2, 57.6 / 68.2 / 74.7 alone), 207 days month-forward (comment_forecast_v2_teamc.md); the orchestrator's independent rebuild gives about 60 / 70 / 75 at +1 h; live comments at +1 h are about half captured"),
    ("P2", "comment_ridge"): ("65.5 / 72.5 / 76.8", "same, identity-free, clean LM"), ("P3", "comment_ridge"): ("67.1 / 72.6 / 76.7 ", "same, identity-free, clean LM"),
    ("P4", "comment_ridge"): ("65.9 / 72.7 / 77.1", "same, identity-free, clean LM"),
    ("R0", "raw_votes"): ("72 / 77 / 88", "6-day replay (early_forecast_replay.json); 85 / 93 / 92 first hour after reveal on 9 days"),
    ("R0q", "raw_votes"): ("75 / 80 / 88", "4-day 15-min replay (reveal_gap.md)"), ("R0h", "raw_votes"): ("75 / 90 / 88", "4-day 15-min replay (reveal_gap.md)"),
    ("R0", "r0blend_neartie"): ("58 / 70 / 88", "4-day replay; R0 votes with 10% near-ties broken by the P4 blend"),
    ("R0", "r0blend_mean"): ("67 / 75 / 88", "4-day replay; mean rank of R0 votes and the P4 blend (Nov 9 has no P4: votes only)"),
    ("R1", "raw_votes"): ("83 / 90 / 88", "6-day replay; 83 / 90 / 88 on the 4-day 15-min replay"), ("R2", "raw_votes"): ("83 / 90 / 93", "6-day replay"),
    ("R4", "raw_votes"): ("94 / 90 / 95", "6-day replay; 93 / 95 / 93 at 08:00-12:00 PT on 29 days"),
    ("week", "dayend_votes"): ("57.5 / 71.5 / 77.8", "end-of-week call without dated votes, 40 weeks (weekly_forecast.md); 100 / 80 / 90 with day-end votes on 1 week"),
    ("month", "monthlyRank"): ("75 / 75 / 80", "dated reads, 4 months (E5 monthly_northstar); 42 / 50 / 52 from daily rank"),
}
ORDER = [("0005", "published"), ("0005", "clean_shadow"), ("0005", "clean_avg_shadow"), ("0005", "makerfix_shadow"), ("0005", "unfixed_replay"), ("0005", "nollm_shadow")] + \
        [(p, m) for p in ("P030", "P0", "P1", "P2", "P3", "P345", "P4") for m in ("best", "best_w25", "best_clean", "best_mix", "best_mix_th", "e5", "clean_thread", "clean_thread_z", "clean_stack", "depth", "comment_ridge", "api_rank", "blend")] + \
        [(p, "raw_votes") for p in ("R0", "R0q", "R0h", "R1", "R2", "R4")] + [("R0", "r0blend_neartie"), ("R0", "r0blend_mean")] + [("week", "dayend_votes"), ("month", "monthlyRank"), ("month", "votes")]


def _boot(v, rng, n=2000):
    v = np.asarray(v, float)
    if len(v) < 5:
        return None
    b = np.array([v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)])
    return np.percentile(b, [2.5, 97.5])


def north_star(X):
    """results/NORTH_STAR.md: one table, every forecast time, live record (with 95% day-bootstrap intervals when n >= 5)
    beside the backtest. Weekly / monthly lines from their forward files."""
    rng = np.random.default_rng(0)
    rows = {}
    for (pt, m, src), g in X.groupby(["point", "method", "source"]):
        rows.setdefault((pt, m), {})[src] = g
    for kind, fp, cols in (("week", "weekly_forecast_forward.jsonl", {"dayend_votes": "week_top"}),
                           ("month", "monthly_forecast_forward.jsonl", {"monthlyRank": "monthlyRank_month_top", "votes": "votes_month_top"})):
        f = os.path.join(HERE, "results", fp)
        if os.path.exists(f):
            W_ = pd.DataFrame([json.loads(l) for l in open(f)])
            if kind == "week":
                W_ = W_[(W_.point == "dayend") & (pd.to_datetime(W_.day).dt.dayofweek == 6)]   # the Sunday end-of-week call
            else:
                W_ = W_.sort_values("day").groupby("month").tail(1)   # the month-end call
            for m, pre in cols.items():
                if len(W_):
                    rows.setdefault((kind, m), {})["live"] = W_.rename(columns={f"{pre}{k}": f"top{k}" for k in (3, 5, 10)})
    L = ["# North star: Product Hunt forecast accuracy", "",
         f"Regenerated by scoreboard.py at {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%MZ')}. topK = share of the forecast's top K "
         "that finished in the final top K (daily rank for 00:05 / P / R; weekly and monthly rank for the period lines). "
         "Days are PT. 95% intervals are day bootstraps, shown when at least 5 days are scored. "
         "Sources: live = written in time; late = honest data cut written afterwards; replay = re-run afterwards.", "",
         "| forecast | when (data cut) | live: days | live top 3 / 5 / 10 [95% CI] | live #1 / #2 / #3 pick in top 3 | other rows (source: days, top 3/5/10) | backtest top 3 / 5 / 10 | backtest basis |",
         "|---|---|---|---|---|---|---|---|"]
    WHEN = {"0005": "00:05 PT", "P030": "00:30 PT", "P0": "00:45 PT", "P1": "01:00 PT", "P2": "02:00 PT", "P3": "03:00 PT", "P345": "03:45 PT", "P4": "04:00 PT", "R0": "reveal ~04:00 PT",
            "R0q": "reveal +15 min", "R0h": "reveal +30 min", "R1": "reveal +1 h", "R2": "reveal +2 h", "R4": "reveal +4 h", "week": "Sunday 23:59 PT", "month": "month end"}
    for key in ORDER:
        d = rows.get(key, {}); live = d.get("live")
        if live is not None and len(live):
            mean = [live[f"top{k}"].mean() for k in (3, 5, 10)]
            ci = [_boot(live[f"top{k}"], rng) for k in (3, 5, 10)]
            cell = " / ".join(f"{m_:.1f}" + (f" [{c[0]:.0f}, {c[1]:.0f}]" if c is not None else "") for m_, c in zip(mean, ci))
            nd = len(live)
            pk = " / ".join(f"{int(live[c].sum())}/{nd}" for c in ("p1_top3", "p2_top3", "p3_top3")) if "p1_top3" in live else "-"
        else:
            cell, nd, pk = "-", 0, "-"
        other = "; ".join(f"{s_}: {len(g)}, " + " / ".join(f"{g[f'top{k}'].mean():.0f}" for k in (3, 5, 10)) for s_, g in d.items() if s_ != "live") or "-"
        bt = BACKTEST.get(key, ("-", "-"))
        L.append(f"| {key[0]} {key[1]} | {WHEN.get(key[0], '')} | {nd} | {cell} | {pk} | {other} | {bt[0]} | {bt[1]} |")
    L += ["", "Notes: the 00:05 published line is the number of record (first published run per day; duplicate rows removed); "
          "a run written more than 30 min after 00:05 PT counts as late (Oct 25-28 and Nov 1 were written hours later; Oct 30 86 min). "
          "Shadow lines are written after 01:00 PT from 00:05 inputs by design. Times shown on the site are written_at. "
          "P replay rows exclude days without a pre-reveal API rank (Nov 2, 3) for the API-based methods; P replay weights were chosen on the same 6 days (in-sample). "
          "P-point API rank and blend have no months-long backtest (the API's pre-reveal rank is only held from Nov 4). "
          "Weekly / monthly lines start scoring after their first full period (week of Nov 9-15; November)."]
    p = os.path.join(HERE, "results", "NORTH_STAR.md"); open(p, "w").write("\n".join(L) + "\n")
    subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/web/NORTH_STAR.md"], check=True)
    print("\n".join(L))


if __name__ == "__main__":
    main()
