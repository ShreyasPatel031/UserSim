"""How much of the person model's gap is relationship knowledge vs taste? For every active person-day Jul-Oct (people who
really voted that day), the taste-aware person model (TASTE=1, cache/popscore_page_taste) ranks the line-up. Each real
pick is labelled:
  tied     a dated tie to the team before the day: the person backed the team's earlier launches, or the team engaged
           with the person's own launches (reciprocity)
  follow   the person follows a team member on Product Hunt (undated, so reported separately)
  untied   neither
Reports (reports/rel_split.json):
  - share of picks in each label, and the person model's top-3 hit on each (is the pick in its top 3 for that person)
  - per person: "acts on relationships" = share of their picks that are tied or follow; stability (Jul-Aug vs Sep-Oct
    correlation) and top-3 hit by quartile of that trait
  - ceilings: top-3 hit if every tied/follow pick were ranked first (relationships we already know, used perfectly),
    and if every pick were known (100 by definition) - the gap split into relationship-known, relationship-unknown, taste
Everything is dated before the day except follow.
usage: SIMLAB_DATA=data_v2 TASTE=1 python -m simlab.rel_split [workers]"""
import json, os, pickle, sys
import multiprocessing as mp
import numpy as np, pandas as pd
from . import choice, popscore as PS

HERE = os.path.dirname(os.path.abspath(__file__))
FROM, TO = os.environ.get("FROM", "2026-07-01"), os.environ.get("TO", "2026-10-24")


def day(d):
    art = pickle.load(open(f"{PS.WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d)   # people active that day
    if not len(D):
        return None
    D = PS.featurize(D, art["cf"], art["prior_cut"]); D = PS.recip_features(D); D, pc = PS.page_cols(D)
    D["p"] = art["model"].predict_proba(D[PS.FEATS + pc])[:, 1]
    D["rk"] = D.groupby("person").p.rank(ascending=False, method="first")
    D["tied"] = (D.backed > 0) | (D.recip_team > 0); D["fol"] = (D.follow > 0) & ~D.tied
    rows = []
    for u, g in D.groupby("person"):
        y = g.y.values > 0
        if not y.any() or y.all():
            continue
        t, f, rk = g.tied.values, g.fol.values, g.rk.values
        top = rk <= 3
        rows.append({"person": u, "day": d, "n": int(y.sum()), "n_tied": int((y & t).sum()), "n_fol": int((y & f).sum()),
                     "n_untied": int((y & ~t & ~f).sum()), "hit": bool((y & top).any()),
                     "hit_tied": int((y & t & top).sum()), "hit_fol": int((y & f & top).sum()), "hit_untied": int((y & ~t & ~f & top).sum()),
                     "lineup_tied": int(t.sum()), "lineup_fol": int(f.sum()),
                     # ceiling 1: rank every known relationship (tied, then follow) first, then the model's order
                     "hit_rel_first": bool(y[np.lexsort((rk, ~f, ~t))][:3].any()),
                     # ceiling 2: dated ties only first
                     "hit_tied_first": bool(y[np.lexsort((rk, ~t))][:3].any())})
    return rows


def main(workers):
    os.environ.setdefault("TASTE", "1"); PS.load()
    if PS.TASTE:
        from .page_taste import traits
        traits()
    from . import harness
    harness.baseline()
    days = sorted(d for d in PS.G["lineup"] if FROM <= d <= TO)
    with mp.get_context("fork").Pool(workers) as pool:
        R = [r for x in pool.imap_unordered(day, days) if x for r in x]
    R = pd.DataFrame(R); R.to_parquet(f"{HERE}/cache/rel_split_rows.parquet")   # per-person rows stay on the VM
    picks = R[["n", "n_tied", "n_fol", "n_untied"]].sum()
    hits = R[["hit_tied", "hit_fol", "hit_untied"]].sum()
    out = {"person_days": len(R), "people": int(R.person.nunique()), "picks": int(picks.n),
           "share_of_picks": {k: round(100 * float(picks["n_" + k] / picks.n), 1) for k in ("tied", "fol", "untied")},
           "pick_in_model_top3": {k: round(100 * float(hits["hit_" + k] / max(picks["n_" + k], 1)), 1) for k in ("tied", "fol", "untied")},
           "top3_hit": round(100 * float(R.hit.mean()), 1),
           "ceiling_dated_ties_first": round(100 * float(R.hit_tied_first.mean()), 1),
           "ceiling_all_known_relationships_first": round(100 * float(R.hit_rel_first.mean()), 1)}
    # person-days by what kind of picks they made
    kind = np.where(R.n_untied == R.n, "all untied", np.where(R.n_untied == 0, "all tied/follow", "mixed"))
    out["by_person_day_kind"] = {k: {"share": round(100 * float((kind == k).mean()), 1), "top3_hit": round(100 * float(R.hit[kind == k].mean()), 1)}
                                 for k in ("all tied/follow", "mixed", "all untied")}
    # per-person trait: acts on relationships
    R["half"] = np.where(R.day < "2026-09-01", "a", "b")
    S = R.groupby(["person", "half"])[["n", "n_tied", "n_fol"]].sum()
    S["rel"] = (S.n_tied + S.n_fol) / S.n
    W = S.rel.unstack().dropna(); Wn = S.n.unstack().reindex(W.index)
    W5 = W[(Wn.a >= 5) & (Wn.b >= 5)]
    out["trait_stability"] = {"people_with_5_picks_each_half": len(W5), "corr_jul_aug_vs_sep_oct": round(float(W5.a.corr(W5.b)), 3),
                              "mean_share_rel": round(float(W5.values.mean()), 3)}
    # does the earlier half's trait sort later hit rates? (no leakage: trait from Jul-Aug, hits in Sep-Oct)
    tr = S.rel.xs("a", level="half"); B = R[R.half == "b"].assign(trait=lambda x: x.person.map(tr)).dropna(subset=["trait"])
    B["q"] = pd.qcut(B.trait.rank(method="first"), 4, labels=["q1 least", "q2", "q3", "q4 most"])
    out["sep_oct_by_jul_aug_trait"] = {str(k): {"person_days": int(len(g)), "top3_hit": round(100 * float(g.hit.mean()), 1),
                                                "share_untied_picks": round(100 * float(g.n_untied.sum() / g.n.sum()), 1)}
                                       for k, g in B.groupby("q", observed=True)}
    by_m = R.assign(m=R.day.str[:7]).groupby("m")
    out["by_month_top3_hit"] = by_m.hit.mean().mul(100).round(1).to_dict()
    out["by_month_untied_share"] = (by_m.n_untied.sum() / by_m.n.sum()).mul(100).round(1).to_dict()
    json.dump(out, open(f"{HERE}/reports/rel_split.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 16)
