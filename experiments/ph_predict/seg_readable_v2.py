"""Readable attribute-group output for Shreyas (orchestrator 07:56Z (3)), from segment_attr_v2.py (K=12, A-fit segments,
popularity-stratified EB-shrunk lifts). For the 10 attribute groups with the most Oct 20 - Nov 8 votes from the held-out
half B: predicted top-3 / bottom-3 audiences (A's Sep 1 - Oct 19 lift for that attribute) vs the actual top-3 / bottom-3
(B's Oct 20 - Nov 8 lift), Spearman across the 12 segments, and the segment descriptions. Counts only, no usernames.
usage: SIMBT=<dir> python seg_readable_v2.py -> results/seg_readable_v2_k12.md"""
import os, pickle
import numpy as np
from scipy.stats import spearmanr
WORK = os.environ["SIMBT"]; HERE = os.path.dirname(os.path.abspath(__file__)); K = 12
A = pickle.load(open(f"{WORK}/segattr_v2_k{K}.pkl", "rb"))
ATTR, pred, real, tv, desc = A["ATTR"], A["lift"], A["test_lift_B"], A["test_votes_B"], A["desc"]
nice = lambda x: x.replace("topic:", "#").replace("cat_", "").replace("aud_", "for ").replace("plat_", "").replace("mat_", "").replace("price_", "").replace("mkt_", "").replace("_", " ")
name = {s: f"S{s} {', '.join(nice(a) for a in desc[s]['top_attrs'][:2])} / {', '.join(desc[s]['top_topics'][:2])}" for s in range(K)}
out = ["# Which audiences favour which kinds of product (K=12 segments)", "",
       "How to read this: Product Hunt people were grouped into 12 audiences by what they upvoted before Sep 1. For each kind of product "
       "(an attribute or topic), we learned from one half of the people (Sep 1 - Oct 19) which audiences over- or under-vote it, after "
       "removing each audience's overall activity and each launch's popularity. We then checked against the OTHER half of the people on "
       "new launches (Oct 20 - Nov 8). Across all product kinds the agreement is a rank correlation of about 0.25 (0.19 on launches from "
       "brand-new teams), against about 0 for a shuffled control. It describes audiences in aggregate; it does not reliably predict a "
       "single person's vote.", "", "## The 12 audiences", "", "| audience | people | over-upvotes (attributes) | over-upvotes (topics) |", "|---|---|---|---|"]
for s in range(K):
    out.append(f"| S{s} | {desc[s]['size_all']} | {', '.join(nice(a) for a in desc[s]['top_attrs'])} | {', '.join(desc[s]['top_topics'])} |")
order = [j for j in np.argsort(-tv.sum(0)) if not ATTR[j].startswith("popq")][:10]
out += ["", "## Ten largest product kinds: predicted vs actual audiences", "",
        "| product kind | test launches (from new teams) | test votes | predicted top 3 | actual top 3 | predicted bottom 3 | actual bottom 3 | rank corr. |", "|---|---|---|---|---|---|---|---|"]
hits = []
for j in order:
    p, r = pred[:, j], real[:, j]
    pt, rt = list(np.argsort(-p)[:3]), list(np.argsort(-r)[:3]); pb, rb = list(np.argsort(p)[:3]), list(np.argsort(r)[:3])
    sp = spearmanr(p, r).correlation; hits.append((len(set(pt) & set(rt)), len(set(pb) & set(rb)), sp))
    f = lambda L: ", ".join(f"S{s}" for s in L)
    out.append(f"| {nice(ATTR[j])} | {int(A['n_test_launches'][j])} ({int(A['n_test_cold'][j])}) | {int(tv[:, j].sum())} | {f(pt)} | {f(rt)} | {f(pb)} | {f(rb)} | {sp:+.2f} |")
h = np.array(hits)
out += ["", f"Over these 10: predicted top-3 audiences that were in the actual top 3: {int(h[:, 0].sum())} of 30 (random about 7.5); "
        f"bottom-3: {int(h[:, 1].sum())} of 30; mean rank correlation {h[:, 2].mean():+.2f}.", "",
        "Audience key: " + "; ".join(name[s] for s in range(K)) + "."]
open(os.path.join(HERE, "results", f"seg_readable_v2_k{K}.md"), "w").write("\n".join(out) + "\n")
print("\n".join(out))
