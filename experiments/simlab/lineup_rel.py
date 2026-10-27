"""Line-up test v2: personas that know their relationships. Same days and people as lineup.py (they were active,
so they saw the list), but each person's line-up marks, for every launch, how they are tied to its team (all dated
before the day except follows, which are read today):
  follows        they follow the poster or a maker
  backed         times they upvoted/commented on this team's earlier launches
  supported_by   times this team commented on launches the person built
and the day's 5 launches the baseline model expects to lead are marked "on top of the page".
Compared on the same person-days with the formula "popularity + follows" (54% in the first test).
usage: python -m simlab.lineup_rel run [n_person_days] [threads]; python -m simlab.lineup_rel score"""
import json, os, random, re, sys, threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
from . import store, harness
from .persona import CACHE, card, gemini

OUT = f"{CACHE}/lineup_rel_picks.jsonl"
PROMPT = """You are simulating real Product Hunt users deciding what to upvote today. Each person sees today's
homepage. Marks after a launch say how THIS person is connected to its team, and which launches sit on top of the page.
People mostly upvote launches by people they know and the ones leading the page; pick what this person would really do.

Today's launches:
{lineup}

People (with their connections to today's launches):
{people}

For each person pick the 3 launches they would most likely upvote. Reply with JSON only:
[{{"id": <person n>, "picks": [<launch number>, <launch number>, <launch number>]}}, ...]"""
lock = threading.Lock()


def build(n, seed=0):
    people, items, events = store.load()
    day_of = dict(zip(items.id, items.day))
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in items.itertuples()}
    fol = {r.person: set(json.loads(r.follows)) if isinstance(r.follows, str) else set() for r in people.itertuples()}
    pdict = people.set_index("person").to_dict("index")
    names = {r.id: f"{r.name} ({r.tagline[:60]})" for r in items.itertuples()}
    ev = events[events.item.isin(day_of)].sort_values("date")
    by_person = ev.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    built = defaultdict(list)
    for i, t in team.items():
        for m in t:
            built[m].append(i)
    B = harness.baseline(); B["r"] = B.groupby("day").base.rank(ascending=False, method="first")
    top = B[B.r <= 5].groupby("day").id.apply(set).to_dict()
    act = ev[(ev.date == ev.item.map(day_of)) & ev.date.between("2026-09-01", "2026-10-24")]
    days = sorted(act.date.unique()); test_days = set(days[1::2])  # the first test's held-out half
    pd_ = [(u, d) for (u, d) in act[act.date.isin(test_days)].groupby(["person", "date"]).size().index if u in pdict]
    random.Random(seed).shuffle(pd_)
    out = []
    for u, d in pd_[:n]:
        line = sorted(i for i, dd in day_of.items() if dd == d)
        hist = [it for dt, it in by_person.get(u, []) if dt < d]
        backed = Counter(m for it in hist for m in team[it])
        supp = Counter()
        for it in built.get(u, []):
            if day_of[it] < d:
                for dt, it2 in []:  # placeholder kept simple: supporters counted below
                    pass
        marks = []
        for k, x in enumerate(line):
            f = bool(fol.get(u, set()) & team[x]); b = sum(backed[m] for m in team[x])
            s = sum(1 for m in team[x] for dt, it in by_person.get(m, []) if dt < d and u in team.get(it, set()))
            tags = (["you follow its team"] if f else []) + ([f"you backed this team {b}x before"] if b else []) + \
                   ([f"this team supported your launches {s}x"] if s else [])
            if tags:
                marks.append(f"launch {k + 1}: " + ", ".join(tags))
        nm = {j: names[it] for j, it in enumerate(hist)}
        c = card(pdict[u], list(range(len(hist))), nm, d)
        out.append({"person": u, "day": d, "lineup": line, "card": c + (" | connections: " + "; ".join(marks) if marks else " | connections: none"),
                    "lines": [f"{k + 1}. {names[x]}" + (" [on top of the page]" if x in top.get(d, set()) else "") for k, x in enumerate(line)]})
    return out


def run(n=500, threads=40):
    jobs = build(n)
    by_day = defaultdict(list)
    for j in jobs:
        by_day[j["day"]].append(j)
    calls = [(d, g[i:i + 5]) for d, g in by_day.items() for i in range(0, len(g), 5)]
    print("person-days", len(jobs), "requests", len(calls), flush=True)

    def one(c):
        d, grp = c
        txt = gemini(PROMPT.format(lineup="\n".join(grp[0]["lines"]), people="\n".join(f"{k}. {j['card']}" for k, j in enumerate(grp))))
        try:
            got = {int(o["id"]): [int(x) for x in o.get("picks", [])][:3] for o in json.loads(re.search(r"\[.*\]", txt, re.S).group(0))}
        except Exception:  # noqa: BLE001
            got = {}
        with lock, open(OUT, "a") as f:
            for k, j in enumerate(grp):
                f.write(json.dumps({"person": j["person"], "day": d, "picks": [j["lineup"][x - 1] for x in got.get(k, []) if 1 <= x <= len(j["lineup"])]}) + "\n")

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, calls))


def score():
    people, items, events = store.load()
    day_of = dict(zip(items.id, items.day))
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in items.itertuples()}
    fol = {r.person: set(json.loads(r.follows)) if isinstance(r.follows, str) else set() for r in people.itertuples()}
    real = events[events.item.map(day_of) == events.date].groupby(["person", "date"]).item.apply(set).to_dict()
    B = harness.baseline(); B["pb"] = B.groupby("day").base.rank(pct=True); bp = dict(zip(B.id, B.pb))
    v1 = {}
    for l in open(f"{CACHE}/lineup_picks.jsonl"):
        r = json.loads(l)
        for u, pk in zip(r["people"], r["picks"]):
            v1[(u, r["day"])] = set(pk)
    rows = []
    for l in open(OUT):
        r = json.loads(l); u, d = r["person"], r["day"]; t = real.get((u, d))
        if not t or not r["picks"]:
            continue
        line = [i for i, dd in day_of.items() if dd == d]
        s = sorted(line, key=lambda x: -(bp.get(x, 0) + (1 if fol.get(u, set()) & team[x] else 0)))[:3]
        rows.append({"v2": bool(t & set(r["picks"])), "formula": bool(t & set(s)), "v1": bool(t & v1.get((u, d), set()))})
    R = pd.DataFrame(rows)
    print(f"person-days {len(R)}: persona v2 (relationships) {R.v2.mean():.1%} | formula popularity+follows {R.formula.mean():.1%} | persona v1 {R.v1.mean():.1%}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 500, int(sys.argv[3]) if len(sys.argv) > 3 else 40)
    else:
        score()
