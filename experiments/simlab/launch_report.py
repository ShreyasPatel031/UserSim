"""One launch, everything the simulation says about it, each part checked against what really happened.
  1. Day ranking: simulation-only rank vs real rank.
  2. Likely voters: the 30-day population ranked by the taste person model (trained on the month before), with the
     main reason for each person; then how many of them really voted.
  3. Likely commenters: upvote chance x the person's past share of comments; checked against real commenters.
  4. Page elements: Gemini's scores, the page facts with a measured effect (ctrl.py), and what is not scored.
  5. What commenters will say: Gemini's predicted comment mix, questions and competitors vs the real comments' labels.
usage: TASTE=1 python -m simlab.launch_report <launch_id> -> reports/launch_<id>.json and .md"""
import json, os, pickle, sys
from collections import Counter
import numpy as np, pandas as pd
from . import choice, popscore as PS
from .page_taste import traits

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.join(os.path.dirname(HERE), "ph_predict")
EFFECTS = {"pf_free_plan": "+0.06", "pf_mac_app": "+0.05", "pf_open_source": "+0.05", "pf_mentions_competitor": "+0.04",
           "pf_no_signup_needed": "+0.04", "pf_b2b_product": "−0.035", "pf_price_point_not_stated": "−0.05"}


def reason(r, I, hist):
    if r.backed > 0:
        return f"backed this team before ({int(round(np.expm1(r.backed)))}x)"
    if r.nbr_team >= 0.9:
        return "people with similar upvotes backed this team"
    if getattr(r, "taste_cos", 0) > 0.3:
        return "picks pages like this one"
    if r.topic >= 0.8:
        return "upvotes this category a lot"
    if r.meaning >= 0.8:
        past = [I.loc[i, "name"] for _, i in reversed(hist) if i in I.index][:2]
        return "similar to past upvotes: " + ", ".join(past)
    return "active on launch day, general interest"


def main(x):
    PS.load(); traits()
    from . import harness
    B = harness.baseline()
    g = PS.load(); I = g["I"].set_index("id"); E = g["E"]
    d = I.loc[x, "day"]; art = pickle.load(open(f"{PS.WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    D = PS.featurize(D, art["cf"], art["prior_cut"]); D, pc = PS.page_cols(D)
    D["p"] = art["model"].predict_proba(D[PS.FEATS + pc])[:, 1]; D["wp"] = D.w * D.p
    day = D.groupby("id").wp.sum().rename("sim").reset_index().merge(B[["id", "dailyRank"]].drop_duplicates("id"), on="id")
    day["sim_rank"] = day.sim.rank(ascending=False).astype(int)
    out = {"launch": x, "name": I.loc[x, "name"], "tagline": I.loc[x, "tagline"], "day": d, "real_votes": int(I.loc[x, "out_votes"]),
           "real_rank": int(day.set_index("id").dailyRank[x]), "sim_rank": int(day.set_index("id").sim_rank[x]), "launches_that_day": len(day),
           "sim_day_top5": [(I.loc[i, "name"], int(r)) for i, r in day.nsmallest(5, "sim_rank")[["id", "dailyRank"]].values]}
    P = D[D.id == x].copy().sort_values("p", ascending=False).reset_index(drop=True)
    voted_all = set(E[(E.item.astype(str) == x) & (E.kind == "upvote")].person)
    commented = set(E[(E.item.astype(str) == x) & (E.kind == "comment")].person)
    hist = {u: list(zip(h.date, h.item.astype(str))) for u, h in E[E.person.isin(P.person.head(200))].sort_values("date").groupby("person")}
    P["really_voted"] = P.y.astype(bool)
    top = P.head(25)
    out["voters"] = [{"person": r.person, "chance": round(float(r.p), 3), "reason": reason(r, I, [h for h in hist.get(r.person, []) if h[0] < d]),
                      "really_voted": bool(r.really_voted)} for r in top.itertuples()]
    from sklearn.metrics import roc_auc_score
    real_in_pop = int(P.y.sum())
    out["voter_check"] = {"population": len(P), "real_voters_in_population": real_in_pop, "real_voters_total_in_our_data": len(voted_all | commented),
                          "real_votes_on_PH": int(I.loc[x, "out_votes"]),
                          "hits_in_top25": int(top.really_voted.sum()), "hits_in_top100": int(P.head(100).really_voted.sum()),
                          "share_of_real_voters_in_top100": round(float(P.head(100).really_voted.sum() / max(real_in_pop, 1)), 3),
                          "auc": round(float(roc_auc_score(P.y, P.p)), 3) if 0 < real_in_pop < len(P) else None}
    # commenters: upvote chance x past comment share (30 days before)
    cut = (pd.Timestamp(d) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    act = E[(E.date >= cut) & (E.date < d)].groupby("person").kind.value_counts().unstack(fill_value=0)
    share = (act.get("comment", 0) / (act.sum(1) + 1)).to_dict()
    P["c"] = P.p * P.person.map(share).fillna(0)
    C = P.sort_values("c", ascending=False)
    out["commenters"] = [{"person": r.person, "really_commented": r.person in commented} for r in C.head(15).itertuples()]
    out["commenter_check"] = {"real_commenters_in_population": int(P.person.isin(commented).sum()), "hits_in_top15": int(C.head(15).person.isin(commented).sum()),
                              "hits_in_top100": int(C.head(100).person.isin(commented).sum())}
    # page
    ps = {json.loads(l)["id"]: json.loads(l) for l in open(f"{PH}/data/page_scores.jsonl")}.get(x, {})
    pf = json.load(open(f"{PH}/data/pf_features.json")).get(x, {})
    res = ps.get("result", {})
    out["elements"] = res.get("elements"); out["overall"] = res.get("overall"); out["images_scored"] = ps.get("n_images", 0)
    out["proven_facts"] = {k[3:]: {"has_it": bool(pf.get(k)), "measured_effect": v} for k, v in EFFECTS.items()}
    # comments
    labels = [json.loads(l) for l in open(f"{PH}/data/comment_labels.jsonl") if l.startswith('{"key": "' + x + "|")]
    real_mix = Counter(l["kind"] for l in labels); n = sum(real_mix.values()) or 1
    out["comments"] = {"predicted_mix": res.get("comment_mix"), "real_mix": {k: round(v / n, 2) for k, v in real_mix.items()}, "real_comments": n,
                       "predicted_questions": res.get("questions"), "predicted_competitors": res.get("competitors"),
                       "real_named_products": sorted({p for l in labels for p in l.get("named") or []})}
    json.dump(out, open(f"{HERE}/reports/launch_{x}.json", "w"), indent=1, default=str)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
