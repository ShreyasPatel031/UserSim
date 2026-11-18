"""Systematic sweep of unscored raw fields (orchestrator 23:37Z Nov 14). PRE-REGISTERED (committed before any residual number was computed).

Input: rawfield_extract.py output (every field of the raw PH day records, mechanically numeric; stored = after-close record; t0005 =
the 00:05 snapshot for Oct 25 - Nov 13). The warehouse launches table carries no field beyond the raw record (poster/makers names, ranks,
votes); raw/ph_at_launch starts Oct 4 / Nov 3 (too short for the 184-day score) and is listed, not scored.
Step 1 exclusions (not "unscored"): fields that are arm-2 inputs or the same quantity (media:n = ph_n_media, topics.edges:n = ph_n_topics,
  makers:n = ph_n_makers, description:len = ph_desc_len, tagline:len = ph_tagline_len, name:len = ph_name_len, drv.hunter_age_d_at_create
  ~ ph_hunter_age_d); fields barred by the clean policy (every makers[].* sub-field: needs named makers); identifiers with no content
  (id:*, user.id:*, createdAt/featuredAt :len/:nonempty).
Step 2 knowability (Oct 25 - Nov 13, same launch in both reads): KNOWABLE if present at 00:05 for >= 80% of launches that have it stored
  AND (Spearman(00:05, stored) >= 0.90, or exact agreement >= 90% when a field has < 3 distinct values). Outcome fields (votesCount,
  commentsCount, reviewsCount, reviewsRating, *Rank*) are leaky by definition. Everything else failing the test is LEAKY and excluded.
Step 3 score (knowable fields): residual = log1p(final votes) - arm 2's prediction ('both', 184 backtest days Apr-Oct 2026 with truth);
  per day Spearman(field, residual) over launches with the field present (>= 8 launches and >= 2 distinct values), mean over days;
  day bootstrap 95% (4000); coverage = share of launches with the field present.
Step 4 pick: the 3 fields with the largest |mean rho| whose interval excludes 0 go to rawfield_arm2.py (2025 first, then 2026 once).
usage: python rawfield_sweep.py rawfields.parquet L.parquet -> results/rawfield_sweep.{json,md}"""
import json, os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
X = pd.read_parquet(sys.argv[1]); L = pd.read_parquet(sys.argv[2]); L["id"] = L.id.astype(str)
FIELDS = [c for c in X.columns if c not in ("id", "day", "kind")]
SAME = {"media:n": "ph_n_media", "topics.edges:n": "ph_n_topics", "makers:n": "ph_n_makers", "description:len": "ph_desc_len",
        "tagline:len": "ph_tagline_len", "name:len": "ph_name_len", "drv.hunter_age_d_at_create": "ph_hunter_age_d",
        # CORRECTION after the first run (b6b51614): both are the topic count = ph_n_topics; the mapping missed them
        "topics.edges[].node:nonempty": "ph_n_topics", "topics.edges[].node.name:nonempty": "ph_n_topics"}
# CORRECTION after the first run: user.followersCount passed the pre-registered test (Spearman 0.949) but its stored value includes
# post-launch growth that depends on the outcome (log stored/00:05: others +0.89, top 3 +0.06; small hunters 2 -> 31); it is the hunter
# follower count arm 2 already drops as read-at-fetch (history_retrain 'nofol'). Marked leaky; its score is still reported.
POSTHOC_LEAKY = {"user.followersCount": "stored value includes outcome-dependent post-launch follower growth (log stored/00:05: others +0.89, top 3 +0.06)"}
OUTCOME = lambda c: c.split(":")[0] in ("votesCount", "commentsCount", "reviewsCount", "reviewsRating") or "Rank" in c
excl = {}
for c in FIELDS:
    if c in SAME: excl[c] = f"arm-2 input ({SAME[c]})"
    elif c.startswith("makers[]"): excl[c] = "clean policy: needs named makers"
    elif c.split(":")[0] in ("id", "user.id", "createdAt", "featuredAt", "user.createdAt"): excl[c] = "identifier / timestamp text"
cand = [c for c in FIELDS if c not in excl]
S = X[X.kind == "stored"].drop_duplicates("id", keep="last").set_index("id"); T0 = X[X.kind == "t0005"].drop_duplicates("id", keep="last").set_index("id")
both_ids = S.index.intersection(T0.index)
know = {}
for c in cand:
    if OUTCOME(c): know[c] = {"status": "leaky", "why": "outcome field"}; continue
    s = S.loc[both_ids, c]; t = T0.loc[both_ids, c]; m = s.notna()
    if m.sum() < 20: know[c] = {"status": "leaky", "why": f"stored on only {int(m.sum())} launches in the window"}; continue
    pres = float(t[m].notna().mean()); mm = m & t.notna()
    if s[mm].nunique() < 3:
        agree = float((s[mm] == t[mm]).mean()) if mm.any() else 0.0; ok = pres >= 0.8 and agree >= 0.9; stat = {"exact_agree": round(agree, 3)}
    else:
        rho = float(pd.Series(s[mm]).rank().corr(pd.Series(t[mm]).rank())) if mm.sum() > 2 else np.nan; ok = pres >= 0.8 and rho >= 0.9; stat = {"spearman": round(rho, 3)}
    know[c] = {"status": "knowable" if ok else "leaky", "present_0005": round(pres, 3), **stat, "n": int(m.sum())}
    if c in POSTHOC_LEAKY: know[c].update({"status": "leaky", "why": POSTHOC_LEAKY[c]})
K = [c for c, v in know.items() if v["status"] == "knowable" or c in POSTHOC_LEAKY]
# residuals on the 184 scored days
A = pd.read_parquet(R("history_retrain_decomp_preds_arm2.parquet")); A["id"] = A.id.astype(str)
A = A.merge(L[["id", "votes"]], on="id"); A["res"] = np.log1p(A.votes.astype(float)) - A.both
import subprocess
T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json"], capture_output=True, text=True, check=True).stdout)["days"]
days = sorted(d for d in A.day.unique() if len(T.get(d, {}).get("ranks", {})) >= 10)
A = A[A.day.isin(days)].merge(S[K], left_on="id", right_index=True, how="left")
score = {}
rng = np.random.default_rng(0)
for c in K:
    per = []
    for d, g in A.groupby("day"):
        g = g[g[c].notna()]
        if len(g) >= 8 and g[c].nunique() >= 2: per.append(g[c].rank().corr(g.res.rank()))
    per = np.array([p for p in per if np.isfinite(p)])
    if len(per) < 30: score[c] = {"n_days": len(per), "note": "too few days"}; continue
    bs = [per[rng.integers(0, len(per), len(per))].mean() for _ in range(4000)]
    score[c] = {"rho": round(float(per.mean()), 4), "ci": [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)],
                "n_days": len(per), "coverage": round(float(A[c].notna().mean()), 3)}
clear = sorted([c for c, v in score.items() if "ci" in v and (v["ci"][0] > 0 or v["ci"][1] < 0) and c not in POSTHOC_LEAKY], key=lambda c: -abs(score[c]["rho"]))
out = {"method": __doc__, "excluded": excl, "knowability": know, "score": score, "clear_of_zero": clear, "picked": clear[:3],
       "ph_at_launch": "raw/ph_at_launch/<day>/ (posts, makers, products, external, followers, api_*): Oct 4 / Nov 3 onwards; listed, too short to score on 184 days"}
json.dump(out, open(R("rawfield_sweep.json"), "w"), indent=1)
md = ["# Raw-field sweep", "", f"{len(FIELDS)} fields; {len(excl)} excluded (arm-2 input / clean policy / identifier); {len(cand)} candidates; "
      f"{len(K)} knowable at 00:05; {len(clear)} clear of 0 on {len(days)} days.", "",
      "| field | status | 00:05 check | rho with arm-2 residual [95%] | days | coverage |", "|---|---|---|---|---|---|"]
for c in cand:
    k = know[c]; s = score.get(c, {})
    chk = ", ".join(f"{a} {b}" for a, b in k.items() if a not in ("status",))
    md.append(f"| {c} | {k['status']} | {chk} | " + (f"{s['rho']:+.3f} [{s['ci'][0]:+.3f}, {s['ci'][1]:+.3f}]" if "ci" in s else "-") + f" | {s.get('n_days', '-')} | {s.get('coverage', '-')} |")
md += ["", "Excluded: " + "; ".join(f"{c} ({w})" for c, w in excl.items()), "", f"Picked for the arm-2 test: {clear[:3]}"]
open(R("rawfield_sweep.md"), "w").write("\n".join(md) + "\n")
print("\n".join(md))
