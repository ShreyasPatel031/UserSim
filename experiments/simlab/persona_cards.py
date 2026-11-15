"""Persona cards for the "say" persona panel (website item 2, orchestrator 23:19Z Nov 14): the NON-LLM half only. 12 personas per launch,
allocated across role segments in proportion to the source list's segment mix; each persona aggregates >= 20 held people of one segment
(never one person: a single person's upvote list could identify them), from the launch's team past-backer pool when it holds >= 20 people,
else from the CF-only top 200. Card = segment, people count, activity (median upvotes in the 30 days before D), topic shares, the products
most commonly upvoted by the group in the 90 days before D (product names only). All from reads fetched before 00:00 PT of D. No usernames,
no person ids, no headlines. PRIVATE input for the Gemini reaction step (owner TBD): gs://.../tmp/e5/persona_cards/<day>.json
    python persona_cards.py <store dir> <scratchpad> <day> [--no-upload]"""
import json, os, re, subprocess, sys
import numpy as np, pandas as pd
DOC = __doc__; HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "backer_arms.py")).read(); exec(SRC[:SRC.index("def day_cols(")])
EW = open(os.path.join(HERE, "explain_writer.py")).read(); exec(EW[EW.index("SEG = ["):EW.index("WHO, COV = {}, {}")])
MIN, K = 20, int(os.environ.get("PANEL_K", 24)); TOPN = list(g["TOP"]); D = TDAYS[0]
PJ = pd.read_parquet(f"{ST}/persons.parquet", columns=["person_id", "headline", "bio"]).drop_duplicates("person_id")
seg = dict(zip(PJ.person_id, (PJ.headline.fillna("") + " " + PJ.bio.fillna("")).map(seg_of)))
import segments_lib; SEGL, SEGP = segments_lib.load(os.environ.get("SEG_SP"))   # data-driven segments override the keyword roles
if SEGL: seg = {p: SEGL.get(p, segments_lib.INACTIVE) for p in seg}
H = U[U.fetched_at < start(D)]; Hb = H[H.lday < D]; act, tvec, ix = feats(D, H)
d30 = (pd.Timestamp(D) - pd.Timedelta(days=30)).strftime("%Y-%m-%d"); d90 = (pd.Timestamp(D) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
n30 = Hb[Hb.lday >= d30].groupby("person_id").size(); names = dict(zip(WA.id.astype(str), WA.name))
A_ = pd.read_parquet(os.path.join(SP, "bp", f"backer_arms_{D}.parquet")); A_ = A_[A_.arm == "CF-only"]
cards, POOLS = {}, {}
for lid in [str(p["id"]) for p in LINE.get(D, [])]:
    team = [x for x in (lhun.get(lid), lmak.get(lid)) if x]
    ls = set().union(*[by_team.get(x, set()) for x in team]) - {lid} if team else set()
    pool = Hb[Hb.target_id.isin(ls)].person_id.unique().tolist() if ls else []
    cf_rank = A_[A_.launch_id == lid].sort_values("rank").person_id.tolist()
    if len(pool) >= K * MIN: src, people = "team past voters", pool
    else:   # 24 personas x >= 20 people needs >= 480: the team's earlier voters first, topped up with the CF-only ranking for this launch
        ps_ = set(pool); people = list(pool) + [q for q in cf_rank if q not in ps_][:max(0, K * MIN - len(pool))]
        src = ("team past voters + CF-only top-up" if len(pool) >= MIN else "CF-only ranking (top %d)" % len(people))
    if len(people) < MIN: cards[lid] = {"status": "not available (fewer than 20 people)"}; continue
    sg = pd.Series([seg.get(p, segments_lib.INACTIVE if SEGL else "no headline or bio") for p in people])
    vc0 = sg.value_counts(); small = set(vc0[vc0 < MIN].index)   # a subgroup with < 20 people in this pool folds into its group label
    if small: sg = sg.map(lambda x: x.split(" / ")[0] if x in small else x)
    POOLS[lid] = {"hunter": Hb[Hb.target_id.isin(by_team.get(lhun.get(lid), set()) - {lid})].person_id.unique().tolist() if lhun.get(lid) else [],
                  "maker": Hb[Hb.target_id.isin(by_team.get(lmak.get(lid), set()) - {lid})].person_id.unique().tolist() if lmak.get(lid) else [], "source": src}
    big = sg.value_counts(); big = big[big >= MIN]
    if big.empty: cards[lid] = {"status": "not available (no segment with >= 20 people)"}; continue
    alloc = np.floor(K * big / big.sum()).astype(int); rem = K - alloc.sum()
    for s_ in (big / big.sum() * K - alloc).sort_values(ascending=False).index[:rem]: alloc[s_] += 1
    P_ = []
    for s_, k_ in alloc.items():
        grp = [p for p, x in zip(people, sg) if x == s_]
        k_ = min(k_, max(1, len(grp) // MIN)) if k_ else 0   # never split below 20 people per persona (was collapsing to one card)
        chunks = [grp[j::k_] for j in range(k_)] if k_ else []   # k_ interleaved sub-groups; each must hold >= 20 people
        chunks = [c for c in chunks if len(c) >= MIN] or ([grp] if k_ else [])
        for c in chunks[:k_]:
            ci_ = [p for p in c if p in ix.index]; tdist = tvec[ix[ci_].values].mean(0) if ci_ else np.zeros(len(TOPN))
            top_t = [{"topic": TOPN[j], "share": round(float(tdist[j]), 3)} for j in np.argsort(-tdist)[:4] if tdist[j] > 0]
            ups = Hb[(Hb.lday >= d90) & Hb.person_id.isin(set(c))].groupby("target_id").person_id.nunique().sort_values(ascending=False)
            prods = [{"product": names.get(t, "?"), "share_of_group": round(float(n / len(c)), 2)} for t, n in ups.head(6).items() if n >= 3]
            P_.append({"segment": s_, "n_people": len(c), **({"segment_profile": SEGP[s_]} if s_ in SEGP else {}), "median_upvotes_last_30_days": float(n30.reindex(c).fillna(0).median()),
                       "topic_shares": top_t, "products_they_commonly_upvoted": prods})
    cards[lid] = {"source": src, "n_source_people": len(people), "personas": P_}
out = {"day": D, "design": DOC.split("\n    python")[0], "written_at": pd.Timestamp.now(tz="UTC").isoformat(), "launches": cards}
os.makedirs(os.path.join(SP, "persona"), exist_ok=True); json.dump(POOLS, open(os.path.join(SP, "persona", f"pools_{D}.json"), "w"))   # PRIVATE (salted ids), local only
p = os.path.join(SP, "persona", f"persona_cards_{D}.json"); json.dump(out, open(p, "w"), indent=1, default=float)
if UP: subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/persona_cards/{D}.json"], check=True)
print(json.dumps({"day": D, "launches": len(cards), "with_personas": sum("personas" in v for v in cards.values()),
                  "personas": sum(len(v.get("personas", [])) for v in cards.values())}))
