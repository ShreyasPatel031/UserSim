"""Priority list for whole-person pulls (Shreyas via the orchestrator, Nov 5 07:30Z): people most likely to have voted on
last week's launches (Oct 29 - Nov 4 PT), ranked, not yet whole in the store. The pace runner pulls from it first.

Evidence per person (store_v3 salted person_id, or a handle hashed with the salt to match):
  up    upvotes on last week's launches (warehouse events + store_v3 events, deduped by launch)
  cm    comments on them (warehouse + store_v3 + the at-launch API commenters via the user id map)
  fol   follows of last week's makers / hunters (store_v3 follows to their salted ids + makers.jsonl followers_page1)
  vn    voter-network connections (raw/ph_population/discovery_voternet_20261104/candidates_ranked.jsonl)
score = 4*up + 3*cm + 2*min(fol, 5) + 0.3*min(vn, 10). Ties by handle.
Excluded: people already whole in store_v3 (full pull, no tab cut short by our code: completeness_watch.short_kind) and
people the pace runner already pulled whole (raw/_pacetest/shared/ and raw/_pacetest/<vm>/ <handle>.json).
Only people with a known handle can be listed (a pull needs the handle); unmapped salted ids are counted.
Writes gs://.../raw/_pacetest/priority_lastweek.txt (one handle per line, best first); bucket only (it has handles).
Prints counts only. The salt (raw/population/_salt) is read to match and never printed.
usage: python priority_lastweek.py [from_day to_day]"""
import glob, hashlib, json, os, subprocess, sys, tempfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
OUT_GS = os.environ.get("OUT_GS", f"{B}/raw/_pacetest/priority_lastweek.txt")


def sh(*a, check=False):
    return subprocess.run(list(a), capture_output=True, text=True, check=check)


def hid(sl, u):
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def main(d0="2026-10-29", d1="2026-11-04"):
    from pipeline import warehouse as W
    from completeness_watch import short_kind
    tmp = tempfile.mkdtemp(prefix="plw_")
    sl = sh("gsutil", "cat", f"{B}/raw/population/_salt", check=True).stdout.strip()
    L = W.query(f"SELECT id::VARCHAR AS id, day::VARCHAR AS day, makers, poster FROM launches WHERE day::VARCHAR BETWEEN '{d0}' AND '{d1}'")
    ids = set(L.id)
    E = W.query("SELECT lower(person) AS person, launch_id::VARCHAR AS id, kind FROM events WHERE kind IN ('upvote','comment')", do_sync=False)
    E = E[E.id.isin(ids)].drop_duplicates()
    people = W.query("SELECT DISTINCT lower(person) AS p FROM people", do_sync=False).p
    for f in ("events", "tabs"):
        sh("gsutil", "-q", "cp", f"{B}/raw/population/store_v3/{f}.parquet", tmp, check=True)
    V = pd.read_parquet(f"{tmp}/events.parquet", columns=["person_id", "kind", "target_id"])
    T = pd.read_parquet(f"{tmp}/tabs.parquet")
    # names we can map salted ids back to
    names = set(people) | set(E.person)
    team = set()
    for m, p in zip(L.makers, L.poster):
        try:
            team |= {str(x).lower() for x in json.loads(m or "[]")}
        except Exception:  # noqa: BLE001
            pass
        if p:
            team.add(str(p).lower())
    names |= team
    sh("gsutil", "-q", "cp", f"{B}/raw/population/user_id_map/user_id_map_20261103.jsonl", tmp)
    idmap = {}
    if os.path.exists(f"{tmp}/user_id_map_20261103.jsonl"):
        for l in open(f"{tmp}/user_id_map_20261103.jsonl"):
            r = json.loads(l); u = str(r.get("username", "")).lower(); names.add(u); idmap[str(r.get("user_id"))] = u
    vn = {}
    r = sh("gsutil", "cat", f"{B}/raw/ph_population/discovery_voternet_20261104/candidates_ranked.jsonl")
    for l in r.stdout.splitlines():
        x = json.loads(l); u = str(x.get("handle", "")).lower(); vn[u] = int(x.get("voter_connections") or 0); names.add(u)
    mf = {}   # makers' first-page followers on at-launch days in the window
    cmh = {}  # at-launch API commenters
    for d in pd.date_range(d0, d1).strftime("%Y-%m-%d"):
        r = sh("gsutil", "cat", f"{B}/raw/ph_at_launch/{d}/makers.jsonl")
        for l in r.stdout.splitlines():
            x = json.loads(l)
            for f in x.get("followers_page1") or []:
                if isinstance(f, dict) and f.get("username"):
                    u = f["username"].lower(); mf[u] = mf.get(u, 0) + 1; names.add(u)
        dd = f"{tmp}/apic_{d}"; os.makedirs(dd, exist_ok=True)
        sh("gsutil", "-q", "-m", "cp", f"{B}/raw/ph_at_launch/{d}/api_comments/*.jsonl", dd)
        for f in glob.glob(f"{dd}/*.jsonl"):
            for l in open(f):
                x = json.loads(l)
                if str(x.get("post_id")) in ids and idmap.get(str(x.get("commenter_user_id"))):
                    u = idmap[str(x["commenter_user_id"])]; cmh.setdefault(u, set()).add((str(x["post_id"]), str(x.get("comment_id"))))
    pulled = set()   # pace runner's whole pulls not yet merged into the store
    r = sh("gsutil", "ls", f"{B}/raw/_pacetest/**.json")
    for l in r.stdout.splitlines():
        b = os.path.basename(l.strip())
        if b.endswith(".json") and "/_code/" not in l:
            pulled.add(b[:-5].lower())
    names |= pulled
    r = sh("gsutil", "ls", f"{B}/raw/ph_population/people_live/vm/deep_list/")   # deep_list files are <handle>.<writer>.json
    names |= {os.path.basename(l.strip()).split(".")[0].lower() for l in r.stdout.splitlines() if l.strip().endswith(".json")}
    r = sh("gsutil", "ls", f"{B}/raw/ph_population/people_live/vm/")              # person files <handle>.<vm>.json, if listed flat
    names |= {os.path.basename(l.strip()).split(".")[0].lower() for l in r.stdout.splitlines() if l.strip().endswith(".json")}
    h2u = {hid(sl, u): u for u in names if u}
    # evidence
    up = {}; cm = {}
    for u, g in E.groupby("person"):
        up[hid(sl, u)] = set(g[g.kind == "upvote"].id); cm[hid(sl, u)] = set(g[g.kind == "comment"].id)
    Vv = V[V.target_id.astype(str).isin(ids)]
    for pid, g in Vv.groupby("person_id"):
        up.setdefault(pid, set()).update(g[g.kind == "upvote"].target_id.astype(str)); cm.setdefault(pid, set()).update(g[g.kind == "comment"].target_id.astype(str))
    for u, s in cmh.items():
        cm.setdefault(hid(sl, u), set()).update({a for a, _ in s})
    team_h = {hid(sl, u) for u in team}
    F = V[(V.kind == "follows") & V.target_id.astype(str).isin(team_h)]
    fol = F.groupby("person_id").target_id.nunique().to_dict()
    for u, n in mf.items():
        k = hid(sl, u); fol[k] = max(fol.get(k, 0), n)
    vnh = {hid(sl, u): n for u, n in vn.items()}
    # whole already
    inc = T[~T.complete.astype(bool)]
    bad = set(inc[inc.apply(short_kind, axis=1) == "code_stop"].person_id) if len(inc) else set()
    full = set(T[T.pull_type.astype(str) == "full"].person_id) if "pull_type" in T else set()
    whole = (full - bad) | {hid(sl, u) for u in pulled}
    cand = (set(up) | set(cm) | set(fol) | set(vnh)) - whole - team_h
    rows = []
    for pid in cand:
        s = 4 * len(up.get(pid, ())) + 3 * len(cm.get(pid, ())) + 2 * min(fol.get(pid, 0), 5) + 0.3 * min(vnh.get(pid, 0), 10)
        if s > 0:
            rows.append((pid, h2u.get(pid), s, len(up.get(pid, ())), len(cm.get(pid, ())), fol.get(pid, 0), vnh.get(pid, 0)))
    R = pd.DataFrame(rows, columns=["pid", "handle", "score", "up", "cm", "fol", "vn"])
    known = R[R.handle.notna()].sort_values(["score", "handle"], ascending=[False, True])
    loc = f"{tmp}/priority_lastweek.txt"
    with open(loc, "w") as f:
        f.write("\n".join(known.handle) + "\n")
    sh("gsutil", "-q", "cp", loc, OUT_GS, check=True)
    rep = {"window": [d0, d1], "launches": int(len(L)), "candidates": int(len(R)), "listed_with_handle": int(len(known)),
           "unmapped_salted_ids": int(R.handle.isna().sum()),
           "unmapped_with_upvote": int((R.handle.isna() & (R.up > 0)).sum()), "unmapped_with_comment": int((R.handle.isna() & (R.cm > 0)).sum()),
           "unmapped_follow_only": int((R.handle.isna() & (R.up == 0) & (R.cm == 0)).sum()), "with_upvote_evidence": int((known.up > 0).sum()),
           "with_comment_evidence": int((known.cm > 0).sum()), "with_maker_follow": int((known.fol > 0).sum()),
           "voternet_only": int(((known.up == 0) & (known.cm == 0) & (known.fol == 0)).sum()),
           "excluded_whole": int(len(whole)), "out": OUT_GS}
    print(json.dumps(rep))
    return rep


if __name__ == "__main__":
    main(*sys.argv[1:3])
