"""WHO half of the cohort scorecard, backtest over every day with frozen predictions (PREREG.md). Aggregates only.
    python cohort_who.py <store dir> <scratchpad> <out json> <day> [<day> ...]"""
import io, json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import period_parts as PP
from pipeline import warehouse
ST, SP, OUT = sys.argv[1:4]; DAYS = sys.argv[4:]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
P = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "complete", "ph_user_id"]).drop_duplicates("person_id")
COMPLETE = set(P[P.complete == True].person_id); BYUID = dict(zip(P.ph_user_id.astype(str), P.person_id))
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id", "fetched_at"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str); U["ft"] = pd.to_datetime(U.fetched_at, utc=True)
last_read = U.groupby("person_id").ft.max(); first_read = U.groupby("person_id").ft.min()
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
LDAY = dict(zip(W.id, W.day)); VOTES = dict(zip(W.id, pd.to_numeric(W.votes, errors="coerce"))); RANK = dict(zip(W.id, pd.to_numeric(W.daily_rank, errors="coerce")))
TOPS = {i: (json.loads(t) if isinstance(t, str) and t.startswith("[") else []) for i, t in zip(W.id, W.topics)}
U["lday"] = U.target_id.map(LDAY)
CUTS = sorted(x.split("/")[-1][:10] for x in subprocess.run(["gsutil", "ls", f"{B}/tmp/e5/private/segments/"], capture_output=True, text=True).stdout.split() if x.endswith(".parquet") and "latest" not in x)
_cut = {}
def seg(D):
    c = max([x for x in CUTS if x <= D] or [CUTS[0]])
    if c not in _cut: _cut[c] = pd.read_parquet(io.BytesIO(gcat(f"{B}/tmp/e5/private/segments/{c}.parquet"))).set_index("person_id").group.to_dict()
    return c, _cut[c]
def jsd(p, q):
    keys = sorted(set(p) | set(q)); a = np.array([p.get(k, 0.0) for k in keys], float); b = np.array([q.get(k, 0.0) for k in keys], float)
    a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2
    kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0))
    return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
def mix(series):
    s = pd.Series(series).value_counts(normalize=True); return s.to_dict()
def family(t):
    t = " ".join(t).lower()
    for f, ks in (("developer", ("developer", "github", "open source", "api", "software engineering", "no-code", "vibe coding")), ("marketing/sales", ("marketing", "sales", "seo", "social media", "advertising")),
                  ("design/creative", ("design", "video", "photo", "music", "art")), ("productivity/business", ("productivity", "saas", "finance", "business", "email", "calendar"))):
        if any(k in t for k in ks): return f
    return "AI/other"

rows, comm_rows, day_cov = [], [], {}
for D in DAYS:
    cut, G = seg(D); close = PP.close_utc(D); flag = "groups fit after the day" if cut > D else "ok"
    ids = [i for i, d in LDAY.items() if d == D]
    # truth: complete held people re-read after close whose upvotes include the launch
    T = U[(U.lday == D) & U.person_id.isin(COMPLETE)]; T = T[T.person_id.map(last_read) > close]
    # base: group share of held upvotes in the 30 days before D (active people)
    H = U[(U.lday < D) & (U.lday >= (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"))]
    base = mix(H.person_id.map(G).dropna())
    # P1: frozen explain groups_expected
    ex = json.loads(gcat(f"{B}/results/web/explain/{D}.json") or b"{}").get("launches", {})
    ex = ex if isinstance(ex, dict) else {str(r.get("id")): r for r in ex}
    # P2: frozen CF list p summed by group
    bp = gcat(f"{B}/tmp/e5/private/backer_pred/{D}.parquet"); BP = pd.read_parquet(io.BytesIO(bp)) if bp else None
    if BP is not None: BP["launch_id"] = BP.launch_id.astype(str); BP["g"] = BP.person_id.map(G)
    # commenters
    teams = {}
    for ln in gcat(f"{B}/raw/ph_at_launch/{D}/api_teams.jsonl").decode(errors="ignore").splitlines():
        try: r = json.loads(ln); teams.setdefault(str(r.get("post_id")), set()).add(str(r.get("maker_id")))
        except Exception: pass
    CM = {}
    lst = subprocess.run(["gsutil", "ls", f"{B}/raw/ph_at_launch/{D}/api_comments/"], capture_output=True, text=True).stdout.split()
    for f in lst:
        for ln in gcat(f).decode(errors="ignore").splitlines():
            try: r = json.loads(ln)
            except Exception: continue
            pid, uid = str(r.get("post_id")), str(r.get("commenter_user_id"))
            if uid in teams.get(pid, set()): continue
            CM.setdefault(pid, set()).add(uid)
    for lid in ids:
        tb = T[T.target_id == lid].person_id.unique(); g_real = [G[p] for p in tb if p in G]
        r = {"day": D, "launch_id": lid, "cut": cut, "flag": flag, "real_backers": len(tb), "real_backers_grouped": len(g_real), "ph_votes": (float(VOTES[lid]) if pd.notna(VOTES.get(lid)) else None),
             "coverage_backers": round(len(tb) / VOTES[lid], 3) if pd.notna(VOTES.get(lid)) and VOTES.get(lid) else None, "rank": (float(RANK[lid]) if pd.notna(RANK.get(lid)) else None), "family": family(TOPS.get(lid, [])),
             "new_share": round(float(np.mean([(close - first_read[p]).days <= 30 for p in tb])), 3) if len(tb) else None}
        if len(g_real) >= 20:
            real = mix(g_real); r["jsd_base"] = jsd(base, real)
            ge = ((ex.get(lid) or {}).get("who") or {}).get("groups_expected") or {}
            if isinstance(ge, dict) and ge.get("groups"):
                p1 = {g["group_id"]: g["share"] for g in ge["groups"] if g.get("share") is not None}
                if sum(p1.values()) > 0: r["jsd_p1"] = jsd(p1, real)
            if BP is not None:
                q = BP[(BP.launch_id == lid) & BP.g.notna()]
                if len(q): r["jsd_p2"] = jsd((q.groupby("g").p.sum() / q.p.sum()).to_dict(), real)
            r["real_top_group_share"] = round(max(real.values()), 3)
        rows.append(r)
        cu = CM.get(lid, set()); matched = [BYUID[u] for u in cu if u in BYUID]
        comm_rows.append({"day": D, "launch_id": lid, "nonteam_commenters": len(cu), "matched": len(matched), "groups": [G[p] for p in matched if p in G]})
    day_cov[D] = {"cut": cut, "flag": flag, "launches": len(ids), "base_mix": {str(k): round(v, 3) for k, v in base.items()}}

R = pd.DataFrame(rows)
def boot_days(df, col):
    df = df.dropna(subset=[col]); d = sorted(df.day.unique())
    if len(df) == 0: return None
    bs = [];
    for _ in range(2000):
        s = rng.choice(d, len(d)); bs.append(pd.concat([df[df.day == x] for x in s])[col].mean())
    return [round(float(df[col].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(df)), len(d)]
S = R.dropna(subset=["jsd_base"]).copy()
for c in ("p1", "p2"):
    if f"jsd_{c}" in S: S[f"d_{c}"] = S[f"jsd_{c}"] - S.jsd_base
out = {"written_at": pd.Timestamp.now(tz="UTC").isoformat(), "days": DAYS, "prereg": "experiments/simlab/cohort_calibration/PREREG.md (commit c69406d6)",
       "backers": {"launches_scored (>= 20 real grouped backers)": int(len(S)), "launches_total": int(len(R)),
                   "coverage_backers_median": float(R.coverage_backers.median()) if len(R) else None,
                   "JSD base mix": boot_days(S, "jsd_base"), "JSD P1 explain groups_expected": boot_days(S, "jsd_p1") if "jsd_p1" in S else None,
                   "JSD P2 frozen CF list": boot_days(S, "jsd_p2") if "jsd_p2" in S else None,
                   "P1 minus base (paired)": boot_days(S, "d_p1") if "d_p1" in S else None, "P2 minus base (paired)": boot_days(S, "d_p2") if "d_p2" in S else None,
                   "note": "[mean, day-bootstrap 2.5%, 97.5%, launches, days]; pass = paired upper bound < 0"}}
# per day series
ser = []
for D in DAYS:
    s = S[S.day == D]; r_ = R[R.day == D]
    ser.append({"day": D, **day_cov[D], "launches_scored": int(len(s)), "coverage_backers_median": float(r_.coverage_backers.median()) if len(r_) and r_.coverage_backers.notna().any() else None,
                "real_backers_total": int(r_.real_backers.sum()), "jsd_base": round(float(s.jsd_base.mean()), 3) if len(s) else None,
                "jsd_p1": round(float(s.jsd_p1.mean()), 3) if "jsd_p1" in s and s.jsd_p1.notna().any() else None,
                "jsd_p2": round(float(s.jsd_p2.mean()), 3) if "jsd_p2" in s and s.jsd_p2.notna().any() else None})
out["per_day"] = ser
# where we pick wrong (P2 has the widest coverage; P1 where present)
best = "jsd_p1" if "jsd_p1" in S and S.jsd_p1.notna().sum() >= 20 else "jsd_p2"
def by(col, bins=None):
    x = S.dropna(subset=[best]).copy()
    if bins: x[col] = pd.cut(x[col], bins[0], labels=bins[1])
    g = x.groupby(col, observed=True)[best].agg(["mean", "count"]).round(3)
    return {str(k): {"mean_jsd": v["mean"], "launches": int(v["count"])} for k, v in g.iterrows()}
out["where_wrong"] = {"metric": best, "by_family": by("family"), "by_final_rank": by("rank", ([0, 5, 10, 1e9], ["1-5", "6-10", "11+"])),
                      "by_ph_votes": by("ph_votes", ([0, 100, 250, 1e9], ["<100", "100-250", ">250"])), "by_new_backer_share": by("new_share", ([-0.01, 0.1, 0.3, 1.01], ["<10%", "10-30%", ">30%"])),
                      "real_top_group_share_mean": round(float(S.real_top_group_share.mean()), 3)}
# commenters pooled per day
C = pd.DataFrame(comm_rows); cs = []
for D in DAYS:
    c = C[C.day == D]; gl = [g for x in c.groups for g in x]; n_nt = int(c.nonteam_commenters.sum()); n_m = int(c.matched.sum())
    r_ = {"day": D, "nonteam_commenters": n_nt, "matched_held": n_m, "coverage": round(n_m / n_nt, 3) if n_nt else None, "grouped": len(gl)}
    if len(gl) >= 20:
        real = mix(gl); r_["jsd_base"] = round(jsd({int(k) if str(k).isdigit() else k: v for k, v in day_cov[D]["base_mix"].items()}, real), 3)
        # predicted: launch-weighted P2 mix of the day (weights = matched commenters per launch)
        if 'BP' in dir(): pass
        r_["commenter_mix"] = {str(k): round(v, 3) for k, v in real.items()}
    cs.append(r_)
out["commenters_per_day"] = cs
json.dump(out, open(OUT, "w"), indent=1, default=str); R.to_parquet(OUT.replace(".json", "_rows.parquet"))
print(json.dumps({k: out[k] for k in ("backers", "where_wrong")}, indent=1, default=str)); print(json.dumps(ser, default=str)); print(json.dumps(cs, default=str))
