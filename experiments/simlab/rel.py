"""Relationship signals from the Phase 1 pulls (screening-sample people), per (person, launch, day):
  followed_by_team  a maker/poster of the launch follows the person (followers page 1; read today: undated)
  hunted_team       the person posted (hunted) an earlier launch made by this team (dated by that launch's day)
  x_mentions_team   the person's X posts before the day mention the team's or company's X handle (Sep-Oct launches)
Coverage report: simlab/reports/phase1_coverage.md"""
import gzip, json, os, re
from collections import defaultdict
import numpy as np, pandas as pd
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))


def load_sources():
    tabs = defaultdict(dict)
    for l in open(f"{store.RAW}/sample_tabs.jsonl"):
        r = json.loads(l); tabs[r["username"]][r["tab"]] = r["items"]
    x = {}
    for l in open(f"{store.RAW}/x_sample.jsonl"):
        r = json.loads(l); x[r["handle"].lower()] = r
    li = {}
    for l in open(f"{store.RAW}/li_apify.jsonl"):
        r = json.loads(l)
        if r.get("u"):
            li[r["u"]] = r["profile"]
    return tabs, x, li


def features(D):
    P, I, E = store.load()
    tabs, X, LI = load_sources()
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in I.itertuples()}
    day = dict(zip(I.id, I.day))
    handles = {}
    for h in json.load(open(f"{store.RAW}/sepoct_handles.json")):
        hs = {x.lower().lstrip("@") for x in (h.get("makers_x") or []) + ([h["company_x"]] if h.get("company_x") else []) if x}
        handles[h["id"]] = hs
    tw = dict(zip(P.person, P.twitter))
    fb = [];  ht = []; xm = []
    for u, it, d in zip(D.person, D.id, D.day):
        t = team.get(it, set())
        fol = set(tabs.get(u, {}).get("followers") or [])
        fb.append(float(bool(fol & t)))
        sub = [s for s in tabs.get(u, {}).get("submitted") or [] if s.get("id") in day and day[s["id"]] < d]
        ht.append(float(any(team.get(s["id"], set()) & t for s in sub)))
        posts = (X.get(str(tw.get(u) or "").lower().lstrip("@")) or {}).get("posts") or []
        hs = handles.get(it, set())
        txt = " ".join((p.get("text") or "").lower() for p in posts if (p.get("created_at") or "9") < d)
        xm.append(float(bool(hs) and any(f"@{h}" in txt for h in hs)))
    D["followed_by_team"], D["hunted_team"], D["x_mentions_team"] = fb, ht, xm
    return D


def coverage(people):
    tabs, X, LI = load_sources()
    P = store.load()[0].set_index("person")
    rows = []
    for u in people:
        t = tabs.get(u, {}); tw = str(P.twitter.get(u) or "").lower().lstrip("@")
        rows.append({"activity items": len(t.get("activity") or []), "collections": len(t.get("collections") or []),
                     "hunted launches": len(t.get("submitted") or []), "followers listed": len(t.get("followers") or []),
                     "X posts": len((X.get(tw) or {}).get("posts") or []), "full LinkedIn": int(u in LI),
                     "LinkedIn experience items": len((LI.get(u) or {}).get("experience") or [])})
    C = pd.DataFrame(rows)
    lines = ["| Source | Share of people with any | Median (among those with any) |", "|---|---|---|"]
    for c in C.columns:
        v = C[c]; nz = v[v > 0]
        lines.append(f"| {c} | {(v > 0).mean():.0%} | {int(nz.median()) if len(nz) else 0} |")
    return "\n".join(lines)


if __name__ == "__main__":
    from .variants import sample
    people = sorted({u for u, _ in sample()})
    os.makedirs(f"{HERE}/reports", exist_ok=True)
    open(f"{HERE}/reports/phase1_coverage.md", "w").write(f"# Phase 1 coverage ({len(people)} screening-sample people)\n\n" + coverage(people) + "\n")
    print(open(f"{HERE}/reports/phase1_coverage.md").read())
