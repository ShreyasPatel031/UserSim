"""Load Grok Bot's signed-in upvote fetches (raw/upvotes_signed_in/<date>.jsonl) into the warehouse.
Input lines: {username, product_slug, product_name, upvoted_at, position, fetched_at}. Each upvote becomes an `events`
row (kind upvote, date = the launch day, date_quality launch_day, as every other upvote; upvoted_at is not used as the
date because the page shows it only roughly). Rows already in `events` (person x launch) are skipped, so re-running is
safe. One `fetch_state` row per person (source upvotes_signed_in) records the fetch. Slugs that match no launch are
counted and written to a local file for checking; they are never guessed.
usage: python -m pipeline.load_signed_in <date | local .jsonl> [--dry]"""
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


if __name__ == "__main__":
    load(sys.argv[1], dry="--dry" in sys.argv)
