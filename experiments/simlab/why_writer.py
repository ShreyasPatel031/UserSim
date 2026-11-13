"""Per-launch "why" file, people side (orchestrator 12:48Z Nov 13; website agent's shape). SHADOW ONLY until the orchestrator says otherwise.
Aggregates only: no usernames, no person ids, every people group >= 20 or the item is omitted (missing item = "not shown").

Forecast file  <day>_<point>.json  (point = 0005): only data known before the launch day starts (00:00 PT):
  hunter_followers    hunter followersCount in the 00:05 read (an input to the 00:05 forecast)
  held_backers        held people who upvoted an earlier launch (strictly earlier day) of this hunter or a named maker, from reads
                      fetched before 00:00 PT of the day
  follow_ties         held people following the hunter or a named maker (follow reads fetched before 00:00 PT)
  follow_ties_active  of those, people with an upvote on a launch in the 30 days before the day
  audience_tiers      backers + followers by activity tier (upvotes on launches in the 90 days before the day) vs all held people
After-the-fact file  <day>_after.json  (written once the day is final; never shown on the forecast panel):
  young_upvoters      share of the launch's listed upvoters (with a join date) whose account was 30-365 days old at the launch day
  created_together    share of listed upvoters within 50 PH user ids of another listed upvoter, minus a same-size random draw from the day
  young_early_commenters  share of non-team commenters in the first 4 h whose account was < 365 days old (suppressed under 20 commenters)
/try sidecar  try_neighbours_v1.json: per row of the reactions_retrieval_v1 bundle (the site's concerns neighbours): final votes,
  daily rank, line-up size (warehouse), so the site can describe how the 20 nearest earlier launches finished.
Every item carries a note id; notes hold the measured strength (basis, n, interval). Descriptive items say they did not improve the forecast.
    python why_writer.py forecast <day> <store dir> <scratchpad> <out dir>     (line-up from raw/daily/<day>/today_0005.json)
    python why_writer.py after    <day> <store dir> <scratchpad> <out dir>     (join date from store persons, else acct/joined.parquet)
    python why_writer.py try      -     -           <scratchpad> <out dir>
"""
import hashlib, json, os, subprocess, sys
import numpy as np, pandas as pd
MODE, DAY, ST, SP, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); PT = "America/Los_Angeles"; MIN = 20; rng = np.random.default_rng(0)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); from pipeline import warehouse  # noqa: E402
SALT = open(f"{SP}/early/salt").read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
ITEMS = {
    "hunter_followers": {"label": "Hunter's followers at 00:05", "unit": "people", "note": "n_hf"},
    "held_backers": {"label": "Held people who backed this team before", "unit": "people", "note": "n_backers"},
    "follow_ties": {"label": "Held people following the hunter or makers", "unit": "people", "note": "n_follow"},
    "follow_ties_active": {"label": "...of whom upvoted something in the last 30 days", "unit": "people", "note": "n_follow"},
    "expected_held_votes": {"label": "Expected votes from people we hold", "unit": "votes", "note": "n_ehv"},
    "team_profile": {"label": "Team members with a headline or bio on their profile", "unit": "members", "note": "n_tprof"},
    "team_reviews_written": {"label": "Reviews the team wrote before launch day", "unit": "reviews", "note": "n_trev"},
    "audience_tiers": {"label": "Activity of backers and followers vs all held people (upvotes on launches in the 90 days before the day)", "unit": "share by tier: 0 / 1-9 / 10-99 / 100+ upvotes in 90 days", "note": "n_tiers"},
    "young_upvoters": {"label": "Listed upvoters with accounts 1-12 months old", "unit": "share", "note": "n_young"},
    "created_together": {"label": "Listed upvoters whose accounts were created close together", "unit": "share above chance", "note": "n_clus"},
    "young_early_commenters": {"label": "Early commenters (first 4 h) with accounts under a year old", "unit": "share", "note": "n_ycom"},
}
NOTES = {
    "n_hf": "An input to the 00:05 forecast (read at 00:05 PT).",
    "n_backers": "Descriptive. Adding team-support counts to the clean forecast plus early comments changed top-3 accuracy by +0.8 points "
                 "(95% interval -1.1 to +2.7; 176 days): no measured improvement.",
    "n_follow": "Leak-safe: counts only follows seen in reads fetched before 00:00 PT of the launch day (so the follow existed before "
                "the launch), among people in our store. Descriptive. Summing held people's expected votes, follows of the hunter and makers included, gave 0.0 top-3 gain over "
                "the clean forecast on 10 test days (Oct 29 - Nov 11). Held people cover about 41-57% of a launch's votes.",
    "n_ehv": "Leak-safe: every input (upvotes, follows of the hunter and first maker) comes from reads fetched before 00:00 PT of the launch day. "
             "Descriptive. The voter_harness pair model (held people's recent activity, topic taste, follows of the hunter and first maker; "
             "trained on the 7 previous days) summed per launch gave 0.0 top-3 gain over the clean forecast on 10 test days (Oct 29 - Nov 11). "
             "Held people cover about 41-57% of a launch's votes, so this is not a vote forecast. Coverage gives the share from the 1,000 most active.",
    "n_tprof": "Descriptive. Team profiles read before the launch day only. In a Mar - Oct backtest (profiles read in Nov, so a possible leak), "
               "'team has a bio or headline' changed top-3 by +1.3 points (95% interval 0.0 to +2.7; 176 days) over the clean forecast plus early "
               "comments; a forward test is running. Not a forecast input.",
    "n_trev": "Descriptive. Reviews dated before the launch day. Backtest partial r +0.10 (0.07 to 0.13) beyond the clean forecast; top-3 +0.6 "
              "(-0.8 to +1.9; 176 days): no measured improvement. Not a forecast input.",
    "n_tiers": "Descriptive only. Audience-mix features did not improve the forecast in testing.",
    "n_young": "After the fact. Upvoters with 1-12 month old accounts count about half in the displayed total (fitted weight 0.48, "
               "84 near-complete launches); the share alone did not explain the gap out of sample (interval includes 0).",
    "n_clus": "After the fact. Explains a small part of the gap between listed upvoters and displayed votes out of sample "
              "(cross-validated R2 0.863 -> 0.866, 928 launches, Oct 1 - Nov 10).",
    "n_ycom": "After the fact. A higher share of under-a-year-old early commenters has gone with fewer final votes than the clean forecast "
              "(partial r -0.17, 95% interval -0.23 to -0.11; 1,398 launches, Mar - Nov). As a forecast input it gave no top-3 gain.",
    "n_try": "Similar earlier launches finished like this; a forecast band built from these neighbours did not sharpen the forecast.",
}
def put(o, k, v, n, cov=None):
    if n is not None and n < MIN: return
    o[k] = {"value": v, "n_people": n, "coverage": cov, "note": ITEMS[k]["note"]}
def write(name, launches, extra):
    doc = {"as_of": extra.pop("data_cut", pd.Timestamp.now(tz="UTC").isoformat()), "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "shadow": True, "min_group": MIN, **extra,
           "items": ITEMS, "notes": NOTES, "launches": launches}
    p = os.path.join(OUT, name); json.dump(doc, open(p, "w"), indent=1, default=float); print("wrote", p, len(launches))
if MODE == "try":
    RBM = json.load(open(f"{SP}/rbundle/reactions_retrieval_v1.json"))
    W = warehouse.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); W = W[W.daily_rank.notna()]
    W["n_day"] = W.groupby("day").id.transform("count"); W["stem"] = W.slug.str.replace(r"-\d+$", "", regex=True)
    k = {(s, d): (v, r, n) for s, d, v, r, n in zip(W.stem, W.day, pd.to_numeric(W.votes, errors="coerce"), W.daily_rank, W.n_day)}
    rows = {}
    for i, m in enumerate(RBM):
        v = k.get((m["slug_stem"], m["day"]))
        if v: rows[str(i)] = {"day": m["day"], "final_votes": float(v[0]), "daily_rank": int(v[1]), "lineup_size": int(v[2])}
    json.dump({"shadow": True, "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "bundle": "reactions_retrieval_v1", "rows_matched": len(rows), "rows_total": len(RBM), "note": NOTES["n_try"], "rows": rows},
              open(os.path.join(OUT, "try_neighbours_v1.json"), "w")); print("try rows", len(rows), "of", len(RBM)); sys.exit()
D0 = pd.Timestamp(DAY).tz_localize(PT).tz_convert("UTC")
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"])
if MODE == "forecast":
    line = json.loads(gcat(f"{B}/raw/daily/{DAY}/today_0005.json") or "[]")
    W = warehouse.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str)
    W = W[W.day < DAY]
    def mk(m):
        try: return [x for x in json.loads(m) if x and not str(x).startswith("[")] if isinstance(m, str) and m.startswith("[") else []
        except Exception: return []
    team_of = {}
    for i, p, m in zip(W.id, W.poster, W.makers):
        hs = ([p] if isinstance(p, str) and p and not p.startswith("[") else []) + mk(m)
        for h in hs: team_of.setdefault(pid(h), set()).add(i)
    Eb = E[E.fetched_at < D0]; U = Eb[Eb.kind == "upvote"].drop_duplicates(["person_id", "target_id"]).copy(); U["target_id"] = U.target_id.astype(str)
    lday = dict(zip(W.id, W.day)); U["d"] = U.target_id.map(lday); U = U[U.d.notna()]
    d30 = (pd.Timestamp(DAY) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); d90 = (pd.Timestamp(DAY) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    act30 = set(U[U.d >= d30].person_id); n90 = U[U.d >= d90].groupby("person_id").size()
    SP_ = set(pd.read_parquet(f"{ST}/persons.parquet").person_id); held = set(Eb.person_id) & SP_
    U = U[U.person_id.isin(SP_)]; F = Eb[(Eb.kind == "follows") & Eb.person_id.isin(SP_)]; fol = F.groupby("target_id").person_id.apply(set).to_dict()
    tiers = lambda ps: (lambda s: {"0": float((s == 0).mean()), "1-9": float(((s >= 1) & (s < 10)).mean()), "10-99": float(((s >= 10) & (s < 100)).mean()), "100+": float((s >= 100).mean())})(pd.Series([n90.get(p, 0) for p in ps]))
    typical = tiers(list(held)); out = {}
    PPf = pd.read_parquet(f"{ST}/persons.parquet").set_index("person_id")
    PPf["pulled"] = pd.to_datetime(PPf["pull_finished_utc"], utc=True, errors="coerce") if "pull_finished_utc" in PPf else pd.NaT
    for c in ("headline", "bio"):
        if c not in PPf: PPf[c] = None
    RVe = E[E.kind == "review"] if "review" in set(E.kind.unique()) else E.iloc[:0]
    RVt = {p: pd.to_datetime(g.fetched_at, utc=True) for p, g in RVe.groupby("person_id")}
    for p in line:
        o = {}; hun = (p.get("user") or {}); team = {pid(u["username"]) for u in [hun] + (p.get("makers") or []) if u and u.get("username")}
        hf = hun.get("followersCount"); o["hunter_followers"] = {"value": hf, "n_people": None, "coverage": None, "note": "n_hf"} if hf is not None else None
        tl = set().union(*[team_of.get(t, set()) for t in team]) if team else set()
        backers = set(U[U.target_id.isin(tl)].person_id); follows = set().union(*[fol.get(t, set()) for t in team]) if team else set()
        named = len(team); cov = {"team_members_named": named}
        put(o, "held_backers", len(backers), len(backers), cov); put(o, "follow_ties", len(follows), len(follows), cov)
        fa = follows & act30; put(o, "follow_ties_active", len(fa), len(fa), cov)
        PPs = PPf.reindex([t for t in team if t in PPf.index]); PPs = PPs[PPs.pulled < D0] if len(PPs) else PPs
        if len(PPs):
            hl = lambda v: isinstance(v, str) and bool(v.strip())
            o["team_profile"] = {"value": {"members_read_before_day": int(len(PPs)), "with_headline": int(sum(hl(v) for v in PPs.headline)), "with_bio": int(sum(hl(v) for v in PPs.bio))},
                                 "n_people": None, "coverage": cov, "note": "n_tprof"}
            nrev = int(sum(int((RVt.get(m, pd.Series([], dtype="datetime64[ns, UTC]")) < D0).sum()) for m in PPs.index))
            o["team_reviews_written"] = {"value": nrev, "n_people": None, "coverage": cov, "note": "n_trev"}
        grp = backers | follows
        if len(grp) >= MIN: o["audience_tiers"] = {"value": {"this launch": tiers(list(grp)), "all held people": typical}, "n_people": len(grp), "coverage": cov, "note": "n_tiers"}
        out[str(p["id"])] = {k: v for k, v in o.items() if v}
    # expected held votes: voter_harness pair model, strict timing (reads fetched before 00:00 PT), EDGES=hunter_maker
    try:
        import tempfile
        tmp = tempfile.mkdtemp(); ld = os.path.join(tmp, "launches"); os.makedirs(ld)
        WA = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); WA["id"] = WA.id.astype(str)
        lu_ids = [str(p["id"]) for p in line]; WA = WA[~WA.id.isin(lu_ids)]
        add = pd.DataFrame([{"id": str(p["id"]), "slug": p.get("slug"), "day": DAY, "topics": json.dumps([e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or [])]),
                             "poster": (p.get("user") or {}).get("username"), "makers": json.dumps([m.get("username") for m in (p.get("makers") or []) if m.get("username")]),
                             "daily_rank": 0.0, "votes": np.nan, "updated_at": "9999"} for p in line])
        pd.concat([WA, add], ignore_index=True)[["id", "slug", "day", "topics", "poster", "makers", "daily_rank", "votes", "updated_at"]].astype({"daily_rank": float, "updated_at": str}).to_parquet(os.path.join(ld, "l.parquet"))
        pd.DataFrame({"id": lu_ids, "day": DAY}).to_parquet(os.path.join(tmp, "clean.parquet"))
        os.environ["EDGES"] = "hunter_maker"; argv0 = sys.argv; sys.argv = ["voter_harness.py", ST, os.path.join(tmp, "clean.parquet"), ld, os.path.join(SP, "early"), os.path.join(tmp, "o")]
        VH = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "voter_harness.py")).read(); g = {"__name__": "vh", "__file__": "voter_harness.py"}
        exec(VH[:VH.index("FOLL = {}")] + "FOLL = {}\n", g); sys.argv = argv0; g["C"] = pd.DataFrame({"id": lu_ids, "day": DAY})
        ev, nact = g["expected"](DAY, "strict"); print("ehv active people", nact, "launches", len(ev), "sum", round(sum(ev.values()), 1))
        act, _, _ = g["feats"](DAY, g["U"][g["U"].fetched_at < g["start"](DAY)]); top = set(act.sort_values("n90", ascending=False).index[:1000])
        ek, _ = g["expected"](DAY, "strict", top)
        for i in lu_ids:
            if i in out or True:
                o = out.setdefault(i, {})
                if nact >= MIN and ev.get(i) is not None:
                    o["expected_held_votes"] = {"value": round(ev[i], 1), "n_people": int(nact), "note": "n_ehv",
                                                "coverage": {"share_from_1000_most_active": round(ek.get(i, 0) / ev[i], 3) if ev[i] > 0 else None}}
    except Exception as e:
        print("expected_held_votes skipped:", repr(e)[:200])
    write(f"{DAY}_0005.json", out, {"day": DAY, "point": "0005", "data_cut": D0.isoformat(), "store_reads_before": D0.isoformat(), "held_people": len(held),
        "held_people_definition": "people in our store (store_v3 persons) with at least one read fetched before the data cut"})
if MODE == "after":
    PJ = pd.read_parquet(f"{ST}/persons.parquet")
    J = (PJ[["person_id", "joined", "ph_user_id"]] if {"joined", "ph_user_id"} <= set(PJ.columns) else pd.read_parquet(f"{SP}/acct/joined.parquet")).drop_duplicates("person_id"); J["jt"] = pd.to_datetime(J.joined, utc=True, errors="coerce"); J["uid"] = pd.to_numeric(J.ph_user_id, errors="coerce")
    jt = J.dropna(subset=["jt"]).set_index("person_id").jt; um = J.dropna(subset=["uid"]).set_index("person_id").uid; ju = J.dropna(subset=["uid"]).drop_duplicates("uid").set_index("uid").jt
    W = warehouse.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); ids = set(W[W.day == DAY].id)
    U = E[(E.kind == "upvote") & E.target_id.astype(str).isin(ids)].drop_duplicates(["person_id", "target_id"]).copy(); U["target_id"] = U.target_id.astype(str)
    U["age"] = (D0 - U.person_id.map(jt)).dt.total_seconds() / 86400; U["uid"] = U.person_id.map(um); pool = U.uid.dropna().unique()
    def near(u):
        u = np.sort(u); g = np.diff(u); n = np.zeros(len(u), bool); n[1:] |= g <= 50; n[:-1] |= g <= 50; return n.mean()
    day = json.loads(gcat(f"{B}/raw/daily/{DAY}/{DAY}.json") or "[]"); team = {str(p["id"]): {str(u.get("id")) for u in [p.get("user")] + (p.get("makers") or []) if u} for p in day}
    import io
    txt = gcat(f"{B}/raw/ph_at_launch/{DAY}/live/comments_ts.jsonl"); C = pd.read_json(io.StringIO(txt), lines=True) if txt.strip() else pd.DataFrame()
    if len(C):
        C["t"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); C["u"] = C.commenter_user_id.astype(str); C["launch_id"] = C.launch_id.astype(str)
        C = C[(C.t <= D0 + pd.Timedelta(hours=4)).values & np.array([u not in team.get(l, set()) for u, l in zip(C.u, C.launch_id)], bool)].drop_duplicates(["launch_id", "u"])
    out = {}
    for lid in sorted(ids):
        o = {}; g = U[U.target_id == lid]; a = g.age.dropna()
        put(o, "young_upvoters", round(float(((a >= 30) & (a < 365)).mean()), 3) if len(a) else None, len(a), {"listed_upvoters": len(g), "with_join_date": len(a)})
        u = g.uid.dropna().values
        if len(u) >= MIN and len(pool) > len(u):
            ex = near(u) - np.mean([near(rng.choice(pool, len(u), replace=False)) for _ in range(20)])
            put(o, "created_together", round(float(ex), 3), len(u), {"listed_upvoters": len(g), "with_user_id": len(u)})
        if len(C):
            cu = pd.to_numeric(C[C.launch_id == lid].u, errors="coerce").dropna(); ca = (D0 - cu.map(ju)).dt.total_seconds().dropna() / 86400
            put(o, "young_early_commenters", round(float((ca < 365).mean()), 3) if len(ca) else None, len(ca), {"early_commenters": len(cu), "with_join_date": len(ca)})
        if o: out[lid] = o
    write(f"{DAY}_after.json", out, {"day": DAY, "point": "after", "after_the_fact": True})
