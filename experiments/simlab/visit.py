"""Does knowing WHEN a person visits, and what the page looked like then, fix the "popular picks" misses?
Product Hunt shows no upvote times, so the visit time is the person's first comment that day (commenting person-days only).
"What they saw" is approximated by each launch's comment count at that moment (others' comments only), the closest
public trace of the homepage order then. Compared with a fixed early read (others' comments in the first 3 h).
Model as in seq.py (v2 baseline + personas + collaborative filtering + sequence signals); trained on Sep, scored on Oct,
both restricted to person-days with a visit time.
usage: SIMLAB_DATA=data_v2 python -m simlab.visit -> simlab/reports/visit.json"""
import json, os, sys
NONE = None
import numpy as np, pandas as pd
from . import store, choice
from .seq import features
from .v2_compare import PERS, BASE, CF, fit
from .persona import CACHE

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ = ["seq_last10", "seq_decay", "seq_nn", "team_recent"]


def comments(I):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ph_predict"))
    import commenters as K
    sid = dict(zip(I.slug, I.id))
    rows = [(sid[s], c["username"], c["created"]) for s, v in K.load_comments().items() if s in sid
            for c in v["rows"] if c.get("username") and c.get("created")]
    C = pd.DataFrame(rows, columns=["id", "person", "t"])
    C["t"] = pd.to_datetime(C.t, utc=True, errors="coerce")
    return C.dropna()


def main():
    P, I, E = store.load()
    A = pd.read_parquet(f"{CACHE}/rows_v1.parquet", columns=["g"] + list(PERS)); keep = set(A.dropna(subset=list(PERS)).g)
    D = pd.read_parquet(f"{CACHE}/rows_v2.parquet"); D = D[D.g.isin(keep)].copy()
    for k in PERS:
        D[k] = D.groupby("g")[k].rank(pct=True)
    D = features(D, I, E)
    C = comments(I); C["t"] = C.t.dt.tz_localize(None)  # UTC, naive
    global NONE; NONE = np.array([], dtype="datetime64[ns]")
    feat = dict(zip(I.id, pd.to_datetime(I.day + "T00:01:00-07:00", utc=True)))  # launches go live 00:01 Pacific
    C["day"] = C.id.map(I.set_index("id").day)
    # comment times per launch, and each person's own, so counts can exclude the person
    by_launch = {i: np.sort(g.t.values) for i, g in C.groupby("id")}
    own = {k: np.sort(g.t.values) for k, g in C.groupby(["id", "person"])}

    def others_before(x, u, t):
        return int(np.searchsorted(by_launch.get(x, NONE), t)) - int(np.searchsorted(own.get((x, u), NONE), t))
    # visit time: the person's first comment that day (known only after the fact)
    first = C.groupby(["person", "day"]).t.min()
    start = {d: pd.Timestamp(d + "T00:01:00-07:00").tz_convert("UTC").tz_localize(None) for d in I.day.unique()}
    off = {(u, d): (t - start[d]).total_seconds() / 3600 for (u, d), t in first.items() if d in start}
    past = {}
    for (u, d), h in sorted(off.items(), key=lambda kv: kv[0][1]):
        past.setdefault(u, []).append((d, h))
    # usual visit time: median offset of the person's first comment on earlier days (knowable before the day)
    usual = {(u, d): float(np.median([h for d0, h in L if d0 < d][-20:])) for u, L in past.items() for d, _ in L
             if any(d0 < d for d0, _ in L)}
    for u, d in set(zip(D.person, D.day)):
        if (u, d) not in usual and u in past and any(d0 < d for d0, _ in past[u]):
            usual[(u, d)] = float(np.median([h for d0, h in past[u] if d0 < d][-20:]))
    D["visit_off"] = [off.get((u, d), np.nan) for u, d in zip(D.person, D.day)]
    D["usual_off"] = [usual.get((u, d), np.nan) for u, d in zip(D.person, D.day)]
    print("share of person-days with: actual visit", round(D.groupby("g").visit_off.first().notna().mean(), 3),
          "| usual visit", round(D.groupby("g").usual_off.first().notna().mean(), 3), flush=True)
    st = np.array([np.datetime64(start[d]) for d in D.day])
    def at(offsets):
        return [others_before(x, u, s0 + np.timedelta64(int(h * 3600), "s")) if h == h else 0
                for x, u, s0, h in zip(D.id.values, D.person.values, st, offsets)]
    D["early3h"] = np.log1p(at(np.full(len(D), 3.0)))
    D["seen_at_visit"] = np.log1p(at(D.visit_off.values))
    D["seen_at_usual"] = np.log1p(at(D.usual_off.values))
    for c in ("early3h", "seen_at_visit", "seen_at_usual"):
        D[c + "_r"] = D.groupby("g")[c].rank(pct=True)
    base = BASE + list(PERS) + CF + SEQ
    E3 = ["early3h", "early3h_r"]; SU = ["seen_at_usual", "seen_at_usual_r", "usual_off"]; SV = ["seen_at_visit", "seen_at_visit_r", "visit_off"]
    groups = {"all person-days": D,
              "usual visit time known": D[D.usual_off.notna()],
              "commented that day (actual visit, not knowable ahead)": D[D.visit_off.notna()]}
    tests = {"all person-days": [("+ early read 3 h", E3)],
             "usual visit time known": [("+ early read 3 h", E3), ("+ page at usual visit time", SU), ("+ both", E3 + SU)],
             "commented that day (actual visit, not knowable ahead)": [("+ early read 3 h", E3), ("+ page at actual visit", SV), ("+ both", E3 + SV)]}
    rng = np.random.default_rng(0); res = {}
    for gname, G in groups.items():
        tr, te = G[G.day < "2026-10-01"], G[G.day >= "2026-10-01"].copy(); te = te[te.g.isin(te[te.y == 1].g)]
        for fol in (False, True):
            F = ["follow"] if fol else []
            H = {}
            for name, extra in [("baseline", [])] + tests[gname]:
                t = te.assign(p=fit(tr, te, base + extra + F)); t["r"] = t.groupby("g").p.rank(ascending=False, method="first")
                H[name] = t[t.r <= 3].groupby("g").y.max().reindex(t.g.unique(), fill_value=0)
                h, au = choice.person_metrics(te, t.p.values)
                d = (H[name] - H["baseline"]).values
                ci = np.percentile([d[rng.integers(0, len(d), len(d))].mean() for _ in range(500)], [2.5, 97.5]) * 100
                key = f"{gname} | {'follows' if fol else 'no follows'} | {name}"
                res[key] = {"person_days": int(te.g.nunique()), "top3_hit": round(float(h), 3), "auc": round(float(au), 3),
                            "gain_pts": round(float(100 * d.mean()), 1), "ci95": [round(float(x), 1) for x in ci]}
                print(key, res[key], flush=True)
    json.dump(res, open(f"{HERE}/reports/visit.json", "w"), indent=1)


if __name__ == "__main__":
    main()
