"""Panel cards from data-driven groups for the 279-launch reactions_v2 harness (orchestrator 03:30Z Nov 15, items 3-4).
Segments fit with a cut BEFORE every harness launch (population_segments.py --cut 2026-08-01). For each launch dated D:
  group share = the group mix of the launch team's earlier voters (held people who upvoted an earlier launch of the poster / a maker, dated
  before D) when >= 20 such people, else the topic model (group share of upvotes in the 30 days before D x group/topic affinity ratio,
  launch topics; affinities from upvotes dated before D).
Panel variants (one persona per selected group; persona = the group's profile: name, who, says (themes paraphrased from the group's own
comments), votes_for, topics by lift, plus the launch-specific share):
  SHARE5  groups with share >= 5%      SHARE3  >= 3%      SHARE10  >= 10%      TOP12  the 12 largest shares
    python seg_cards_hist.py <store dir> <segments dir (latest.json + members_<cut>.parquet)> <sample json> <out dir> [h25src dir]"""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, ".."))
from pipeline import warehouse  # noqa: E402
ST, SEGD, SMP, OUT = sys.argv[1:5]; H25 = sys.argv[5] if len(sys.argv) > 5 else None; os.makedirs(OUT, exist_ok=True)
J = json.load(open(os.path.join(SEGD, "latest.json"))); M = pd.read_parquet(os.path.join(SEGD, f"members_{J['cut']}.parquet"))
UNIT = os.environ.get("UNIT", "group")   # group | subgroup (persona = one subgroup, labelled "group / subgroup")
if UNIT == "subgroup":
    GRP = dict(zip(M.person_id, M.subgroup.astype(str)))
    PROF = {s_["id"]: {**s_, "name": f"{g.get('name')} / {s_.get('name')}"} for g in J["groups"] for s_ in g.get("subgroups", [])}
else: GRP = dict(zip(M.person_id, M.group.astype(int).astype(str))); PROF = {str(g["id"]): g for g in J["groups"]}
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].copy(); del E
U["target_id"] = U.target_id.astype(str)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
W["tops"] = W.topics.map(lambda t: json.loads(t) if isinstance(t, str) and t.startswith("[") else [])
mk = lambda m: {str(x).lower() for x in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if x and not str(x).startswith("[")}
W["team"] = [mk(m) | ({str(p).lower()} if isinstance(p, str) and p and not p.startswith("[") else set()) for m, p in zip(W.makers, W.poster)]
X = W[["id", "day", "tops", "team"]]
if H25:
    x25 = [(str(e["id"]), os.path.basename(f)[:10], [t["node"]["name"] for t in ((e.get("topics") or {}).get("edges") or [])] if isinstance(e.get("topics"), dict) else (e.get("topics") or []), set())
           for f in glob.glob(os.path.join(H25, "*.json")) for e in json.load(open(f))]
    X = pd.concat([pd.DataFrame(x25, columns=["id", "day", "tops", "team"]), X]).drop_duplicates("id", keep="last")
lday = dict(zip(X.id, X.day)); ltops = dict(zip(X.id, X.tops))
U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()].drop_duplicates(["person_id", "target_id"]); U["g"] = U.person_id.map(GRP)
U = U[U.g.notna() & U.g.isin(set(PROF))]
by_member = {}
for i, d, t in zip(W.id, W.day, W.team):
    for u in t: by_member.setdefault(u, []).append((d, i))
voters = U.groupby("target_id").person_id.agg(set).to_dict(); G_ = sorted(PROF)
UT = U.assign(t=U.target_id.map(ltops)).explode("t").dropna(subset=["t"]).reset_index(drop=True)


def topic_mix(D, tops):
    h = UT[UT.lday < D]; A = pd.crosstab(h.g, h.t).reindex(G_).fillna(0); pop = A.sum(0) / A.values.sum()
    A = (A + 50 * pop).div((A + 50 * pop).sum(1), axis=0); Ar = A / pop
    d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); vs = U[(U.lday < D) & (U.lday >= d30)].g.value_counts().reindex(G_).fillna(0) + 1
    tp = [t for t in tops if t in Ar.columns]; m = (vs / vs.sum()) * (Ar[tp].mean(axis=1) if tp else 1.0); return m / m.sum()


def persona(g, share, n_src):
    p = PROF[g]
    return {"segment": p.get("name") or f"group {g}", "n_people": int(p["n_people"]), "share_of_expected_voters": round(float(share), 3),
            "median_upvotes_last_30_days": float(p.get("median_upvotes_last_30_days") or 0),
            "topic_shares": [{"topic": t["topic"], "share": t["share"]} for t in p.get("topics_by_lift", [])[:4]],
            "products_they_commonly_upvoted": p.get("products_distinctive", [])[:5],
            "segment_profile": {"who": p.get("who"), "says": p.get("says"), "votes_for": p.get("votes_for"), "group": p.get("name")}}


VARS = {"SHARE5": lambda m: m[m >= 0.05], "SHARE3": lambda m: m[m >= 0.03], "SHARE10": lambda m: m[m >= 0.10], "TOP12": lambda m: m.sort_values(ascending=False).head(12)}
cards = {v: {} for v in VARS}; stats = []
for x in json.load(open(SMP)):
    D, lid = x["day"], str(x["id"]); team = mk(x["makers"]) | ({str(x["poster"]).lower()} if x.get("poster") else set())
    earlier = {i for u in team for (d, i) in by_member.get(u, []) if d < D and i != lid}
    pool = set().union(*[voters.get(i, set()) for i in earlier]) if earlier else set()
    if len(pool) >= 20: m = pd.Series([GRP[p_] for p_ in pool if GRP.get(p_) in PROF]).value_counts(normalize=True).reindex(G_).fillna(0); src = "team's earlier voters"
    else: m = topic_mix(D, json.loads(x["topics"]) if isinstance(x["topics"], str) and x["topics"].startswith("[") else []); src = "topic model"
    m = m.sort_values(ascending=False)
    for v, f in VARS.items():
        sel = f(m); sel = sel if len(sel) else m.head(1)
        cards[v][x["slug"]] = {"source": src, "personas": [persona(g, s, len(pool)) for g, s in sel.items()]}
    stats.append({"src": src, **{v: len(cards[v][x["slug"]]["personas"]) for v in VARS}})
for v in VARS: json.dump(cards[v], open(os.path.join(OUT, f"cards_{UNIT}_{v}.json"), "w"), indent=1, default=float)
S = pd.DataFrame(stats); print(json.dumps({"launches": len(S), "source": S.src.value_counts().to_dict(), "panel size median [min, max]": {v: [float(S[v].median()), int(S[v].min()), int(S[v].max())] for v in VARS}}))
