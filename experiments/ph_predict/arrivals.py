"""it10 ARRIVALS population (orchestrator Nov 11; pre-registered with E5). Candidate rows per day d: complete people x
launches on d where the person is tied to L's team by information provable at 00:05 PT:
  (a) follows a real maker or the hunter: warehouse follows observed 2026-10-26, used for d >= Oct 27 only
  (b) engaged (upvote / comment) with an earlier launch by a real maker of L or by L's hunter (events dated < d)
  (c) was a one-vote-that-day voter on an earlier launch by the same real maker / hunter (<= d-2)
Real makers = items.makers without placeholders (simlab.handles.clean_handles). Persons are salted ids; handles of
makers are hashed with the population salt only to match follow edges (never printed).
Row features (person): tie_mk (log count), tie_hu, tie_days (days since last engagement with the team), fol_mk, fol_hu,
past_arr (log count of past one-vote arrivals for the team), act_30 (active days in the prior 30), days_since, tenure,
log_act_all. Team (launch): n_makers_real, team_prev (team's earlier launches), team_arr_mean (mean one-vote arrivals per
earlier team launch), cand_n (|C(L)|), lineup_n. Label y = upvote on L dated d (label filter applied as in it8).
usage: SIMBT=<dir> python arrivals.py build <from> <to>   -> <SIMBT>/arrivals/<d>.parquet
       SIMBT=<dir> python arrivals.py fit                 -> monthly honest fits, EV per launch -> <SIMBT>/arrivals/ev.parquet"""
import glob, hashlib, json, os, subprocess, sys
from collections import defaultdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(HERE); sys.path.insert(0, EXP); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]; OUT = os.path.join(WORK, "arrivals"); os.makedirs(OUT, exist_ok=True)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
PF = ["tie_mk", "tie_hu", "tie_days", "fol_mk", "fol_hu", "past_arr", "act_30", "days_since", "tenure", "log_act_all"]
TF = ["n_makers_real", "team_prev", "team_arr_mean", "cand_n", "lineup_n"]


def prep():
    from simlab.handles import clean_handles
    I = pd.read_parquet(f"{WORK}/items.parquet"); I["id"] = I.id.astype(str)
    mk = {r.id: clean_handles(json.loads(r.makers or "[]")) for r in I.itertuples()}
    hu = {r.id: (r.poster if r.poster and not str(r.poster).startswith("[") else None) for r in I.itertuples()}
    day = dict(zip(I.id, I.day))
    E = pd.read_parquet(f"{WORK}/events_cp.parquet"); E["item"] = E.item.astype(str); E = E[E.item.isin(day)]
    E["date"] = E.date.astype(str).str[:10]
    up = E[E.kind == "upvote"]
    nday = up.groupby(["person", "date"]).item.transform("size")
    up = up.assign(one=(nday == 1))
    return I, mk, hu, day, E, up


def follows():
    from pipeline import warehouse as W
    sl = subprocess.run(["gsutil", "cat", f"{B}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()
    F = W.query("SELECT lower(person) AS p, lower(followee) AS f FROM follows WHERE observed_on = '2026-10-26'", do_sync=False)
    F["pid"] = ["p_" + hashlib.sha256((sl + "producthunt:" + u).encode()).hexdigest()[:16] for u in F.p]
    return F.groupby("pid").f.apply(set).to_dict()


def build(d0, d1):
    import two_level as T
    ok, _ = T._label_maps()
    I, mk, hu, day, E, up = prep()
    fol = follows(); FOL_FROM = "2026-10-27"
    # team -> launches (by maker / hunter), per person engagement history with dates
    eng = E.sort_values("date")[["person", "item", "date"]].values
    first = E.groupby("person").date.min().to_dict()
    adates = E[["person", "date"]].drop_duplicates()
    for d in pd.date_range(d0, d1).strftime("%Y-%m-%d"):
        lineup = I[I.day == d].id.tolist()
        if not lineup:
            continue
        past = E[E.date < d]; past_up = up[up.date <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")]
        # person -> maker -> (count, last date); person -> hunter -> count; person -> team member -> one-vote arrivals
        cm, ch, last, arr = defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int)), {}, defaultdict(lambda: defaultdict(int))
        for p, it, dt in past[["person", "item", "date"]].itertuples(index=False):
            for m in mk.get(it, ()):
                cm[p][m] += 1; k = (p, m); last[k] = max(last.get(k, ""), dt)
            h = hu.get(it)
            if h:
                ch[p][h] += 1; k = (p, "h:" + h); last[k] = max(last.get(k, ""), dt)
        for p, it in past_up[past_up.one][["person", "item"]].itertuples(index=False):
            for m in mk.get(it, ()) | ({hu[it]} if hu.get(it) else set()):
                arr[p][m] += 1
        # team-level history (launches before d)
        prev = I[I.day < d]; team_prev, team_arr = {}, {}
        one_votes = past_up[past_up.one].groupby("item").size().to_dict()
        by_member = defaultdict(list)
        for r in prev.itertuples():
            for m in mk.get(r.id, ()) | ({hu[r.id]} if hu.get(r.id) else set()):
                by_member[m].append(r.id)
        act = adates[adates.date < d]
        cut30 = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        a30 = act[act.date >= cut30].groupby("person").size().to_dict(); alll = act.groupby("person").size().to_dict()
        lastact = act.groupby("person").date.max().to_dict()
        rows = []
        for L in lineup:
            team = mk.get(L, set()); h = hu.get(L); members = team | ({h} if h else set())
            tl = sorted({x for m in members for x in by_member.get(m, [])})
            tp = len(tl); ta = float(np.mean([one_votes.get(x, 0) for x in tl])) if tl else 0.0
            cands = set()
            for p in cm.keys() | ch.keys() | arr.keys() | (fol.keys() if d >= FOL_FROM else set()):
                if (any(cm[p].get(m, 0) for m in team) or (h and ch[p].get(h, 0)) or any(arr[p].get(m, 0) for m in members)
                        or (d >= FOL_FROM and (fol.get(p, set()) & {x.lower() for x in members}))):
                    cands.add(p)
            for p in cands:
                lt = [last.get((p, m), "") for m in team] + ([last.get((p, "h:" + h), "")] if h else [])
                lt = max([x for x in lt if x], default="")
                fl = fol.get(p, set()) if d >= FOL_FROM else set()
                rows.append({"person": p, "id": L, "tie_mk": np.log1p(sum(cm[p].get(m, 0) for m in team)),
                             "tie_hu": np.log1p(ch[p].get(h, 0)) if h else 0.0,
                             "tie_days": float((pd.Timestamp(d) - pd.Timestamp(lt)).days) if lt else 999.0,
                             "fol_mk": float(bool(fl & {m.lower() for m in team})), "fol_hu": float(bool(h and h.lower() in fl)),
                             "past_arr": np.log1p(sum(arr[p].get(m, 0) for m in members)), "act_30": float(a30.get(p, 0)),
                             "days_since": float((pd.Timestamp(d) - pd.Timestamp(lastact[p])).days) if p in lastact else 999.0,
                             "tenure": float((pd.Timestamp(d) - pd.Timestamp(first[p])).days) if p in first else 0.0,
                             "log_act_all": np.log1p(alll.get(p, 0)), "n_makers_real": float(len(team)), "team_prev": float(tp),
                             "team_arr_mean": ta, "cand_n": float(len(cands)), "lineup_n": float(len(lineup))})
        if not rows:
            continue
        R = pd.DataFrame(rows)
        lab = up[(up.date == d) & up.item.isin(lineup)]; pos = set(zip(lab.person, lab.item))
        R["y"] = [int((p, x) in pos) for p, x in zip(R.person, R.id)]
        R["lab_ok"] = ok(R.person, d)
        R["day"] = d
        R.to_parquet(f"{OUT}/{d}.parquet")
        print(json.dumps({"day": d, "rows": len(R), "candidates": int(R.person.nunique()), "launches": int(R.id.nunique()),
                          "pos": int(R.y.sum()), "dormant_30": int((R.act_30 == 0).sum()), "fol_rows": int((R.fol_mk + R.fol_hu > 0).sum())}), flush=True)


SELECTED = {d.strftime("%Y-%m-%d") for d in pd.date_range("2026-10-29", "2026-11-04")}


def fit_score():
    """Honest monthly fits of P_arr (Sep candidate rows -> Oct days, Oct -> Nov), label-filtered rows only. EV per launch
    = arrivals EV (+/- dormant-30 rows, E5 fix 1) + browsers EV (it9b product-only rows, persons x launches NOT in C(L)).
    No herding step in the ranking (E5 fix 2: monotone, cannot change the order). Scored on the it8 days vs it8 full
    (cp_choice2) and the deployed sim, plus the share of complete-people votes that come from C(L)."""
    import lightgbm as lgb
    from scipy.stats import spearmanr
    from pipeline import warehouse as W
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank, votes FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank)); vt = dict(zip(L.id, L.votes))
    dep = {}
    for f in glob.glob(f"{WORK}/scores_retrain/wh_*.parquet"):
        S = pd.read_parquet(f); dep.update({(r.day, str(r.id)): r.psn_ev for r in S.itertuples()})
    files = {os.path.basename(f)[:10]: f for f in glob.glob(f"{OUT}/20*.parquet")}
    test = sorted(d for d in files if "2026-10-20" <= d <= "2026-11-08")
    import two_level as TL
    T_ok, _ = TL._label_maps()
    cols = PF + TF; rng = np.random.default_rng(0); res = {"variants": {}}
    ev_rows = []
    for variant in ("no_dormant", "with_dormant"):
        models = {}
        for mon in sorted({d[:7] for d in test}):
            prev = (pd.Timestamp(mon + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
            T = pd.concat([pd.read_parquet(files[d]) for d in sorted(files) if d[:7] == prev])
            T = T[T.lab_ok]
            if variant == "no_dormant":
                T = T[T.act_30 > 0]
            else:
                T = T[(T.act_30 > 0) | ~T.day.isin(SELECTED)]
            models[mon] = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=50, verbose=-1, n_jobs=4).fit(T[cols], T.y)
        per = []
        for d in test:
            A = pd.read_parquet(files[d])
            if variant == "no_dormant" or d in SELECTED:
                A = A[A.act_30 > 0]
            A["p"] = models[d[:7]].predict_proba(A[cols])[:, 1]
            arr = A.groupby("id").p.sum()
            Bp = f"{WORK}/rows_tl_cp_attr_noctx/{d}.parquet"
            Bw = pd.read_parquet(Bp, columns=["person", "id", "w", "p", "y"]); Bw["id"] = Bw.id.astype(str)
            cand = set(zip(A.person, A.id))
            Bw = Bw[[(p, x) not in cand for p, x in zip(Bw.person, Bw.id)]]
            brw = Bw.assign(e=Bw.w * Bw.p).groupby("id").e.sum()
            ids = sorted(set(arr.index) | set(brw.index))
            G = pd.DataFrame({"id": ids}); G["arr"] = G.id.map(arr).fillna(0); G["brw"] = G.id.map(brw).fillna(0)
            G["ev"] = G.arr + G.brw; G["rank"] = G.id.map(rk); G["votes"] = G.id.map(vt); G["dep"] = [dep.get((d, x)) for x in G.id]
            G["cand_n"] = G.id.map(A.groupby("id").cand_n.first()); G["day"] = d; G["variant"] = variant
            ev_rows.append(G.copy())
            G = G.dropna(subset=["rank"])
            row = {"day": d, "selected": d in SELECTED}
            for k in (3, 5, 10):
                top = set(G[G["rank"] <= k].id)
                for m in ("ev", "arr", "brw", "dep"):
                    g = G.dropna(subset=[m]) if m == "dep" else G
                    row[f"{m}_top{k}"] = len(set(g.nlargest(k, m).id) & top) / k * 100 if len(top) >= k and len(g) >= k else np.nan
            for m in ("ev", "arr", "brw"):
                row[f"sp_{m}"] = spearmanr(G[m], G.votes).correlation
            lab = A[A.lab_ok]; okb = T_ok(Bw.person, d)
            cv, bv = float(lab.y.sum()), float(Bw[okb].y.sum())
            row["cand_vote_share"] = cv / max(1.0, cv + bv)
            per.append(row)
        P = pd.DataFrame(per)
        def b(x):
            x = np.asarray(x, float); x = x[~np.isnan(x)]
            bs = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(5000)]
            return [round(float(x.mean()), 1 if abs(x.mean()) > 1.5 else 3), [round(float(v), 1 if abs(x.mean()) > 1.5 else 3) for v in np.percentile(bs, [2.5, 97.5])], int(len(x))]
        r = {}
        for sub, m in (("all", P.day.notna()), ("clean", ~P.selected), ("oct", P.day < "2026-11-01"), ("nov", P.day >= "2026-11-01")):
            Q = P[m]
            r[sub] = {f"top{k}": {x: b(Q[f"{x}_top{k}"]) for x in ("ev", "arr", "brw", "dep")} for k in (3, 5, 10)}
            r[sub]["spearman"] = {x: b(Q[f"sp_{x}"]) for x in ("ev", "arr", "brw")}
            r[sub]["candidate_share_of_sample_votes"] = b(Q.cand_vote_share)
        r["per_day"] = P.round(3).to_dict("records")
        res["variants"][variant] = r
    json.dump(res, open(os.path.join(HERE, "results", "arrivals.json"), "w"), indent=1, default=float)
    pd.concat(ev_rows).to_parquet(f"{OUT}/ev_per_launch.parquet")
    print("saved", len(ev_rows))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "fit":
        fit_score()
