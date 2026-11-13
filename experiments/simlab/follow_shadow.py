"""Nightly shadow feature: before-launch held-follower count of each launch team (orchestrator 04:55Z Nov 13). SCRIPT ONLY - not scheduled.
Run at about 00:10 PT on the launch day D, after the 00:05 read exists.
Team = the hunter (user) + every maker named in that day's 00:05 read (today_0005.json); redacted members (username "[REDACTED]" / id "0") are skipped. Held followers = complete people of the people store
whose following tab was PULLED BEFORE D 00:00 PT (events.fetched_at of their follow rows), so every counted edge provably predates the
launch. Edges from pulls made at or after D 00:00 PT are ignored. Output per launch (no usernames, ids only):
  launch_id, n_team, held_followers_pre (distinct held people following >= 1 team member), held_followers_all (all edges, leaky reference
  for evaluation only - do not use as a feature), hunter_followers_ph (followersCount in the 00:05 read), team_followers_ph_max,
  pre_per_1k_hunter_followers, eligible_people (held people pulled before D 00:00 PT).
    python follow_shadow.py <today_0005.json (local path or gs://...)> <launch day YYYY-MM-DD> <store dir> <salt dir> <out .jsonl>
"""
import hashlib, json, os, subprocess, sys
import pandas as pd
def load_json(p):
    return json.loads(subprocess.check_output(["gsutil", "cat", p]) if p.startswith("gs://") else open(p).read())
def features(lineup, day, store, salt_dir):
    salt = open(os.path.join(salt_dir, "salt")).read().strip(); pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    cut = pd.Timestamp(day + " 00:00").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
    P = pd.read_parquet(os.path.join(store, "persons.parquet")); comp = set(P[P.complete].person_id)
    E = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "kind", "target_id", "fetched_at"])
    F = E[(E.kind == "follows") & E.person_id.isin(comp)]; pulled = F.groupby("person_id").fetched_at.max()
    elig = set(pulled[pulled < cut].index); by_t_all = F.groupby("target_id").person_id.agg(set).to_dict()
    Fp = F[F.person_id.isin(elig)]; by_t_pre = Fp.groupby("target_id").person_id.agg(set).to_dict(); out = []
    for x in lineup:
        hu = (x.get("user") or {}); mk = [m for m in (x.get("makers") or []) if m.get("username")]
        real = lambda u: bool(u.get("username")) and not str(u["username"]).startswith("[") and str(u.get("id")) != "0"
        team = {pid(u["username"]) for u in [hu] + mk if real(u)}
        pre = set().union(*[by_t_pre.get(t, set()) for t in team]) if team else set(); al = set().union(*[by_t_all.get(t, set()) for t in team]) if team else set()
        hf = hu.get("followersCount") if real(hu) else None; tf = max([u.get("followersCount") or 0 for u in [hu] + mk if real(u)] or [0])
        out.append({"launch_id": str(x["id"]), "day": day, "n_team": len(team), "held_followers_pre": len(pre), "held_followers_all": len(al),
                    "hunter_followers_ph": hf, "team_followers_ph_max": tf, "pre_per_1k_hunter_followers": round(len(pre) / hf * 1000, 3) if hf else None,
                    "eligible_people": len(elig)})
    return out
if __name__ == "__main__":
    lp, day, store, saltd, outp = sys.argv[1:6]; rows = features(load_json(lp), day, store, saltd)
    with open(outp, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    print("wrote", len(rows), "launches; eligible people", rows[0]["eligible_people"] if rows else 0)
