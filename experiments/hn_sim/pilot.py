"""Phase 1 pilot: the four arms on the pilot posts, then score.py.

    python pilot.py <post_id> [<post_id> ...]   (ids from PILOT)
Browser runs go through browser.py (Atelier human mode). Writes sim_runs and sim_comments; logs measured spend."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import arms as A
import browser
import llm
import store as S
from snapcheck import bb_minutes


def target_url(post: dict, where: str) -> str:
    if where == "live":
        return post["url"]
    import datetime as dt
    ts = dt.datetime.fromtimestamp(post["created_at_i"], dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"https://web.archive.org/web/{ts}/{post['url']}"


PILOT = {49937304: "wayback", 49995539: "wayback", 49997971: "wayback", 50074909: "wayback", 50137950: "wayback",
         50090932: "wayback", 49928566: "live", 50024499: "live", 50077020: "live", 50151980: "live"}
# Wayback copy works and the model does not claim to know the product (6), else the live site (4); snapcheck.py.


def main(ids: list[int], workers: int = 12) -> None:
    allp = S.read("hn_posts").drop_duplicates("post_id").set_index("post_id")
    ordered = sorted((dict(allp.loc[i], post_id=i) for i in PILOT), key=lambda p: p["created_at_i"])
    donor = {p["post_id"]: ordered[(k + 1) % len(ordered)] for k, p in enumerate(ordered)}   # D: next post's commenters
    posts = [p for p in ordered if p["post_id"] in ids]
    jobs = []   # (post, arm, slot, person, who, persona)
    for p in posts:
        real = A.pick_people(p)
        for k, person in enumerate(real):
            cd = A.card(person, p["created_at_i"], A.history(person, p["post_id"], p["created_at_i"]))
            jobs.append((p, "A_twin", k, person, A.card_text(cd), cd.get("persona"), cd))
        d = donor[p["post_id"]]
        cutoff = min(d["created_at_i"], p["created_at_i"])
        for k, person in enumerate(A.pick_people(d)[:len(real)]):
            cd = A.card(person, cutoff, A.history(person, d["post_id"], cutoff))
            jobs.append((p, "D_shuffled", k, person, A.card_text(cd), cd.get("persona"), cd))
        gp = A.generic_personas(p["url"])[:len(real)]
        for k, g in enumerate(gp):
            who = f"{g.get('name')}, {g.get('role')}. {g.get('bio')}"
            jobs.append((p, "B_generic", k, g.get("name"), who, who, g))
    print(f"{len(jobs)} browser runs on {len(posts)} posts", flush=True)
    m0, t0 = bb_minutes(), time.time()

    def one(j):
        p, arm, k, person, who, persona, cd = j
        r = browser.run(target_url(p, PILOT[p["post_id"]]), persona or who, A.TASK.format(title=p["title"], text=(p["text"] or "")[:1200]),
                        max_actions=A.MAX_ACTIONS, tag=arm)
        return j, r, A.write(p, who, r, seed=k)
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, jobs))
    m1 = bb_minutes()
    page = {p["post_id"]: A.page_only(p) for p in posts}
    runs, comments = [], []
    for (p, arm, k, person, who, persona, cd), r, c in res:
        runs.append({"post_id": p["post_id"], "arm": arm, "slot": k, "person": person, "where": PILOT[p["post_id"]],
                     "card": json.dumps(cd, default=str), "session_id": r.get("session_id"), "watch_url": r.get("watch_url"),
                     "url": r.get("url"), "outcome": r.get("outcome"), "actions": r.get("actions"),
                     "seconds": r.get("seconds"), "model_usd": r.get("model_usd"), "error": r.get("error"),
                     "worked": r.get("worked"), "observations": json.dumps(r.get("observations")),
                     "steps": json.dumps(r.get("steps"))[:200000], "notes": r.get("notes"), "ran_on": S.now()})
        comments.append({"post_id": p["post_id"], "arm": arm, "slot": k, "person": person, **c, "written_on": S.now()})
    for pid, cs in page.items():
        comments += [{"post_id": pid, "arm": "C_page", "slot": k, "person": None, **c, "written_on": S.now()}
                     for k, c in enumerate(cs)]
    R = pd.DataFrame(runs)
    S.write("sim_runs", R)
    S.write("sim_comments", pd.DataFrame(comments))
    meter = llm.meter()
    usd = llm.flush_spend("hn_pilot_arms", f"{len(posts)} posts, {len(jobs)} browser runs")
    print(json.dumps(meter, indent=1))
    print(f"model ${usd:.3f}  wall {time.time() - t0:.0f}s  browserbase minutes delta (account-wide) "
          f"{(m1 - m0) if m0 is not None and m1 is not None else 'n/a'}")
    print(R.groupby("arm").agg(runs=("arm", "size"), worked=("worked", "mean"), errors=("error", lambda s: s.notna().sum()),
                               actions=("actions", "mean"), seconds=("seconds", "mean"), usd=("model_usd", "mean")).round(3))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+", type=int)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    main(a.ids, a.workers)
