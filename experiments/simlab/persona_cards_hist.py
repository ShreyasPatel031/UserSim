"""Persona cards for the 300 past launches of the reactions_v2 harness (validation of the persona-panel "say"). Same rules as persona_cards.py:
12 personas per launch allocated across role segments (keyword rule on the person's own headline + bio) in proportion to the source mix, each
aggregating >= 20 held people of one segment. Source = the launch team's earlier backers (held people who upvoted an earlier launch, dated
before the target day, whose poster or a maker is on this launch's team) when >= 20 people, else held people who upvoted launches sharing the
launch's first topic in the 30 days before the day. Card: segment, people, median upvotes in the 30 days before, topic shares and products
commonly upvoted in the 90 days before (launch days strictly before the target day). DATING: by launch day; the profile reads behind the
upvotes were fetched in Nov 2026. No usernames, ids or headlines in the output.
    python persona_cards_hist.py <store dir> <sample json> <out json>"""
import json, os, re, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
from pipeline import warehouse  # noqa: E402
ST, SMP, OUT = sys.argv[1:4]; MIN, K = 20, int(os.environ.get("PANEL_K", 12))
EW = open(os.path.join(HERE, "explain_writer.py")).read(); exec(EW[EW.index("SEG = ["):EW.index("WHO, COV = {}, {}")])
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
seg = dict(zip(PJ.person_id, (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).map(seg_of)))
import segments_lib; SEGL, SEGP = segments_lib.load(os.environ.get("SEG_SP"))   # data-driven segments override the keyword roles
if SEGL: seg = {p: SEGL.get(p, segments_lib.INACTIVE) for p in seg}
E = pd.read_parquet(f"{ST}/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"].copy(); del E
U["target_id"] = U.target_id.astype(str)
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W["day"] = W.day.astype(str).str[:10]
mk = lambda m: {str(x).lower() for x in (json.loads(m) if isinstance(m, str) and m.startswith("[") else []) if x and not str(x).startswith("[")}
tp = lambda t: (json.loads(t) if isinstance(t, str) and t.startswith("[") else [])
W["team"] = [mk(m) | ({str(p).lower()} if isinstance(p, str) and p and not p.startswith("[") else set()) for m, p in zip(W.makers, W.poster)]
W["tops"] = W.topics.map(tp); lday = dict(zip(W.id, W.day)); lname = dict(zip(W.id, W.name)); ltops = dict(zip(W.id, W.tops))
U["lday"] = U.target_id.map(lday); U = U[U.lday.notna()]
by_member = {}
for i, d, t in zip(W.id, W.day, W.team):
    for u in t: by_member.setdefault(u, []).append((d, i))
voters = U.groupby("target_id").person_id.agg(set).to_dict()
SPEC = bool(os.environ.get("SPECTRUM"))
LEAF = [l for l, v in SEGP.items() if "subgroup_size" in v] + [l for l, v in SEGP.items() if "subgroup_size" not in v and not any(k.startswith(l + " / ") for k in SEGP)]
MEM = {}
for p_, l in seg.items(): MEM.setdefault(l, []).append(p_)
RNG = np.random.default_rng(0)


def interest(lift): return "high" if lift >= 1.5 else ("medium" if lift >= 0.67 else "low")


def spectrum(D, people):
    """One card per leaf unit. share = unit share of this launch's likely-voter pool; base_share = unit share of held upvotes in the 30 days
    before D; lift = share / base_share; interest from lift (>= 1.5 high, >= 0.67 medium, else low). Card profile from the unit's members in
    the pool when >= 20, else from 400 random members of the unit (upvotes in the 90 days before D)."""
    d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); d90 = (pd.Timestamp(D) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    base = U[(U.lday < D) & (U.lday >= d30)].person_id.map(seg); base = base[base.isin(set(LEAF))].value_counts(normalize=True)
    mix = pd.Series([seg.get(p_) for p_ in people]); mix = mix[mix.isin(set(LEAF))].value_counts(normalize=True)
    out = []
    for l in LEAF:
        sh, b = float(mix.get(l, 0.0)), float(base.get(l, 0.0)); lift = sh / b if b else 0.0
        inpool = [p_ for p_ in people if seg.get(p_) == l]
        c = inpool if len(inpool) >= MIN else list(RNG.choice(MEM.get(l, []), min(400, len(MEM.get(l, []))), replace=False))
        g = U[U.person_id.isin(set(c)) & (U.lday < D) & (U.lday >= d90)]
        tc = pd.Series([t for i in g.target_id for t in (ltops.get(i) or [])]).value_counts(normalize=True).head(4)
        n30 = g[g.lday >= d30].groupby("person_id").size().reindex(c).fillna(0)
        prods = g.groupby("target_id").person_id.nunique().sort_values(ascending=False).head(6)
        out.append({"segment": l, "n_people": int(SEGP[l].get("subgroup_size") or SEGP[l].get("group_size")), "segment_profile": SEGP[l],
                    "share_of_expected_voters": round(sh, 3), "base_share": round(b, 3), "lift": round(lift, 2), "interest": interest(lift),
                    "median_upvotes_last_30_days": float(n30.median()) if len(n30) else 0.0,
                    "topic_shares": [{"topic": t, "share": round(float(v), 3)} for t, v in tc.items()],
                    "products_they_commonly_upvoted": [{"product": lname.get(t, "?"), "share_of_group": round(float(n / len(c)), 2)} for t, n in prods.items() if n >= 3]})
    return sorted(out, key=lambda r: -r["lift"])


cards = {}
for x in json.load(open(SMP)):
    D, lid = x["day"], x["id"]; team = mk(x["makers"]) | ({str(x["poster"]).lower()} if x.get("poster") else set())
    earlier = {i for u in team for (d, i) in by_member.get(u, []) if d < D and i != lid}
    pool = set().union(*[voters.get(i, set()) for i in earlier]) if earlier else set(); src = "team past backers"
    if len(pool) < MIN:
        t0 = (tp(x["topics"]) or [None])[0]; d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        tl = {i for i, d in lday.items() if d30 <= d < D and t0 in (ltops.get(i) or [])} if t0 else set()
        pool = set().union(*[voters.get(i, set()) for i in tl]) if tl else set(); src = "same-topic backers (30 days before)"
    people = sorted(pool)
    if len(people) < MIN: cards[x["slug"]] = {"status": "fewer than 20 people"}; continue
    if SPEC:   # spectrum panel: one voice per leaf unit (every subgroup + groups without subgroups), sorted by lift
        cards[x["slug"]] = {"source": src, "n_source_people": len(people), "personas": spectrum(D, people)}; continue
    sg = pd.Series([seg.get(p, segments_lib.INACTIVE if SEGL else "no headline or bio") for p in people]); big = sg.value_counts(); big = big[big >= MIN]
    if big.empty: cards[x["slug"]] = {"status": "no segment >= 20"}; continue
    THR = float(os.environ.get("PANEL_SHARE", 0))   # panel-size rule: one persona per segment holding >= THR of the likely voters
    if THR:
        big = big[big / len(people) >= THR]; big = big if len(big) else sg.value_counts().head(1)
        alloc = pd.Series(1, index=big.index); rem = 0
    else: alloc = np.floor(K * big / big.sum()).astype(int); rem = K - alloc.sum()
    for s_ in (big / big.sum() * K - alloc).sort_values(ascending=False).index[:rem]: alloc[s_] += 1
    d90 = (pd.Timestamp(D) - pd.Timedelta(days=90)).strftime("%Y-%m-%d"); d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    Ub = U[U.person_id.isin(set(people)) & (U.lday < D) & (U.lday >= d90)]
    P_ = []
    for s_, k_ in alloc.items():
        grp = [p for p, z in zip(people, sg) if z == s_]
        chunks = [c for c in ([grp[j::k_] for j in range(k_)] if k_ else []) if len(c) >= MIN] or ([grp] if k_ else [])
        for c in chunks[:k_]:
            g = Ub[Ub.person_id.isin(set(c))]
            tc = pd.Series([t for i in g.target_id for t in (ltops.get(i) or [])]).value_counts(normalize=True).head(4)
            n30 = g[g.lday >= d30].groupby("person_id").size().reindex(c).fillna(0)
            prods = g.groupby("target_id").person_id.nunique().sort_values(ascending=False).head(6)
            P_.append({"segment": s_, "n_people": len(c), **({"segment_profile": SEGP[s_]} if s_ in SEGP else {}), "median_upvotes_last_30_days": float(n30.median()),
                       "topic_shares": [{"topic": t, "share": round(float(v), 3)} for t, v in tc.items()],
                       "products_they_commonly_upvoted": [{"product": lname.get(t, "?"), "share_of_group": round(float(n / len(c)), 2)} for t, n in prods.items() if n >= 3]})
    cards[x["slug"]] = {"source": src, "n_source_people": len(people), "personas": P_}
json.dump(cards, open(OUT, "w"), indent=1, default=float)
print(json.dumps({"launches": len(cards), "with_personas": sum("personas" in v for v in cards.values()),
                  "team source": sum(v.get("source") == "team past backers" for v in cards.values())}))
