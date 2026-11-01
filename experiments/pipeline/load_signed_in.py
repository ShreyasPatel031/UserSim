"""Load Grok Bot's signed-in upvote fetches (raw/upvotes_signed_in/<date>.jsonl) into the warehouse.
Input lines: {username, product_slug, product_name, upvoted_at, position, fetched_at}. Each upvote becomes an `events`
row (kind upvote, date = the launch day, date_quality launch_day, as every other upvote; upvoted_at is not used as the
date because the page shows it only roughly). Rows already in `events` (person x launch) are skipped, so re-running is
safe. One `fetch_state` row per person (source upvotes_signed_in) records the fetch. Slugs that match no launch are
counted and written to a local file for checking; they are never guessed.
usage: python -m pipeline.load_signed_in <date | local .jsonl> [--dry]
       python -m pipeline.load_signed_in <date> --ph [--dry]   (raw/ph_upvotes/, post ids; also the daily step ph_upvotes)"""
import json, os, subprocess, sys
import pandas as pd
from . import warehouse as W


def load(day, dry=False):
    if os.path.exists(day):   # a local file (tests)
        txt = open(day).read(); day = os.path.basename(day)[:10]
    else:
        txt = subprocess.run(["gsutil", "cat", f"{W.BUCKET}/raw/upvotes_signed_in/{day}.jsonl"], capture_output=True, text=True, check=True).stdout
    R = [json.loads(l) for l in txt.splitlines() if l.strip()]
    con = W.connect()
    L = con.execute("SELECT id, slug, day, name FROM launches").df()
    by_slug = dict(zip(L.slug, zip(L.id.astype(str), L.day)))
    by_name = {}
    for i, d, n in zip(L.id.astype(str), L.day, L.name):   # fallback: an exact, unique launch name
        by_name.setdefault((n or "").strip().lower(), []).append((i, d))
    have = set(map(tuple, con.execute("SELECT person, CAST(launch_id AS VARCHAR) FROM events WHERE kind = 'upvote'").fetchall()))
    ev, miss, seen = [], [], set()
    for r in R:
        u, s = r.get("username"), (r.get("product_slug") or "").strip()
        hit = by_slug.get(s)
        if hit is None:
            c = by_name.get((r.get("product_name") or "").strip().lower(), [])
            hit = c[0] if len(c) == 1 else None
        if hit is None:
            miss.append(r); continue
        k = (u, hit[0])
        if k in have or k in seen:
            continue
        seen.add(k)
        ev.append({"person": u, "launch_id": hit[0], "date": hit[1], "kind": "upvote", "date_quality": "launch_day"})
    E = pd.DataFrame(ev, columns=["person", "launch_id", "date", "kind", "date_quality"])
    P = pd.DataFrame(R)
    st = P.groupby("username").agg(items=("product_slug", "size"), last_fetched=("fetched_at", "max")).reset_index() if len(P) else pd.DataFrame()
    if len(st):
        st = st.rename(columns={"username": "person"}).assign(source="upvotes_signed_in", status=200, complete=False)
        st["last_fetched"] = st.last_fetched.astype(str).str[:10]
    os.makedirs("/tmp/signed_in", exist_ok=True)
    with open(f"/tmp/signed_in/unmatched_{day}.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in miss)
    if not dry:
        if len(E):
            W.write("events", E)
        if len(st):
            W.write("fetch_state", st)
    out = {"lines": len(R), "people": int(P.username.nunique()) if len(P) else 0, "matched": len(R) - len(miss),
           "unmatched": len(miss), "new_events": len(E), "already_known": len(R) - len(miss) - len(E),
           "newest_launch_day": E.date.max() if len(E) else None, "dry": dry}
    print(json.dumps(out))
    return out


DONE = os.path.expanduser("~/w/ph_upvotes_loaded.txt")   # files already merged (re-merging is safe, only slower)


def load_ph(d, dry=False):
    """Grok Bot's team's upvote-page fetches (raw/ph_upvotes/<date>_*.jsonl, parse_upvotes.py records with post ids)
    for every file dated up to day d that is not merged yet: incremental.merge_upvotes, so only new person x launch
    pairs are added, plus fetch_state rows. -> counts for the run log."""
    from . import incremental as INC
    ls = subprocess.run(["gsutil", "ls", f"{W.BUCKET}/raw/ph_upvotes/*.jsonl"], capture_output=True, text=True).stdout.split()
    done = set(open(DONE).read().split()) if os.path.exists(DONE) else set()
    todo = [f for f in sorted(ls) if f not in done and os.path.basename(f)[:10] <= d]
    out = {"files": len(todo), "records": 0, "ok_pages": 0, "new_events": 0, "people_deeper": 0}
    if not todo:
        return out
    con = W.connect()
    for f in todo:
        recs = [json.loads(l) for l in subprocess.run(["gsutil", "cat", f], capture_output=True, text=True, check=True).stdout.splitlines() if l.strip()]
        recs = [r for r in recs if r.get("username")]
        ev, st, deeper = INC.merge_upvotes(con, recs, os.path.basename(f)[:10])
        out["records"] += len(recs); out["ok_pages"] += sum(r.get("status") == 200 for r in recs)
        out["new_events"] += len(ev); out["people_deeper"] += len(deeper)
        if not dry:
            if len(ev):
                W.write("events", ev)
            if len(st):
                W.write("fetch_state", st)
            with open(DONE, "a") as g:
                g.write(f + "\n")
    print(json.dumps({"ph_upvotes": out, "dry": dry}))
    return out


if __name__ == "__main__":
    if "--ph" in sys.argv:
        load_ph(sys.argv[1], dry="--dry" in sys.argv)
    else:
        load(sys.argv[1], dry="--dry" in sys.argv)
