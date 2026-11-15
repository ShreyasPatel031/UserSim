"""Per-launch calibration of CF scores (PREREG_cf_launch_calibration.md). Arms CF / ASSIGN-EXP / ASSIGN-30D on the frozen CF-only lists,
strict scoring as backer_arms_score.py (observed voters = held before the freeze AND re-read after close; ranked within re-read people),
pooled recall at observed N and at realistic N-hat, DAY bootstrap, paired vs CF.
    python cf_launch_calib.py <store dir> <scratchpad> <day> ...   -> <SP>/cfcal/cf_launch_calib.json"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.isotonic import IsotonicRegression
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import period_parts as PP
from pipeline import warehouse  # noqa: E402
ST, SP, DAYS = sys.argv[1], sys.argv[2], sys.argv[3:]; rng = np.random.default_rng(0)
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
held = set(pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id"]).person_id)
last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
U["lday"] = U.target_id.map(dict(zip(W.id, W.day)))
DATA = {}
for D in DAYS:
    lp = os.path.join(SP, "bp", f"backer_arms_{D}.parquet"); lp = lp if os.path.exists(lp) else os.path.join(SP, "bp", f"_arms_{D}.parquet")
    if not os.path.exists(lp): continue
    F = pd.read_parquet(lp); F = F[F.arm == "CF-only"][["launch_id", "person_id", "p"]].assign(launch_id=lambda x: x.launch_id.astype(str))
    close = PP.close_utc(D); st = close - pd.Timedelta(days=1)
    reread = set(last_read[last_read > close].index) & held; hf = set(first_read[first_read < st].index) & held; ok = reread & hf
    obs = U[(U.lday == D) & U.person_id.isin(ok)].groupby("target_id").person_id.agg(set).to_dict()
    F["y"] = [p_ in obs.get(l, ()) for l, p_ in zip(F.launch_id, F.person_id)]; F["ok"] = F.person_id.isin(ok)
    d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    r30 = U[(U.lday < D) & (U.lday >= d30) & (U.ft < st)].groupby("person_id").size() / 30.0
    DATA[D] = {"F": F, "obs": obs, "ok": ok, "r30": r30}
print("days", list(DATA), flush=True)


def lists(D, iso, c):
    F = DATA[D]["F"].copy(); F["pc"] = iso.predict(F.p)
    st_ = F.groupby("person_id").p.agg(["mean", "std", "size"]); F = F.join(st_, on="person_id")
    F["z"] = np.where(F["size"] > 1, (F.p - F["mean"]) / (F["std"].fillna(0) + 1e-9), 0.0)
    b_exp = F.groupby("person_id").pc.sum().round().clip(lower=1).astype(int)
    b_30 = DATA[D]["r30"].reindex(F.person_id.unique()).fillna(0).round().clip(lower=1).astype(int)
    out = {"CF": {}, "ASSIGN-EXP": {}, "ASSIGN-30D": {}}
    F = F.sort_values(["person_id", "z"], ascending=[True, False]); F["zrank"] = F.groupby("person_id").cumcount() + 1
    for arm, b in (("ASSIGN-EXP", b_exp), ("ASSIGN-30D", b_30)):
        F[arm] = F.zrank <= F.person_id.map(b).values
    for lid, g in F[F.ok].groupby("launch_id"):
        g = g.sort_values("p", ascending=False); out["CF"][lid] = list(g.person_id)
        for arm in ("ASSIGN-EXP", "ASSIGN-30D"): out[arm][lid] = list(g[g[arm]].person_id) + list(g[~g[arm]].person_id)
    nhat = (F[F.ok].groupby("launch_id").pc.sum() * c).round().astype(int).to_dict()
    return out, nhat


rows = []
for D in DATA:
    oth = [x for x in DATA if x != D]
    if not oth: continue
    Fo = pd.concat([DATA[x]["F"][DATA[x]["F"].ok] for x in oth]); iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(Fo.p, Fo.y)
    c = sum(len(v) for x in oth for v in DATA[x]["obs"].values()) / max(1e-9, iso.predict(Fo.p).sum())
    L, nhat = lists(D, iso, c)
    for lid in L["CF"]:
        o = DATA[D]["obs"].get(lid, set()); n = len(o); nh = max(1, nhat.get(lid, 1))
        if not n: continue
        r = {"day": D, "N": n, "Nhat": nh}
        for arm in L: r[arm] = len(set(L[arm][lid][:n]) & o); r[arm + "@Nhat"] = len(set(L[arm][lid][:nh]) & o)
        rows.append(r)
P = pd.DataFrame(rows)
def boot(f):
    days = P.day.unique(); g = {d: P[P.day == d] for d in days}
    v = [f(pd.concat([g[d] for d in rng.choice(days, len(days))])) for _ in range(2000)]
    return [round(float(np.percentile(v, 2.5)), 2), round(float(np.percentile(v, 97.5)), 2)]
rec = lambda df, a: 100 * df[a].sum() / df.N.sum(); pre = lambda df, a: 100 * df[a + "@Nhat"].sum() / df.Nhat.sum(); recn = lambda df, a: 100 * df[a + "@Nhat"].sum() / df.N.sum()
out = {"design": open(os.path.join(HERE, "results_reports", "PREREG_cf_launch_calibration.md")).read()[:300], "days": sorted(P.day.unique()), "launches": int(len(P)),
       "observed_voters": int(P.N.sum()), "Nhat_total": int(P.Nhat.sum()), "per_day_observed": P.groupby("day").N.sum().to_dict()}
for a in ("CF", "ASSIGN-EXP", "ASSIGN-30D"):
    out[a] = {"recall@N": [round(rec(P, a), 2)] + boot(lambda x, a=a: rec(x, a)), "recall@Nhat": [round(recn(P, a), 2)] + boot(lambda x, a=a: recn(x, a)),
              "precision@Nhat": [round(pre(P, a), 2)] + boot(lambda x, a=a: pre(x, a))}
for a in ("ASSIGN-EXP", "ASSIGN-30D"):
    out[f"{a} minus CF (paired)"] = {"recall@N": [round(rec(P, a) - rec(P, "CF"), 2)] + boot(lambda x, a=a: rec(x, a) - rec(x, "CF")),
                                     "recall@Nhat": [round(recn(P, a) - recn(P, "CF"), 2)] + boot(lambda x, a=a: recn(x, a) - recn(x, "CF")),
                                     "per_day recall@N": {d: round(rec(g, a) - rec(g, "CF"), 2) for d, g in P.groupby("day")}}
    out[f"{a} adopt (pre-registered: recall@N lower bound > 0)"] = out[f"{a} minus CF (paired)"]["recall@N"][1] > 0
os.makedirs(f"{SP}/cfcal", exist_ok=True); json.dump(out, open(f"{SP}/cfcal/cf_launch_calib.json", "w"), indent=1, default=float); print(json.dumps(out, indent=1, default=float))
