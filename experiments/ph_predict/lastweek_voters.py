"""Per-voter file for the last-week window (population agent, Nov 10 09:14Z): who voted on Oct 29 - Nov 4 PT launches, how
many of those votes we see, how many fell on each day's top 3, whether the person is COMPLETE (latest_complete.txt), so the
fleet queue can be ordered by the votes each person adds toward 80% complete-only coverage.

Votes seen per person = warehouse pool upvotes (events) U store_v3 upvotes, on window launches with final votes, deduped
by salted id x launch (same sources as pool_size.py's lastweek_block). Handles: salted ids mapped back through the same
name sources as priority_lastweek.py; unmapped salted ids are counted, not listed.
Order: incomplete people first by votes_uncovered (their votes_in_window), then votes_on_top3, then handle; complete people
after (votes_uncovered 0). Writes gs://.../raw/_pacetest/lastweek_voters.tsv (bucket only: it has handles).
Columns: handle, votes_in_window, votes_on_top3, complete, votes_uncovered. Prints counts only; the salt is never printed.
usage: python lastweek_voters.py [from_day to_day]"""
import hashlib, json, os, subprocess, sys, tempfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUT_GS = os.environ.get("OUT_GS", f"{B}/raw/_pacetest/lastweek_voters.tsv")


def sh(*a, check=False):
    return subprocess.run(list(a), capture_output=True, text=True, check=check)


def hid(sl, u):
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def main(d0="2026-10-29", d1="2026-11-04"):
    from pipeline import warehouse as W
    tmp = tempfile.mkdtemp(prefix="lwv_")
    sl = sh("gsutil", "cat", f"{B}/raw/population/_salt", check=True).stdout.strip()
    L = W.query(f"SELECT id::VARCHAR AS id, daily_rank FROM launches WHERE day::VARCHAR BETWEEN '{d0}' AND '{d1}' AND daily_rank IS NOT NULL")
    ids = set(L.id); top3 = set(L[L.daily_rank <= 3].id)
    E = W.query("SELECT lower(person) AS person, launch_id::VARCHAR AS id FROM events WHERE kind = 'upvote'", do_sync=False)
    E = E[E.id.isin(ids)].drop_duplicates()
    sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/events.parquet", tmp, check=True)
    V = pd.read_parquet(f"{tmp}/events.parquet", columns=["person_id", "kind", "target_id"])
    V = V[(V.kind == "upvote") & V.target_id.astype(str).isin(ids)]
    U = pd.concat([pd.DataFrame({"pid": E.person.map(lambda u: hid(sl, u)), "id": E.id}),
                   pd.DataFrame({"pid": V.person_id, "id": V.target_id.astype(str)})]).drop_duplicates()
    # names to map salted ids back (same sources as priority_lastweek.py)
    names = set(E.person) | set(W.query("SELECT DISTINCT lower(person) AS p FROM people", do_sync=False).p)
    r = sh("gsutil", "cat", f"{B}/raw/_babysitter/quality/latest_complete.txt")
    lc = {l.split("\t")[0].strip().lower() for l in r.stdout.splitlines() if l.strip()}
    if r.returncode or not lc:
        raise SystemExit("latest_complete.txt unreadable; not writing")
    names |= lc
    r = sh("gsutil", "cat", f"{B}/raw/population/user_id_map/user_id_map_20261103.jsonl")
    names |= {str(json.loads(l).get("username", "")).lower() for l in r.stdout.splitlines() if l.strip()}
    r = sh("gsutil", "cat", f"{B}/raw/ph_population/discovery_voternet_20261104/candidates_ranked.jsonl")
    names |= {str(json.loads(l).get("handle", "")).lower() for l in r.stdout.splitlines() if l.strip()}
    for path in (f"{B}/raw/ph_population/people_live/vm/", f"{B}/raw/ph_population/people_live/vm/deep_list/"):
        r = sh("gsutil", "ls", path)
        names |= {os.path.basename(l.strip()).split(".")[0].lower() for l in r.stdout.splitlines() if l.strip().endswith(".json")}
    h2u = {hid(sl, u): u for u in names if u}
    comp = {hid(sl, u) for u in lc}
    g = U.assign(t3=U.id.isin(top3)).groupby("pid").agg(votes_in_window=("id", "size"), votes_on_top3=("t3", "sum")).reset_index()
    g["handle"] = g.pid.map(h2u); g["complete"] = g.pid.isin(comp)
    g["votes_uncovered"] = g.votes_in_window.where(~g.complete, 0)
    known = g[g.handle.notna()].sort_values(["complete", "votes_uncovered", "votes_on_top3", "handle"], ascending=[True, False, False, True])
    loc = f"{tmp}/lastweek_voters.tsv"
    known[["handle", "votes_in_window", "votes_on_top3", "complete", "votes_uncovered"]].to_csv(loc, sep="\t", index=False)
    sh("gsutil", "-q", "cp", loc, OUT_GS, check=True)
    inc = known[~known.complete]
    rep = {"window": [d0, d1], "launches_final": len(ids), "real_votes": int(W.query(f"SELECT sum(votes) v FROM launches WHERE day::VARCHAR BETWEEN '{d0}' AND '{d1}' AND daily_rank IS NOT NULL", do_sync=False).v.iloc[0]),
           "voters_seen": int(len(g)), "votes_seen": int(g.votes_in_window.sum()), "listed_with_handle": int(len(known)),
           "unmapped_voters": int(g.handle.isna().sum()), "unmapped_votes": int(g[g.handle.isna()].votes_in_window.sum()),
           "complete_voters": int(known.complete.sum()), "complete_votes": int(known[known.complete].votes_in_window.sum()),
           "incomplete_voters": int(len(inc)), "incomplete_votes": int(inc.votes_in_window.sum()),
           "incomplete_votes_top3": int(inc.votes_on_top3.sum()),
           "incomplete_top_1000_votes": int(inc.votes_uncovered.head(1000).sum()), "out": OUT_GS}
    print(json.dumps(rep))
    return rep


if __name__ == "__main__":
    main(*sys.argv[1:3])
