"""Hunter reach at 00:05 (orchestrator 08:15Z Nov 17). SHADOW FILE ONLY: no model reads it; collected forward because follow lists are
undated (no leak-free backward test). Frozen at the 00:05 run of launch day D, per launch's hunter:
  hunter_in_store          the hunter's salted person id is in the people store (persons.parquet)
  held_followers_pre       complete people whose following list was pulled before D 00:00 PT (max fetched_at of their follow rows < cut)
                           and who follow the hunter (the follow_shadow.py rule)
  held_followers_active30  of those, how many have an upvote OBSERVED before D 00:00 PT (fetched_at < cut) on another launch dated
                           D-30 .. D-1 (warehouse launches.day)
  eligible_people          complete people with a follow pull before the cut
Ids and counts only (no usernames); the salt is read from <salt dir>/salt and never printed. Redacted hunters (username "[...]" / id "0")
are written with hunter_in_store null.
usage: python hunter_reach.py <today_0005.json (path or gs://)> <D> <store dir> <salt dir> <out.json>"""
import datetime as dt, hashlib, json, os, subprocess, sys
import pandas as pd


def load_json(p):
    return json.loads(subprocess.check_output(["gsutil", "cat", p]) if p.startswith("gs://") else open(p).read())


def launch_days(lo, hi):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import warehouse as W
    L = W.query(f"SELECT CAST(id AS VARCHAR) AS lid, CAST(day AS VARCHAR) AS dday FROM launches WHERE CAST(day AS VARCHAR) >= '{lo}' AND CAST(day AS VARCHAR) < '{hi}'")
    return set(L.lid)


def reach(lineup, day, store, salt_dir):
    salt = open(os.path.join(salt_dir, "salt")).read().strip()
    pid = lambda h: "p_" + hashlib.sha256((salt + "producthunt:" + str(h).lower()).encode()).hexdigest()[:16]
    cut = pd.Timestamp(day + " 00:00").tz_localize("America/Los_Angeles", ambiguous=True).tz_convert("UTC")
    P = pd.read_parquet(os.path.join(store, "persons.parquet"), columns=["person_id", "complete"])
    allp = set(P.person_id); comp = set(P[P.complete].person_id)
    F = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "target_id", "fetched_at"], filters=[("kind", "=", "follows")])
    F = F[F.person_id.isin(comp)]; pulled = F.groupby("person_id").fetched_at.max(); elig = set(pulled[pulled < cut].index)
    by_t = F[F.person_id.isin(elig)].groupby("target_id").person_id.agg(set).to_dict()
    d0 = dt.date.fromisoformat(day); prior = launch_days(str(d0 - dt.timedelta(days=30)), day)
    U = pd.read_parquet(os.path.join(store, "events.parquet"), columns=["person_id", "target_id", "fetched_at"], filters=[("kind", "=", "upvote")])
    U = U[U.person_id.isin(elig) & (U.fetched_at < cut) & U.target_id.astype(str).isin(prior)]
    votes = U.groupby("person_id").target_id.agg(lambda s: set(s.astype(str))).to_dict()
    out = []
    for x in lineup:
        hu = x.get("user") or {}; lid = str(x["id"])
        real = bool(hu.get("username")) and not str(hu["username"]).startswith("[") and str(hu.get("id")) != "0"
        if not real:
            out.append({"launch_id": lid, "hunter_in_store": None, "held_followers_pre": None, "held_followers_active30": None}); continue
        h = pid(hu["username"]); fol = by_t.get(h, set())
        act = sum(1 for p in fol if votes.get(p, set()) - {lid})
        out.append({"launch_id": lid, "hunter_in_store": h in allp, "held_followers_pre": len(fol), "held_followers_active30": act})
    return out, len(elig), len(prior)


if __name__ == "__main__":
    lp, day, store, saltd, outp = sys.argv[1:6]
    rows, ne, npr = reach(load_json(lp), day, store, saltd)
    res = {"day": day, "kind": "hunter_reach_0005", "shadow_only": True, "written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "cut_utc": str(pd.Timestamp(day + " 00:00").tz_localize("America/Los_Angeles").tz_convert("UTC")), "eligible_people": ne,
           "prior_launches_30d": npr, "store": os.path.basename(os.path.normpath(store)), "rule":
           "followers = complete people with a follow pull before D 00:00 PT; active30 = upvote observed before the cut on another launch dated D-30..D-1",
           "launches": rows}
    json.dump(res, open(outp, "w"), indent=1)
    print(json.dumps({"day": day, "launches": len(rows), "eligible_people": ne, "hunters_in_store": sum(1 for r in rows if r["hunter_in_store"]),
                      "with_followers": sum(1 for r in rows if (r["held_followers_pre"] or 0) > 0)}))
