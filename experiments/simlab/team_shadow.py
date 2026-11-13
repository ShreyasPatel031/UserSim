"""Nightly shadow feature: the launch team's own community upvoting before launch (orchestrator 10:38Z Nov 13). SCRIPT ONLY - not
scheduled. Run on launch day D after the 00:05 read exists. No LLM, no Product Hunt requests.
Team = the hunter (user) + every maker named in the 00:05 read (today_0005.json; redacted members skipped). A member counts only if
COMPLETE in the store AND their upvotes tab was pulled before D 00:00 PT (tabs.fetched_at), so every counted upvote was cast before
the launch. An upvote's date = the acted-on launch's day (upvote rows carry no cast time).
Per launch (ids and counts only): team_up7 / team_up30 = upvotes the eligible members gave on launches dated in the 7 / 30 days before D;
team_makers30 = distinct first-named makers of those 30-day launches; *_lag2 variants keep only launches dated >= 2 days before D (for
members pulled after their launch, this drops the post-launch "vote back" window); n_team, n_team_complete, n_team_eligible,
covered (>= 1 eligible member), store path.
PROFILE FIELDS (forward test, orchestrator 14:51Z Nov 13), from team members whose person record was pulled before D 01:00 PT
(persons.pull_finished_utc; the fleet's job 1 pulls team members at/after 00:05): n_team_pulled_0100, prof_has_headline, prof_has_bio,
prof_badges_max, prof_streak_any, prof_ranks_any, prof_mh_prior_max (maker_history launches dated before D - 12 h),
prof_reviews_before (reviews the members wrote, dated before D). n_team_estab (orchestrator 19:50Z): eligible members (held before D)
with prior footing >= 30 days before D (a team role on an earlier launch or >= 5 upvotes on launches dated then). Counts only. Read the partials at about 9 scored days.
    python team_shadow.py <today_0005.json (path or gs://)> <YYYY-MM-DD> <store dir> <salt dir> <out .jsonl>
"""
import hashlib, json, os, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
def load_json(p): return json.loads(subprocess.check_output(["gsutil", "cat", p]) if p.startswith("gs://") else open(p).read())
def features(lineup, day, store, salt_dir):
    from pipeline import warehouse
    salt = open(os.path.join(salt_dir, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    D = pd.Timestamp(day); cut = D.tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
    W = warehouse.table("launches", do_sync=True); W["id"] = W.id.astype(str); W = W.sort_values("updated_at").drop_duplicates("id", keep="last")
    lday = dict(zip(W.id, pd.to_datetime(W.day)))
    def fm(m):
        try: ms = [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
        except Exception: ms = []
        return pid(ms[0]) if ms else None
    fmaker = dict(zip(W.id, [fm(m) for m in W.makers]))
    P = pd.read_parquet(os.path.join(store, "persons.parquet")); comp = set(P[P.complete].person_id)
    T = pd.read_parquet(os.path.join(store, "tabs.parquet")); T = T[(T.tab == "upvotes") & T.person_id.isin(comp)]
    pulled = dict(zip(T.person_id, pd.to_datetime(T.fetched_at, utc=True)))
    real = lambda u: bool(u.get("username")) and not str(u["username"]).startswith("[") and str(u.get("id")) != "0"
    team = {str(x["id"]): list(dict.fromkeys(pid(u["username"]) for u in [x.get("user") or {}] + (x.get("makers") or []) if real(u))) for x in lineup}
    elig = {m for ms in team.values() for m in ms if m in pulled and pulled[m] < cut}
    E = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "kind", "target_id"]); U = E[(E.kind == "upvote") & E.person_id.isin(elig)].copy()
    U["target_id"] = U.target_id.astype(str); U = U.drop_duplicates(["person_id", "target_id"]); U["d"] = U.target_id.map(lday); U = U[U.d.notna() & (U.d < D) & (U.d >= D - pd.Timedelta(days=30))]
    G = {p: g for p, g in U.groupby("person_id")}; out = []
    d30 = D - pd.Timedelta(days=30); UA = E[(E.kind == "upvote") & E.person_id.isin(elig)].drop_duplicates(["person_id", "target_id"]).copy()
    UA["d"] = UA.target_id.astype(str).map(lday); old_up = UA[UA.d.notna() & (UA.d <= d30)].groupby("person_id").size()
    role30 = set()
    for p_, m_, d_ in zip(W.poster, W.makers, pd.to_datetime(W.day)):
        if d_ <= d30:
            for h in ([p_] if isinstance(p_, str) and p_ and not p_.startswith("[") else []) + (json.loads(m_) if isinstance(m_, str) and m_.startswith("[") else []):
                if h and not str(h).startswith("["): role30.add(pid(h))
    ESTAB = {m: (m in role30) or old_up.get(m, 0) >= 5 for m in elig}
    PP = P.set_index("person_id"); PP["pulled"] = pd.to_datetime(PP.get("pull_finished_utc"), utc=True, errors="coerce")
    for c in ("headline", "bio", "badges_count", "streak", "ranks_text_json", "maker_history_json"):
        if c not in PP: PP[c] = None
    MH = {}
    for m_, j in PP.maker_history_json.dropna().items():
        try: MH[m_] = [pd.Timestamp(e["date"]).tz_convert("UTC") for e in json.loads(j) if e.get("date")]
        except Exception: pass
    RV = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "kind", "ts_hi", "fetched_at"]); RV = RV[RV.kind == "review"]
    RVt = {p: pd.to_datetime(g.ts_hi.fillna(g.fetched_at), utc=True) for p, g in RV.groupby("person_id")}
    for lid, ms in team.items():
        em = [m for m in ms if m in elig]; o = {"launch_id": lid, "day": day, "n_team": len(ms), "n_team_complete": sum(m in comp for m in ms), "n_team_eligible": len(em), "covered": bool(em)}
        for suf, lag in (("", 1), ("_lag2", 2)):
            rows = pd.concat([G[m] for m in em if m in G]) if any(m in G for m in em) else pd.DataFrame(columns=["d", "target_id"])
            r = rows[rows.d <= D - pd.Timedelta(days=lag)] if len(rows) else rows
            o[f"team_up7{suf}"] = int((r.d >= D - pd.Timedelta(days=7)).sum()) if len(r) else 0; o[f"team_up30{suf}"] = int(len(r))
            o[f"team_makers30{suf}"] = len({fmaker.get(t) for t in r.target_id} - {None}) if len(r) else 0
        pm = [m for m in ms if m in PP.index and PP.at[m, "pulled"] is not pd.NaT and PP.at[m, "pulled"] < cut + pd.Timedelta(hours=1)]
        o["n_team_pulled_0100"] = len(pm); hl = lambda v: isinstance(v, str) and bool(v.strip())
        o["prof_has_headline"] = any(hl(PP.at[m, "headline"]) for m in pm); o["prof_has_bio"] = any(hl(PP.at[m, "bio"]) for m in pm)
        o["prof_badges_max"] = int(max([PP.at[m, "badges_count"] or 0 for m in pm], default=0)); o["prof_streak_any"] = any(hl(PP.at[m, "streak"]) for m in pm)
        o["prof_ranks_any"] = any(hl(PP.at[m, "ranks_text_json"]) and PP.at[m, "ranks_text_json"] not in ("[]", "null") for m in pm)
        o["prof_mh_prior_max"] = int(max([sum(t < cut - pd.Timedelta(hours=12) for t in MH.get(m, [])) for m in pm], default=0))
        o["prof_reviews_before"] = int(sum(int((RVt.get(m, pd.Series([], dtype="datetime64[ns, UTC]")) < cut).sum()) for m in pm))
        o["n_team_estab"] = sum(1 for m in em if ESTAB.get(m, False))   # held before the day AND prior footing (>= 30 d): team role or >= 5 upvotes
        o["store"] = os.path.abspath(store); out.append(o)
    return out
if __name__ == "__main__":
    lp, day, store, saltd, outp = sys.argv[1:6]; rows = features(load_json(lp), day, store, saltd)
    with open(outp, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    print("wrote", len(rows), "launches; covered", sum(r["covered"] for r in rows), "; team members pulled before 01:00 PT", sum(r["n_team_pulled_0100"] for r in rows), "of", sum(r["n_team"] for r in rows))
