"""Loaders for launch voter lists and follower lists, if the signed-in route makes them visible (orchestrator's ask,
Nov 2; mailbox 20261102T2140_ph_voters_followers_visible). Schema only until the pilot lands; every reader fails loudly
on a missing column.

Expected inputs (bucket, raw/):
  ph_voters/<post_id>.jsonl      username, position, fetched_at          (one launch's upvoter list)
  ph_followers/<kind>/<key>.jsonl  username, fetched_at, plus target and target_kind (maker | hunter | product)
                                 if not implied by the path (<kind> = target_kind, <key> = the target's username or slug)

1. Voters -> events: every listed voter becomes an upvote event on that launch, dated to the launch's Pacific day
   (date_quality launch_day, as PH doesn't expose upvote times), skipping (person, launch) pairs already in events.
   Usernames not in `people` are new people: added with first_seen = the launch day, and queued for the daily
   upvote / following fetch (raw/ph_people_daily queue file, bucket only: never commit usernames).
2. Pool metrics by voter source: for a day, per launch, voters from `events` (what the pool sees today) or from the
   voter lists (all voters); the pool = people first seen before the day. Within-day Spearman of a simulation's
   expected picks with pool voters, and the pool share of all voters (how much of the board the observed population
   can decide once voters are complete).
3. Followers -> dated follows: a (follower, target) pair is dated to the first day it was seen in any fetched list,
   and counts for launches from the next day on (the rule used for the daily following fetch).

usage: python -m pipeline.voters voters <dir> [--dry-run]
       python -m pipeline.voters followers <dir> [--dry-run]
       python -m pipeline.voters poolmetrics <day> <sim json> [events|voters] [voters dir]"""
import glob, gzip, json, os, sys
import pandas as pd

PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ph_predict")
QUEUE = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_people_daily/queue/new_people_{day}.txt"


def need(df, cols, what):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise SystemExit(f"{what}: missing columns {miss}; has {sorted(df.columns)}")


def read_jsonl_dir(path, key_from_name=None):
    files = sorted(glob.glob(os.path.join(path, "**", "*.jsonl*"), recursive=True))
    if not files:
        raise SystemExit(f"no *.jsonl under {path}")
    out = []
    for f in files:
        op = gzip.open if f.endswith(".gz") else open
        with op(f, "rt") as h:
            D = pd.DataFrame([json.loads(l) for l in h if l.strip()])
        if len(D) and key_from_name:
            for k, v in key_from_name(f).items():
                if k not in D:
                    D[k] = v
        out.append(D)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ---------- 1. voters -> events ----------
def voter_events(V, launch_day, have_pairs, known_people):
    """Pure: voter rows (post_id, username, ...) -> (new events, new people). launch_day: {post_id: day}."""
    need(V, ["post_id", "username", "fetched_at"], "ph_voters")
    V = V.assign(post_id=V.post_id.astype(str), username=V.username.astype(str))
    V = V[V.username.ne("") & V.username.ne("[REDACTED]") & V.post_id.isin(launch_day)]
    V = V.drop_duplicates(["post_id", "username"])
    ev = pd.DataFrame({"person": V.username, "launch_id": V.post_id, "date": V.post_id.map(launch_day), "kind": "upvote",
                       "date_quality": "launch_day", "source": "voter_list"})
    ev = ev[[(p, l) not in have_pairs for p, l in zip(ev.person, ev.launch_id)]]
    newp = ev[~ev.person.isin(known_people)].groupby("person").date.min().reset_index().rename(columns={"date": "first_seen"})
    return ev.reset_index(drop=True), newp


def load_voters(path, dry=False):
    from . import warehouse as W
    con = W.connect()
    V = read_jsonl_dir(path, key_from_name=lambda f: {"post_id": os.path.basename(f).split(".")[0]})
    day = dict(con.execute("SELECT id::VARCHAR, day::VARCHAR FROM launches").fetchall())
    have = set(map(tuple, con.execute("SELECT person, launch_id::VARCHAR FROM events WHERE kind = 'upvote'").fetchall()))
    known = {r[0] for r in con.execute("SELECT person FROM people").fetchall()}
    ev, newp = voter_events(V, day, have, known)
    print(json.dumps({"voter_rows": len(V), "launches": int(V.post_id.nunique()) if len(V) else 0, "new_events": len(ev),
                      "new_people": len(newp)}), flush=True)
    if not dry:
        W.write("events", ev)
        if len(newp):
            W.write("people", newp)
            d = str(newp.first_seen.max()); tmp = f"/tmp/new_people_{d}.txt"
            open(tmp, "w").write("\n".join(sorted(newp.person)) + "\n")
            os.system(f"gsutil -q cp {tmp} {QUEUE.format(day=d)}")
    return ev, newp


# ---------- 2. pool metrics by voter source ----------
def pool_metrics(day, sim, voters, votes, pool):
    """Pure. sim: {launch_id: expected picks}; voters: {launch_id: set(usernames)} for that day's launches;
    votes: {launch_id: final votes}; pool: set of people first seen before the day."""
    from scipy.stats import spearmanr
    ids = [x for x in sim if x in voters]
    if len(ids) < 5:
        return None
    pv = [len(voters[x] & pool) for x in ids]; allv = [len(voters[x]) for x in ids]
    rho = spearmanr([sim[x] for x in ids], pv).correlation
    share = [p / v for p, v in zip(pv, [votes.get(x) or a for x, a in zip(ids, allv)]) if v]
    return {"day": day, "launches": len(ids), "pool_spearman": float(rho), "pool_voters": int(sum(pv)),
            "pool_share_of_votes": float(sum(share) / len(share)) if share else None}


def pool_metrics_cli(day, sim_json, source="events", voters_dir=None):
    from . import warehouse as W
    con = W.connect()
    S = json.load(open(sim_json)); sim = {k: v.get("pnx_ev") for k, v in S.items() if v.get("pnx_ev") is not None}
    L = con.execute(f"SELECT id::VARCHAR AS id, votes FROM launches WHERE day::VARCHAR = '{day}'").df()
    votes = dict(zip(L.id, L.votes))
    pool = {r[0] for r in con.execute(f"SELECT person FROM people WHERE first_seen::VARCHAR < '{day}'").fetchall()}
    if source == "voters":
        V = read_jsonl_dir(voters_dir, key_from_name=lambda f: {"post_id": os.path.basename(f).split(".")[0]})
        need(V, ["post_id", "username"], "ph_voters")
        V = V[V.post_id.astype(str).isin(set(L.id))]
        voters = V.groupby(V.post_id.astype(str)).username.apply(set).to_dict()
    else:
        E = con.execute(f"""SELECT launch_id::VARCHAR AS id, person FROM events WHERE kind IN ('upvote', 'comment')
                            AND launch_id::VARCHAR IN (SELECT id::VARCHAR FROM launches WHERE day::VARCHAR = '{day}')""").df()
        voters = E.groupby("id").person.apply(set).to_dict()
    r = pool_metrics(day, sim, voters, votes, pool)
    print(json.dumps({"source": source, **(r or {"day": day, "note": "fewer than 5 launches with voters"})}))
    return r


# ---------- 3. followers -> dated follows ----------
def dated_follows(Fl, have_first_seen):
    """Pure. Follower rows (username, target, target_kind, fetched_at) -> new (follower, target) pairs with first_seen =
    the earliest fetch day, counting from first_seen + 1. have_first_seen: {(follower, target_kind, target): day}."""
    need(Fl, ["username", "target", "target_kind", "fetched_at"], "ph_followers")
    Fl = Fl.assign(day=pd.to_datetime(Fl.fetched_at, utc=True).dt.tz_convert("America/Los_Angeles").dt.strftime("%Y-%m-%d"))
    G = Fl.groupby(["username", "target_kind", "target"]).day.min().reset_index().rename(columns={"username": "person", "day": "first_seen"})
    G = G[[(p, k, t) not in have_first_seen for p, k, t in zip(G.person, G.target_kind, G.target)]]
    G["counts_from"] = (pd.to_datetime(G.first_seen) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    # first_seen is an upper bound: lists are re-read every RESOLUTION_DAYS (Data Feeder reads follows weekly, on Mondays,
    # until daily reads are confirmed), so the follow happened in (first_seen - resolution, first_seen]. counts_from stays
    # honest; don't claim day-precise tie timing from it.
    G["resolution_days"] = int(os.environ.get("RESOLUTION_DAYS", "7"))
    return G.reset_index(drop=True)


def load_followers(path, dry=False):
    from . import warehouse as W
    Fl = read_jsonl_dir(path, key_from_name=lambda f: {"target_kind": os.path.basename(os.path.dirname(f)),
                                                        "target": os.path.basename(f).split(".")[0]})
    try:
        con = W.connect()
        have = {(a, b, c): d for a, b, c, d in con.execute("SELECT person, target_kind, target, first_seen FROM dated_follows").fetchall()}
    except Exception:  # noqa: BLE001  (table not created yet)
        have = {}
    G = dated_follows(Fl, have)
    print(json.dumps({"follower_rows": len(Fl), "new_dated_follows": len(G)}), flush=True)
    if not dry and len(G):
        W.write("dated_follows", G)
    return G


if __name__ == "__main__":
    a = sys.argv[1:]; dry = "--dry-run" in a; a = [x for x in a if x != "--dry-run"]
    if a[0] == "voters":
        load_voters(a[1], dry)
    elif a[0] == "followers":
        load_followers(a[1], dry)
    elif a[0] == "poolmetrics":
        pool_metrics_cli(*a[1:5])
