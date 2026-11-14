"""Hunter-history FORM features at 00:05, as-of (orchestrator 15:21Z Nov 14). From the day files (2025 + 2026; ~/w/h25/data/days).
For a launch on day d hunted by h, history = h's featured hunts on days <= d-2 (labels settled), other launches only. rel = log1p(votes) - the
day's mean log1p(votes). Counts / ids only; hunter ids stay inside the run (never written to the output, which is keyed by launch id).
  hf_last_days, hf_last_rank, hf_last_logv, hf_last_rel         the hunter's most recent earlier hunt
  hf_trend3                                                     rel of the last hunt minus the mean rel of the two before it (needs 3)
  hf_best_rank, hf_n_top3, hf_n_top10                            best-ever final rank, counts of top-3 / top-10 finishes
  hf_topic_rel, hf_topic_n                                       mean rel of earlier hunts sharing >= 1 topic with this launch, their count
  hf_wd_rel, hf_wd_n                                             same weekday
  hf_short_share                                                 share of earlier hunts on short-list days (< 10 ranked launches)
  hf_eb                                                          empirical-Bayes hunter effect: sum(rel) / (n + k), k = within / between
                                                                 variance ratio estimated as-of from hunters with >= 2 hunts on days <= d-2
Not built (not held as-of): hunter-is-maker (maker ids are redacted in the API since 2026) and line-up position share (no historical
00:05 order). usage: python3 hunter_form.py <days dir> <out.parquet>"""
import glob, json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd

R = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    d = os.path.basename(f)[:-5]
    for p in json.load(open(f)):
        tp = p.get("topics") or {}
        ts = [e["node"]["name"] for e in tp.get("edges", [])] if isinstance(tp, dict) else [t if isinstance(t, str) else t.get("name") for t in tp]
        h = (p.get("user") or {}).get("id")
        R.append({"id": str(p["id"]), "day": d, "h": str(h) if h not in (None, "", "0") else None, "votes": p.get("votesCount"),
                  "rank": p.get("dailyRank"), "topics": set(t for t in ts if t)})
L = pd.DataFrame(R).drop_duplicates(["id", "day"])
L["votes"] = pd.to_numeric(L.votes, errors="coerce"); L["rank"] = pd.to_numeric(L["rank"], errors="coerce")
L["lv"] = np.log1p(L.votes); L["rel"] = L.lv - L.groupby("day").lv.transform("mean")
L["short"] = (L.groupby("day")["rank"].transform(lambda s: s.notna().sum()) < 10).astype(float)
L["dt"] = pd.to_datetime(L.day); L["wd"] = L.dt.dt.dayofweek
L = L.sort_values(["day", "id"]).reset_index(drop=True)
days = sorted(L.day.unique()); byday = {d: g for d, g in L.groupby("day")}
H = defaultdict(list)          # hunter -> list of past hunts (added when they become d-2 settled)
added = set(); OUT = []
# running EB moments over settled hunts
def eb_k():
    ns = np.array([len(v) for v in H.values()]); ok = ns >= 2
    if ok.sum() < 20: return 10.0
    means = np.array([np.mean([x["rel"] for x in v]) for v, o in zip(H.values(), ok) if o])
    within = np.mean([np.var([x["rel"] for x in v], ddof=1) for v, o in zip(H.values(), ok) if o])
    between = max(np.var(means, ddof=1) - within / np.mean(ns[ok]), 1e-3)
    return float(np.clip(within / between, 0.5, 50))
for i, d in enumerate(days):
    cut = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    for dd in days[:i]:
        if dd <= cut and dd not in added:
            for r in byday[dd].itertuples():
                if r.h and np.isfinite(r.lv):
                    H[r.h].append({"day": dd, "dt": r.dt, "rank": r.rank, "lv": r.lv, "rel": r.rel, "topics": r.topics, "wd": r.wd, "short": r.short})
            added.add(dd)
    k = eb_k()
    for r in byday[d].itertuples():
        h = [x for x in H.get(r.h, [])] if r.h else []
        o = {"id": r.id, "day": d}
        if h:
            last = h[-1]; rels = [x["rel"] for x in h]; rk = [x["rank"] for x in h if np.isfinite(x["rank"])]
            tp = [x["rel"] for x in h if x["topics"] & r.topics]; wd = [x["rel"] for x in h if x["wd"] == r.wd]
            o.update({"hf_last_days": (r.dt - last["dt"]).days, "hf_last_rank": last["rank"], "hf_last_logv": last["lv"], "hf_last_rel": last["rel"],
                      "hf_trend3": rels[-1] - np.mean(rels[-3:-1]) if len(rels) >= 3 else np.nan,
                      "hf_best_rank": min(rk) if rk else np.nan, "hf_n_top3": sum(x <= 3 for x in rk), "hf_n_top10": sum(x <= 10 for x in rk),
                      "hf_topic_rel": np.mean(tp) if tp else np.nan, "hf_topic_n": len(tp), "hf_wd_rel": np.mean(wd) if wd else np.nan, "hf_wd_n": len(wd),
                      "hf_short_share": np.mean([x["short"] for x in h]), "hf_eb": sum(rels) / (len(rels) + k)})
        else:
            o.update({"hf_n_top3": 0, "hf_n_top10": 0, "hf_topic_n": 0, "hf_wd_n": 0, "hf_eb": 0.0})
        OUT.append(o)
O = pd.DataFrame(OUT); O.to_parquet(sys.argv[2])
print(json.dumps({"launches": len(O), "days": len(days), "with_history": round(float(O.hf_last_days.notna().mean()), 3),
                  "cols": [c for c in O.columns if c.startswith("hf_")]}))
