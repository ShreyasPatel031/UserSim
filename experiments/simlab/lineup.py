"""Line-up test: on days a real person was active on Product Hunt (upvoted or commented on that day's launches, so
they saw the list), their persona (built only from what was known before that day) sees the day's whole line-up
and picks the 3 it would upvote. Separates appeal from exposure: everyone tested here did see the list.
Scored:
  person   share of person-days where a real pick is among the persona's 3 (vs random 3 of n, vs "picks the
           baseline model's top 3"), split by whether the person follows the launch's team
  launch   picks summed over all persona-days -> a score per launch for the harness (experiments/lineup_picks.py)
usage: python -m simlab.lineup run 2026-09-01 2026-10-24 [threads]   (resumable; cache/lineup_picks.jsonl)
       python -m simlab.lineup score"""
import json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
from . import store
from .persona import CACHE, card, gemini

PER_CALL = 5
PROMPT = """You are simulating real Product Hunt users. Today's launches on the homepage:
{lineup}

For each person below, pick the 3 launches they would most likely upvote today, true to their role, interests and
what they have backed before. Reply with JSON only: [{{"id": <person n>, "picks": [<launch number>, <launch number>, <launch number>]}}, ...]

People:
{people}"""
lock = threading.Lock()


def jobs(day_from, day_to):
    people, items, events = store.load()
    day_of = dict(zip(items.id, items.day))
    ev = events[events.item.isin(day_of)].copy(); ev["iday"] = ev.item.map(day_of)
    pdict = people.set_index("person").to_dict("index")
    names = {r.id: f"{r.name} ({r.tagline[:60]})" for r in items.itertuples()}
    ev = ev.sort_values("date")
    hist = ev.groupby("person").apply(lambda g: list(zip(g.date, g.item)), include_groups=False).to_dict()
    act = ev[(ev.date == ev.iday) & ev.date.between(day_from, day_to)]
    for d, g in act.groupby("date"):
        line = items[items.day == d].sort_values("id")
        lineup = list(line.id)
        people_d = [u for u in g.person.unique() if u in pdict]
        for i in range(0, len(people_d), PER_CALL):
            chunk = people_d[i:i + PER_CALL]
            cards = []
            for u in chunk:
                h = [it for dt, it in hist.get(u, []) if dt < d]
                nm = {k: names[it] for k, it in enumerate(h)}
                cards.append(card(pdict[u], list(range(len(h))), nm, d))
            yield d, lineup, [f"{k + 1}. {names[x]}" for k, x in enumerate(lineup)], chunk, cards


def run(day_from, day_to, threads=32):
    os.makedirs(CACHE, exist_ok=True)
    out = f"{CACHE}/lineup_picks.jsonl"
    done = {(json.loads(l)["day"], json.loads(l)["people"][0]) for l in open(out)} if os.path.exists(out) else set()
    J = [j for j in jobs(day_from, day_to) if (j[0], j[3][0]) not in done]
    print("requests", len(J), flush=True)

    def one(j):
        d, lineup, lines, chunk, cards = j
        txt = gemini(PROMPT.format(lineup="\n".join(lines), people="\n".join(f"{k}. {c}" for k, c in enumerate(cards))))
        try:
            got = {int(o["id"]): [int(x) for x in o.get("picks", [])][:3] for o in json.loads(re.search(r"\[.*\]", txt, re.S).group(0))}
        except Exception:  # noqa: BLE001
            got = {}
        rec = {"day": d, "people": chunk, "picks": [[lineup[x - 1] for x in got.get(k, []) if 1 <= x <= len(lineup)] for k in range(len(chunk))]}
        with lock, open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, J))


def score():
    from . import harness
    people, items, events = store.load()
    day_of = dict(zip(items.id, items.day)); n_day = items.groupby("day").size().to_dict()
    real = events[events.item.map(day_of) == events.date].groupby(["person", "date"]).item.apply(set).to_dict()
    fol = {r.person: set(json.loads(r.follows)) if isinstance(r.follows, str) else set() for r in people.itertuples()}
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in items.itertuples()}
    B = harness.baseline(); B["r"] = B.groupby("day").base.rank(ascending=False, method="first")
    base_top = B[B.r <= 3].groupby("day").id.apply(set).to_dict()
    rows, votes = [], {}
    for l in open(f"{CACHE}/lineup_picks.jsonl"):
        r = json.loads(l)
        for u, picks in zip(r["people"], r["picks"]):
            if not picks:
                continue
            truth = real.get((u, r["day"]), set())
            if not truth:
                continue
            for x in picks:
                votes[x] = votes.get(x, 0) + 1
            fol_truth = {x for x in truth if fol.get(u, set()) & team.get(x, set())}
            rows.append({"hit": bool(truth & set(picks)), "base_hit": bool(truth & base_top.get(r["day"], set())),
                         "random": 1 - np.prod([1 - 3 / max(n_day[r["day"]] - j, 3) for j in range(len(truth))]),
                         "follows_a_pick": bool(fol_truth), "hit_followed": bool(fol_truth & set(picks)),
                         "hit_not_followed": bool((truth - fol_truth) & set(picks))})
    R = pd.DataFrame(rows)
    nf = R[~R.follows_a_pick]
    print(f"person-days {len(R)}")
    print(f"persona's 3 picks contain a real pick: {R.hit.mean():.1%}   random: {R.random.mean():.1%}   "
          f"baseline's top 3 for everyone: {R.base_hit.mean():.1%}")
    print(f"  where the person follows a team they upvoted ({R.follows_a_pick.mean():.0%} of days): persona {R[R.follows_a_pick].hit.mean():.1%}")
    print(f"  where they don't: persona {nf.hit.mean():.1%}, baseline top 3 {nf.base_hit.mean():.1%}, random {nf.random.mean():.1%}")
    pd.DataFrame([{"id": k, "lineup_votes": v} for k, v in votes.items()]).to_parquet(f"{CACHE}/lineup_scores.parquet")
    R.to_parquet(f"{CACHE}/lineup_person_eval.parquet")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 32)
    else:
        score()
