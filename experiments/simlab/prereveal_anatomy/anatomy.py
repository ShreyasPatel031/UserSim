"""Error anatomy of the before-reveal (03:45 PT) forecast, top 10. Replay of the published method (hybrid_vm: hidden top 5 from the recorder's
rank_now, slots 6+ by a ridge on z(log hidden position), z(movement since 01:00), z(log1p comments), z(00:05 prior); weights leave-one-day-out),
on every day with a recorder file and a final board. Inputs read at <= 03:45 PT (+90 s); the 03:00 read is used where no 03:45 read exists
(flagged), as the live writer did until Nov 15. Votes after 04:00 and final ranks are used only to classify misses, never as features."""
import json, glob, os, sys, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP = sys.argv[1]; P = f"{SP}/pra"; OUT = f"{P}/out"
TD = json.load(open(f"{P}/truth_daily.json"))["days"]
A = pd.read_parquet(f"{SP}/fcv/arm2_oos.parquet"); A["id"] = A.id.astype(str); a2 = dict(zip(A.id, A.pred))
X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "hist_hunter_top5", "hist_hunter_n", "ph_n_makers"]); X["id"] = X.id.astype(str); X = X.drop_duplicates("id").set_index("id")
RING = pd.read_parquet(f"{SP}/ring/ph_discounted_likely.parquet"); ringp = set(RING[RING.ph_discounted_likely].person_id)
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); E = E[E.kind == "upvote"]; E["target_id"] = E.target_id.astype(str)
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
rows, info = [], {}
for f in sorted(glob.glob(f"{P}/vs/*.jsonl")):
    d = os.path.basename(f)[:10]
    if d not in TD: info[d] = "no final board yet"; continue
    V = pd.DataFrame([json.loads(l) for l in open(f) if l.strip()]); V["id"] = V.launch_id.astype(str); V["a"] = pd.to_datetime(V["at"], utc=True)
    V = V.drop_duplicates(["id", "a"]); V["rank_now"] = pd.to_numeric(V.rank_now, errors="coerce"); V["votes"] = pd.to_numeric(V.votes, errors="coerce"); V["comments"] = pd.to_numeric(V.comments, errors="coerce")
    pt = lambda hm: pd.Timestamp(f"{d} {hm}", tz="America/Los_Angeles").tz_convert("UTC"); t0 = pt("00:00")
    def read(hm, need_rank=True):
        T = pt(hm); s = V[(V.a <= T + pd.Timedelta(seconds=90)) & (V.a >= T - pd.Timedelta(minutes=65)) & (V.a >= t0 - pd.Timedelta(minutes=5))]
        if need_rank: s = s[s.rank_now.notna()]
        return s.sort_values("a").groupby("id").last() if len(s) else None
    r345 = read("03:45"); src = "03:45 read"
    if r345 is None or (r345.index.size and (pt("03:45") - r345.a.max()) > pd.Timedelta(minutes=20)): r345 = read("03:00"); src = "03:00 read (no 03:45 read)"
    if r345 is None: info[d] = "no pre-reveal read"; continue
    r100 = read("01:00"); r245 = read("02:45"); ids = list(r345.index)
    fr = {str(k): int(v) for k, v in TD[d]["ranks"].items()}; ids = [i for i in ids if i in fr]
    if len(ids) < 10: info[d] = "too few ranked"; continue
    pos = r345.rank_now.reindex(ids).rank(method="first"); pos1 = (r100.rank_now.reindex(ids).fillna(999) if r100 is not None else pd.Series(999, index=ids)).rank(method="first")
    c345 = r345.comments.reindex(ids).fillna(0); c245 = (r245.comments.reindex(ids).fillna(0) if r245 is not None else c345 * 0)
    fc = f"{P}/fc/forecast_{d}.parquet"; prior = {}
    if os.path.exists(fc):
        F = pd.read_parquet(fc); prior = dict(zip(F.id.astype(str), F.pred)); psrc = "00:05 forecast parquet"
    else: psrc = "arm-2 month-forward stand-in"
    pr = pd.Series({i: prior.get(i, a2.get(i, np.nan)) for i in ids}); pr = pr.fillna(pr.min() - 0.1 if pr.notna().any() else 0)
    vt = {}
    for hm in ("04:00", "05:00", "06:00"):
        s = V[(V.a >= pt(hm)) & (V.a <= pt(hm) + pd.Timedelta(minutes=40)) & V.votes.notna()]
        vt[hm] = s.sort_values("a").groupby("id").votes.first().reindex(ids) if len(s) else pd.Series(np.nan, index=ids)
    cm = f"{P}/cm/{d}.jsonl"; mshare = {}
    if os.path.exists(cm):
        C = pd.DataFrame([json.loads(l) for l in open(cm) if l.strip()]); C["t"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); C = C[(C.t <= pt("03:45")) & (C.t >= t0 - pd.Timedelta(hours=1))]
        C = C.drop_duplicates("comment_id"); C["lid"] = C.launch_id.astype(str)
        for lid, g in C.groupby("lid"): mshare[lid] = float((g.is_maker == True).mean()) if len(g) else np.nan
    for i in ids:
        held = E[E.target_id == i].person_id
        rows.append({"day": d, "id": i, "name": r345.name.get(i) if "name" in r345 else "", "final": fr[i], "read": src, "prior_src": psrc, "n_day": len(ids),
                     "pos": pos[i], "lpos": np.log(pos[i]), "pos_0100": pos1[i], "move": np.log(pos1[i]) - np.log(pos[i]), "comments": c345[i], "nc_rec": np.log1p(c345[i]),
                     "comment_vel_1h": c345[i] - c245[i], "clean": pr[i], "maker_comment_share": mshare.get(i, np.nan),
                     "hunter_top5": X.hist_hunter_top5.get(i, np.nan) if i in X.index else np.nan, "hunter_n": X.hist_hunter_n.get(i, np.nan) if i in X.index else np.nan,
                     "votes_0400": vt["04:00"][i], "votes_0500": vt["05:00"][i], "votes_0600": vt["06:00"][i],
                     "held_voters": int(len(held)), "ring_share_held": float(held.isin(ringp).mean()) if len(held) else np.nan})
    info[d] = {"launches": len(ids), "read": src, "prior": psrc}
D = pd.DataFrame(rows)
for c in ["lpos", "move", "nc_rec", "clean"]: D["z_" + c] = D.groupby("day")[c].transform(zf)
D["y"] = D.groupby("day").final.transform(lambda s: zf(-np.log(s))); D["r_clean"] = D.groupby("day").clean.rank(ascending=False, method="first")
FE = ["z_lpos", "z_move", "z_nc_rec", "z_clean"]
def order(g, score):
    h = g.sort_values("pos"); top = list(h.id[:5]); rest = g[~g.id.isin(top)].assign(s=score[~g.id.isin(top)]).sort_values("s", ascending=False); return top + list(rest.id)
days = sorted(D.day.unique()); ORD = {}
for d in days:
    tr = D[D.day != d]; m = Ridge(alpha=1.0).fit(tr[FE], tr.y); g = D[D.day == d]; ORD[d] = order(g, pd.Series(m.predict(g[FE]), index=g.index))
D["pred_rank"] = 0
for d in days:
    rk = {i: k + 1 for k, i in enumerate(ORD[d])}; D.loc[D.day == d, "pred_rank"] = D[D.day == d].id.map(rk)
for hm in ("0400", "0500", "0600"): D[f"vrank_{hm}"] = D.groupby("day")[f"votes_{hm}"].rank(ascending=False, method="first")
D.to_parquet(f"{OUT}/launch_rows.parquet"); json.dump(info, open(f"{OUT}/days.json", "w"), indent=1)
hit = lambda d, k: len(set(ORD[d][:k]) & set(D[(D.day == d) & (D.final <= k)].id)) / k
print("days", len(days), {k: round(100 * np.mean([hit(d, k) for d in days]), 1) for k in (3, 5, 10)})
print(pd.Series({d: v if isinstance(v, str) else v["read"] + " | " + v["prior"] for d, v in info.items()}).to_string())
