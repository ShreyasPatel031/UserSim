"""How many people must the pool hold so that 80-90% of launch-day votes come from people we track? (Shreyas via the
orchestrator, Nov 4 20:02 UTC.) Counts only: no usernames are printed or written.

Data: warehouse events (pool people's upvotes, mostly from upvote-list page 1, dated to the upvoted launch's day) and
launches (real final votes). store_v3 (salted person ids) full all-tab pulls give each pulled person's complete upvote
list, used to measure how much of a person's voting the page-1 lists miss (completeness). The salt
(raw/population/_salt) is read only to match ids and never printed.

Parts
  1 coverage by month: share of all real votes cast by pool people (as recorded), all launches and the day's top 3.
  2 within-pool curve: pool people ranked by activity in a separate earlier window (Aug-Sep upvotes + comments, out
    of sample) or by the turnout weight; cumulative share of real votes in the test window (Oct 1-24) at N = 1k, 2k,
    5k, 10k, all; daily and top-3 separately; 95% intervals from a bootstrap over days.
  3 completeness: for people with a store_v3 full pull, upvotes in the test window in the full list vs the warehouse.
  4 capture-recapture and votes per voter: see main().
usage: python pool_size.py -> results/pool_size.json"""
import hashlib, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
BUCKET = "gs://usersim-bakeoff-347838016394/usersim_sim"
TEST = (os.environ.get("TEST_FROM", "2026-10-01"), os.environ.get("TEST_TO", "2026-10-24"))
RANK = (os.environ.get("RANK_FROM", "2026-08-01"), os.environ.get("RANK_TO", "2026-09-30"))
NS = [1000, 2000, 5000, 10000, 15000]
BOOT = int(os.environ.get("BOOT", "500"))
OUT = os.environ.get("OUT", os.path.join(HERE, "results", "pool_size.json"))


def W():
    from pipeline import warehouse as W
    return W


def frames():
    w = W()
    L = w.query("SELECT id::VARCHAR AS id, day::VARCHAR AS day, votes, daily_rank FROM launches WHERE votes IS NOT NULL AND daily_rank IS NOT NULL")
    E = w.query("SELECT person, launch_id::VARCHAR AS id, date, kind FROM events WHERE kind IN ('upvote','comment')", do_sync=False)
    Pp = w.query("SELECT person, first_seen::VARCHAR AS first_seen FROM people", do_sync=False)
    E["person"] = E.person.str.lower(); Pp["person"] = Pp.person.str.lower()
    E = E.merge(L[["id", "day"]], on="id", how="inner")   # events on featured launches, dated to the launch day
    return L, E, Pp


def by_month(L, E):
    U = E[E.kind == "upvote"].drop_duplicates(["person", "id"]).groupby("id").size().rename("pv")
    A = L.set_index("id").join(U).fillna({"pv": 0})
    A["month"] = A.day.str[:7]; A["top3"] = A.daily_rank <= 3
    out = {}
    for m, g in A[A.day >= "2026-01-01"].groupby("month"):
        t = g[g.top3]
        out[m] = {"launches": int(len(g)), "share_all": round(float(g.pv.sum() / g.votes.sum()), 3),
                  "share_top3": round(float(t.pv.sum() / t.votes.sum()), 3) if len(t) else None}
    return out, A


def curve(L, E, rank_by):
    """Cumulative share of real votes in TEST cast by the top-N pool people (ranked out of sample)."""
    R = E[(E.day >= RANK[0]) & (E.day <= RANK[1])]
    if rank_by == "activity":
        score = R.groupby("person").size()
    else:   # turnout weight: share of the window's days with any activity
        nd = pd.date_range(*RANK).size
        score = R.groupby("person").day.nunique() / nd
    T = E[(E.kind == "upvote") & (E.day >= TEST[0]) & (E.day <= TEST[1])].drop_duplicates(["person", "id"])
    everyone = pd.Index(sorted(set(E.person)))
    score = score.reindex(everyone).fillna(0).sort_values(ascending=False, kind="stable")
    rank = pd.Series(np.arange(1, len(score) + 1), index=score.index)
    T = T.assign(r=T.person.map(rank))
    Lt = L[(L.day >= TEST[0]) & (L.day <= TEST[1])].set_index("id")
    days = sorted(Lt.day.unique())
    Ns = [n for n in NS if n < len(rank)] + [len(rank)]
    # per day x N: pool votes by the top N, and real votes (all launches / top 3)
    rows = []
    for d in days:
        ld = Lt[Lt.day == d]; t3 = set(ld[ld.daily_rank <= 3].index)
        td = T[T.id.isin(ld.index)]
        r = {"day": d, "V": float(ld.votes.sum()), "V3": float(ld.loc[list(t3)].votes.sum())}
        for n in Ns:
            k = td[td.r <= n]
            r[f"a{n}"] = len(k); r[f"t{n}"] = int(k.id.isin(t3).sum())
        rows.append(r)
    D = pd.DataFrame(rows); rng = np.random.default_rng(0)
    res = {"rank_by": rank_by, "people_ranked": int(len(rank)), "people_with_rank_activity": int((score > 0).sum()), "by_N": {}}
    for n in Ns:
        def share(S, c, v): return S[c].sum() / S[v].sum()
        b = [(share(S, f"a{n}", "V"), share(S, f"t{n}", "V3")) for S in (D.sample(len(D), replace=True, random_state=rng.integers(1 << 31)) for _ in range(BOOT))]
        b = np.array(b)
        res["by_N"][str(n)] = {"share_all": round(float(share(D, f"a{n}", "V")), 3), "ci_all": np.percentile(b[:, 0], [2.5, 97.5]).round(3).tolist(),
                               "share_top3": round(float(share(D, f"t{n}", "V3")), 3), "ci_top3": np.percentile(b[:, 1], [2.5, 97.5]).round(3).tolist()}
    return res


def salt():
    return subprocess.run(["gsutil", "cat", f"{BUCKET}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()


def v3():
    d = tempfile.mkdtemp(prefix="v3_")
    for f in ("events", "persons", "tabs"):
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/population/store_v3/{f}.parquet", d], check=True)
    return {f: pd.read_parquet(f"{d}/{f}.parquet") for f in ("events", "persons", "tabs")}


def completeness(L, E, V, sl):
    """Full-pulled pool people: upvotes on TEST-window launches in their full list vs in the warehouse."""
    T = V["tabs"]; full = set(T[(T.tab == "upvotes") & T.complete].person_id)
    Ev = V["events"]; Ev = Ev[(Ev.kind == "upvote") & Ev.person_id.isin(full) & Ev.source.astype(str).str.contains("people_live")]
    Ev = Ev.assign(id=Ev.target_id.astype(str)).merge(L[["id", "day"]], on="id")
    Ev = Ev[(Ev.day >= TEST[0]) & (Ev.day <= TEST[1])]
    h = {"p_" + hashlib.sha256((sl + "producthunt:" + u).encode()).hexdigest()[:16]: u for u in set(E.person)}
    wh = E[(E.kind == "upvote") & (E.day >= TEST[0]) & (E.day <= TEST[1])].drop_duplicates(["person", "id"])
    rows = []
    for pid in full:
        u = h.get(pid)
        if u is None:
            continue
        f = set(Ev[Ev.person_id == pid].id); w_ = set(wh[wh.person == u].id)
        rows.append((len(f), len(w_), len(f & w_), len(f | w_)))
    R = pd.DataFrame(rows, columns=["full", "wh", "both", "union"])
    if not len(R):
        return {"people": 0}
    rng = np.random.default_rng(1)
    ratio = lambda S: S.wh.sum() / S.union.sum() if S.union.sum() else np.nan
    b = [ratio(R.sample(len(R), replace=True, random_state=rng.integers(1 << 31))) for _ in range(BOOT)]
    return {"people_full_pulled_in_pool": int(len(R)), "people_with_test_votes": int((R.union > 0).sum()),
            "test_votes_union": int(R.union.sum()), "in_warehouse": int(R.wh.sum()), "in_full_list": int(R.full.sum()),
            "warehouse_completeness": round(float(ratio(R)), 3), "ci": np.nanpercentile(b, [2.5, 97.5]).round(3).tolist(),
            "full_pull_people_total": int(len(full))}


def hid(sl, u):
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def discovery(V, sl, days=("2026-11-03", "2026-11-04")):
    """Capture-recapture samples found independently of voting: (a) first-page followers of each day's makers and
    hunters (makers.jsonl followers_page1), (b) the day's API commenters (commenter_user_id via the user id map).
    Returns {sample: set of salted ids}."""
    d = tempfile.mkdtemp(prefix="disc_"); S = {"maker_followers": set(), "launch_commenters": set()}
    idmap = None
    for day in days:
        f = f"{d}/makers_{day}.jsonl"
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/makers.jsonl", f], check=True)
        for l in open(f):
            r = json.loads(l)
            for x in (r.get("followers_page1") or []):
                if isinstance(x, dict) and x.get("username"):
                    S["maker_followers"].add(hid(sl, x["username"]))
        subprocess.run(["gsutil", "-q", "-m", "cp", f"{BUCKET}/raw/ph_at_launch/{day}/api_comments/*.jsonl", d], capture_output=True)
    import glob
    ids = set()
    for f in glob.glob(f"{d}/*.jsonl"):
        if os.path.basename(f).startswith("makers_"):
            continue
        for l in open(f):
            r = json.loads(l)
            if r.get("commenter_user_id") is not None:
                ids.add(str(r["commenter_user_id"]))
    if ids:
        loc = f"{d}/idmap.jsonl"
        subprocess.run(["gsutil", "-q", "cp", f"{BUCKET}/raw/population/user_id_map/user_id_map_20261103.jsonl", loc], check=True)
        M = pd.read_json(loc, lines=True, dtype=False)
        if "last_seen" in M:
            M = M.sort_values("last_seen").groupby(M.user_id.astype(str)).tail(1)
        m = dict(zip(M.user_id.astype(str), M.username.astype(str)))
        S["launch_commenters"] = {hid(sl, m[i]) for i in ids if i in m}
        S["commenter_ids_unmapped"] = len(ids - set(m))
    return S


def oct_votes(V, L):
    """Per salted person with a dated upvote pull (store_v3 people_live full pulls or people_daily page 1): upvotes on
    TEST-window launches. Pulled-person sets are returned so zero-vote people count."""
    Ev = V["events"]; up = Ev[Ev.kind == "upvote"]
    pulled = set(up.person_id) | set(V["tabs"][V["tabs"].tab == "upvotes"].person_id)
    U = up.assign(id=up.target_id.astype(str)).merge(L[["id", "day"]], on="id")
    U = U[(U.day >= TEST[0]) & (U.day <= TEST[1])].drop_duplicates(["person_id", "id"])
    c = U.groupby("person_id").size()
    return pd.Series({p: int(c.get(p, 0)) for p in pulled})


def part4(L, E, V, sl, curve_all):
    rng = np.random.default_rng(2)
    pool = set(V["persons"].person_id)
    S = discovery(V, sl)
    res = {"samples": {}}
    for k in ("maker_followers", "launch_commenters"):
        s = S[k]; x = np.array([p in pool for p in s], dtype=float)
        b = [rng.choice(x, len(x)).mean() for _ in range(BOOT)] if len(x) else [np.nan]
        res["samples"][k] = {"n": int(len(x)), "share_in_pool": round(float(x.mean()), 3) if len(x) else None,
                             "ci": np.nanpercentile(b, [2.5, 97.5]).round(3).tolist()}
    res["samples"]["commenter_ids_unmapped"] = S.get("commenter_ids_unmapped")
    # votes per person in the TEST window, same pull methods for pool and non-pool (people with a dated upvote pull)
    c = oct_votes(V, L); inp = c.index.isin(pool)
    def stats(x):
        x = np.asarray(x, float); v = x[x > 0]
        bm = [rng.choice(v, len(v)).mean() for _ in range(BOOT)] if len(v) else [np.nan]
        return {"pulled": int(len(x)), "voters": int(len(v)), "share_voting": round(float((x > 0).mean()), 3) if len(x) else None,
                "votes_per_voter": round(float(v.mean()), 2) if len(v) else None, "ci": np.nanpercentile(bm, [2.5, 97.5]).round(2).tolist(),
                "median": float(np.median(v)) if len(v) else None}
    res["test_votes_per_person"] = {"pool": stats(c[inp]), "non_pool": stats(c[~inp])}
    # the whole pool from the warehouse (page 1, 98.6% complete for the TEST window)
    T = E[(E.kind == "upvote") & (E.day >= TEST[0]) & (E.day <= TEST[1])].drop_duplicates(["person", "id"])
    pv = T.groupby("person").size()
    Lt = L[(L.day >= TEST[0]) & (L.day <= TEST[1])]
    Vtot, Vpool = float(Lt.votes.sum()), float(len(T))
    res["test_window_votes"] = {"real_votes": int(Vtot), "pool_votes": int(Vpool), "pool_voters": int(len(pv)),
                                "pool_votes_per_voter": round(float(pv.mean()), 2), "launches": int(len(Lt))}
    # total voters: (A) votes method N_out = (V - Vpool) / r_out; (B) Lincoln-Petersen on each sample: active pool
    # voters / share of the sample in the pool (samples are people, not voters: an upper-biased share -> N low)
    npv = c[~inp]; npv = npv[npv > 0].values.astype(float)
    est = {}
    if len(npv):
        bo = [(Vtot - Vpool) / rng.choice(npv, len(npv)).mean() for _ in range(BOOT)]
        est["votes_method_nonpool_voters"] = {"est": int((Vtot - Vpool) / npv.mean()), "ci": np.percentile(bo, [2.5, 97.5]).astype(int).tolist()}
        est["votes_method_total_voters"] = {"est": int(len(pv) + (Vtot - Vpool) / npv.mean()), "ci": (len(pv) + np.percentile(bo, [2.5, 97.5])).astype(int).tolist()}
    for k in ("maker_followers", "launch_commenters"):
        sh = res["samples"][k]; 
        if sh["share_in_pool"]:
            est[f"lincoln_petersen_{k}"] = {"accounts_like_pool": int(len(pool) / sh["share_in_pool"]),
                                            "ci": [int(len(pool) / max(sh["ci"][1], 1e-6)), int(len(pool) / max(sh["ci"][0], 1e-6))]}
    res["population"] = est
    # N for 80 / 90%: add non-pool voters most active first, with the non-pool votes-per-voter distribution
    # (assumption: the pulled non-pool sample's distribution stands for all non-pool voters, and the most active can be
    # found first); pool kept whole
    if len(npv):
        out = {}
        for tgt in (0.8, 0.9):
            need = tgt * Vtot - Vpool
            def n_needed(v):
                v = np.sort(v)[::-1]; Nout = (Vtot - Vpool) / v.mean()
                cum = np.cumsum(v) / v.sum() * (Vtot - Vpool)
                i = np.searchsorted(cum, need)
                return (i + 1) / len(v) * Nout if i < len(v) else np.nan
            b = [n_needed(rng.choice(npv, len(npv))) for _ in range(BOOT)]
            n0 = n_needed(npv)
            out[str(tgt)] = {"non_pool_voters_to_add": int(n0), "ci": np.nanpercentile(b, [2.5, 97.5]).astype(int).tolist(),
                             "pool_total": int(len(pool) + n0)}
        res["N_for_target"] = out
    # profile of non-pool votes (pulled non-pool sample): share of their TEST votes cast by people with 1 / 2-3 / 4+ votes
    if len(npv):
        tot = npv.sum()
        res["non_pool_profile"] = {"votes_by_1_vote_people": round(float(npv[npv == 1].sum() / tot), 3),
                                   "votes_by_2_3": round(float(npv[(npv >= 2) & (npv <= 3)].sum() / tot), 3),
                                   "votes_by_4_plus": round(float(npv[npv >= 4].sum() / tot), 3),
                                   "share_of_pulled_non_pool_with_0_votes": res["test_votes_per_person"]["non_pool"]["share_voting"]}
    return res


def main():
    L, E, Pp = frames()
    res = {"test_window": TEST, "rank_window": RANK, "pool_people": int(len(Pp)), "people_with_events": int(E.person.nunique())}
    res["by_month"], A = by_month(L, E)
    res["curve_activity"] = curve(L, E, "activity")
    res["curve_turnout"] = curve(L, E, "turnout")
    V = v3(); sl = salt()
    res["completeness"] = completeness(L, E, V, sl)
    res["part4"] = part4(L, E, V, sl, res["curve_activity"])
    json.dump(res, open(OUT, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
