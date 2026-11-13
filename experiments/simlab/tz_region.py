"""Time-zone mechanism for late climbers (orchestrator 02:04Z Nov 13). Location sources: people_v3g profiles.location (PH / X / other
platform profiles) and Grok Bot's X persons.jsonl location; free text mapped to Americas / Europe-Africa / Asia-Pacific by a keyword
table (countries, US states / abbreviations, major cities); ambiguous or unmapped -> unknown. Team = hunter (always safe) + the first named
maker in the launches table (safe at 00:05 in most reads). A launch's team region = majority of its known team members' regions.
(1) coverage per launch Oct 26 - Nov 11; (2) rank change from the hidden rank at 01:00 / 02:00 / 03:00 PT to the final rank by team
region, 7 hidden-window days, day bootstrap; (3) if Americas teams climb: hidden rank + region offset, leave-day-out, top 3/5/10;
(4) held voters with a known region: share of a launch's voters from the Americas vs its climb (hidden-rank days) and vs its residual over
the clean score (Oct 1 - Nov 10). Counts only.
    python tz_region.py <v3g dir> <x drops dir> <store dir> <launches dir> <salt dir> <warehouse cache> <honest_preds_v2.parquet> <out dir>
"""
import glob, hashlib, json, os, re, sys
import numpy as np, pandas as pd
G3, XD, V3, LDIR, SALTD, WH, HP, OUT = sys.argv[1:9]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
SALT = open(os.path.join(SALTD, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((SALT + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
AM = r"usa|united states|\bus\b|u\.s\.|america|canada|mexico|brazil|brasil|argentina|chile|colombia|peru|uruguay|venezuela|costa rica|toronto|vancouver|montreal|new york|nyc|san francisco|\bsf\b|bay area|silicon valley|los angeles|\bla\b|seattle|austin|boston|chicago|miami|denver|atlanta|dallas|houston|portland|san diego|philadelphia|washington|brooklyn|palo alto|mountain view|são paulo|sao paulo|rio de janeiro|buenos aires|bogot|lima|santiago|mexico city|cdmx|california|texas|florida|new jersey|colorado|georgia|ohio|michigan|illinois|massachusetts|virginia|oregon|utah|arizona|nevada|minnesota|wisconsin|carolina|tennessee|pennsylvania|ontario|quebec|british columbia|alberta|\b(ca|ny|tx|fl|wa|ma|co|il|ga|nc|nj|va|or|az|ut|mn|pa|oh|mi)\b"
EU = r"united kingdom|\buk\b|england|london|scotland|wales|ireland|dublin|france|paris|germany|deutschland|berlin|munich|münchen|hamburg|spain|españa|madrid|barcelona|portugal|lisbon|lisboa|italy|italia|milan|rome|netherlands|amsterdam|belgium|brussels|switzerland|zurich|zürich|geneva|austria|vienna|sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|estonia|tallinn|latvia|lithuania|poland|warsaw|krak|czech|prague|hungary|budapest|romania|bucharest|bulgaria|greece|athens|ukraine|kyiv|kiev|turkey|türkiye|istanbul|israel|tel aviv|europe|nigeria|lagos|kenya|nairobi|south africa|cape town|johannesburg|egypt|cairo|morocco|ghana|uae|dubai|abu dhabi|saudi|riyadh|qatar|serbia|croatia|slovenia|slovakia|cyprus|malta|luxembourg|iceland|belarus|russia|moscow"
AP = r"india|bangalore|bengaluru|mumbai|delhi|hyderabad|pune|chennai|kolkata|gurgaon|gurugram|noida|ahmedabad|pakistan|karachi|lahore|islamabad|bangladesh|dhaka|sri lanka|nepal|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|japan|tokyo|osaka|korea|seoul|singapore|malaysia|kuala lumpur|indonesia|jakarta|bali|philippines|manila|vietnam|hanoi|ho chi minh|saigon|thailand|bangkok|australia|sydney|melbourne|brisbane|perth|new zealand|auckland|wellington|asia|kazakhstan|uzbekistan"
def region(t):
    t = t.lower() if isinstance(t, str) else ""
    if len(t) < 2: return None
    hits = [r_ for r_, pat in (("Americas", AM), ("Europe-Africa", EU), ("Asia-Pacific", AP)) if re.search(pat, t)]
    return hits[0] if len(hits) == 1 else None
loc = {}
pr = pd.read_parquet(os.path.join(G3, "profiles.parquet"), columns=["person_id", "location"])
for p, l in zip(pr.person_id, pr.location):
    r = region(l)
    if r: loc.setdefault(p, r)
for f in glob.glob(os.path.join(XD, "*", "persons.jsonl")):
    for l in open(f):
        x = json.loads(l); r = region(x.get("location"))
        if r: loc.setdefault(x["person_id"], r)
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str); L["rank"] = L.daily_rank.astype(float)
def fmk(m):
    try: ms = json.loads(m) if isinstance(m, str) and m.startswith("[") else []
    except Exception: ms = []
    ms = [x for x in ms if x and not str(x).startswith("[")]; return pid(ms[0]) if ms else None
L["hun"] = [pid(p) if isinstance(p, str) and p and not p.startswith("[") else None for p in L.poster]; L["mak"] = [fmk(m) for m in L.makers]
def team_region(h, m):
    rs = [loc.get(x) for x in (h, m) if x and loc.get(x)]
    if not rs: return "unknown"
    v = pd.Series(rs).value_counts(); return v.index[0] if len(v) == 1 or v.iloc[0] > v.iloc[1] else "mixed"
L["team_region"] = [team_region(h, m) for h, m in zip(L.hun, L.mak)]
W = L[(L.day >= "2026-10-26") & (L.day <= "2026-11-11")]
res = {"design": __doc__.split("\n    python")[0], "people_with_region": len(loc), "region_counts_people": pd.Series(list(loc.values())).value_counts().to_dict(),
       "launches_oct26_nov11": len(W), "team_region_coverage": W.team_region.value_counts().to_dict(),
       "share_launches_with_known_team_region": round(float((~W.team_region.isin(["unknown"])).mean()), 3)}
print(json.dumps({k: v for k, v in res.items() if k != "design"}), flush=True)
# (2) rank change from hidden rank to final by team region
rd = lambda t: pd.concat([pd.read_parquet(f) for f in glob.glob(f"{WH}/{t}/*.parquet")])
V = rd("vote_snapshots"); V["at"] = pd.to_datetime(V["at"], utc=True); V["id"] = V.launch_id.astype(str); V["rank_now"] = pd.to_numeric(V.rank_now, errors="coerce"); V = V[V.rank_now.notna()]
HD = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
def hidden(d, hh):
    T = pd.Timestamp(f"{d} {hh}").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC"); return V[(V.day == d) & (V["at"] <= T)].sort_values("at").groupby("id").rank_now.last()
def dboot(df, col, by):
    out = {}
    for g_, d in df.groupby(by):
        dm = d.groupby("day")[col].mean(); v = dm.values
        bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)] if len(v) > 1 else [np.nan]
        out[g_] = {"launches": int(len(d)), "days": int(len(v)), "mean_climb": round(float(d[col].mean()), 2), "day_ci": [round(float(np.nanpercentile(bs, 2.5)), 2), round(float(np.nanpercentile(bs, 97.5)), 2)]}
    return out
X = L[L.day.isin(HD)].copy(); res["climb"] = {}
for hh in ("01:00", "02:00", "03:00"):
    X["hr"] = [hidden(d, hh).get(i, np.nan) for i, d in zip(X.id, X.day)]; X[f"climb_{hh}"] = X.hr - X["rank"]   # positive = climbed after the read
    res["climb"][hh] = dboot(X.dropna(subset=["hr"]), f"climb_{hh}", "team_region")
print(json.dumps(res["climb"]), flush=True)
# (3) hidden rank + Americas offset (leave-day-out), only if Americas climbs
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
res["offset"] = {}
for hh in ("01:00", "02:00", "03:00"):
    Y = X.copy(); Y["hr"] = [hidden(d, hh).get(i, 999) for i, d in zip(Y.id, Y.day)]; Y["s0"] = -np.log(Y.hr); Y["am"] = (Y.team_region == "Americas").astype(float)
    per = []
    for d in HD:
        tr = Y[Y.day != d]; b = max((0, .25, .5, 1), key=lambda b: np.mean([dm(g.assign(s=g.s0 + b * g.am), "s")[0] for _, g in tr.groupby("day")]))
        g = Y[Y.day == d]; per.append(np.array(dm(g.assign(s=g.s0 + b * g.am), "s")) - np.array(dm(g, "s0")))
    df = np.array(per); bs = np.array([df[rng.integers(0, len(df), len(df))].mean(0) for _ in range(2000)])
    res["offset"][hh] = {"hidden_alone_top3": float(np.mean([dm(Y[Y.day == d], "s0")[0] for d in HD])), "gain top3/5/10": [[round(float(df[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]}
# (4) voters: share of a launch's held voters from the Americas vs climb / residual
P = pd.read_parquet(os.path.join(V3, "persons.parquet")); COV = set(P[P.complete].person_id)
E = pd.read_parquet(os.path.join(V3, "events.parquet"), columns=["person_id", "kind", "target_id"]); E = E[(E.kind == "upvote") & E.person_id.isin(COV)]
E["reg"] = E.person_id.map(loc); E = E[E.reg.notna()]; E["target_id"] = E.target_id.astype(str)
sh = E.groupby("target_id").agg(n=("reg", "size"), am=("reg", lambda s: (s == "Americas").mean()))
X2 = X.merge(sh, left_on="id", right_index=True, how="inner"); X2 = X2[X2.n >= 5]
from scipy.stats import spearmanr
res["voters"] = {"held_voters_with_region": int(E.person_id.nunique()), "launches_with_>=5_regioned_voters_hidden_days": len(X2)}
for hh in ("01:00", "02:00", "03:00"):
    if len(X2) > 10: res["voters"][f"spearman(americas share, climb after {hh})"] = round(float(spearmanr(X2.am, X2[f"climb_{hh}"], nan_policy="omit").correlation), 3)
Hn = pd.read_parquet(HP)[["id", "honest", "day"]]; Hn["id"] = Hn.id.astype(str)
R = L[(L.day >= "2026-10-01") & (L.day <= "2026-11-10")].merge(Hn[["id", "honest"]], on="id"); R["crank"] = R.groupby("day").honest.rank(ascending=False); R["resid"] = R.crank - R["rank"]
R = R.merge(sh, left_on="id", right_index=True); R = R[R.n >= 5]
cors = []
for _ in range(1000):
    ds = rng.choice(R.day.unique(), R.day.nunique()); s_ = pd.concat([R[R.day == d] for d in ds]); cors.append(spearmanr(s_.am, s_.resid).correlation)
res["voters"]["oct1_nov10: launches"] = len(R); res["voters"]["spearman(americas share, finish above clean rank)"] = [round(float(spearmanr(R.am, R.resid).correlation), 3), round(float(np.percentile(cors, 2.5)), 3), round(float(np.percentile(cors, 97.5)), 3)]
json.dump(res, open(os.path.join(OUT, "tz_region.json"), "w"), indent=1, default=float); print(json.dumps({k: res[k] for k in ("offset", "voters")}, default=float))
