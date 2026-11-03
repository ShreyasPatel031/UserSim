"""PH numeric user id -> username map from everything held (population agent). Raw map goes to GCS only.
Walks every .json/.jsonl(.gz) under DATA_DIR and v3g profiles, collecting user nodes:
  {username|handle, user_id}  or  {username, id} with user-node keys (followersCount/headline/twitterUsername).
Usage: python user_id_map.py DATA_DIR OUT_JSONL   -> rows {user_id, username, sources, last_seen}; prints coverage counts only.
"""
import glob, gzip, json, os, sys
from collections import defaultdict
import pandas as pd

D, OUT = sys.argv[1], sys.argv[2]
pairs = defaultdict(lambda: {"sources": set(), "last": ""})
USERKEYS = {"followersCount", "headline", "twitterUsername", "followers_count"}


def add(uid, name, src, ts=""):
    if uid is None or not name:
        return
    uid = str(uid).strip()
    if not uid.isdigit():
        return
    k = (uid, str(name).lower().lstrip("@"))
    pairs[k]["sources"].add(src)
    pairs[k]["last"] = max(pairs[k]["last"], ts or "")


def walk(o, src, ts=""):
    if isinstance(o, dict):
        ts = o.get("fetched_at") or ts
        name = o.get("username") or o.get("handle")
        if name and o.get("user_id") is not None:
            add(o["user_id"], name, src, ts)
        elif name and o.get("id") is not None and USERKEYS & o.keys():
            add(o["id"], name, src, ts)
        for v in o.values():
            if isinstance(v, (dict, list)):
                walk(v, src, ts)
    elif isinstance(o, list):
        for v in o:
            walk(v, src, ts)


for p in glob.glob(f"{D}/**/*", recursive=True):
    if not os.path.isfile(p) or not any(p.endswith(s) for s in (".json", ".jsonl", ".jsonl.gz", ".json.gz")):
        continue
    src = os.path.relpath(p, D).split("/")[0]
    op = gzip.open if p.endswith(".gz") else open
    try:
        with op(p, "rt") as f:
            if ".jsonl" in p:
                for l in f:
                    if '"user_id"' in l or '"username"' in l or '"handle"' in l:
                        walk(json.loads(l), src)
            else:
                walk(json.load(f), src)
    except Exception as ex:
        print("skip", os.path.relpath(p, D), type(ex).__name__, file=sys.stderr)

prof = pd.read_parquet(f"{D}/people_v3g/profiles.parquet")
prof = prof[prof.platform == "producthunt"]
for h, ex, ob in zip(prof.handle, prof.extra, prof.observed_on):
    add(json.loads(ex).get("ph_user_id"), h, "people_v3g", ob or "")

rows = pd.DataFrame([{"user_id": k[0], "username": k[1], "sources": sorted(v["sources"]), "last_seen": v["last"]} for k, v in pairs.items()])
# one id -> several usernames = renamed account: keep all rows, flag; current name = latest seen
rows["names_for_id"] = rows.groupby("user_id").username.transform("nunique")
rows["ids_for_name"] = rows.groupby("username").user_id.transform("nunique")
rows.to_json(OUT, orient="records", lines=True)
pool = set(pd.read_parquet(f"{D}/people_v3g/persons.parquet").ph_username.str.lower())
known = set(rows.username)
print(f"ids {rows.user_id.nunique():,}; usernames {rows.username.nunique():,}; ids with >1 username {int((rows.groupby('user_id').username.nunique() > 1).sum())}; "
      f"usernames with >1 id {int((rows.groupby('username').user_id.nunique() > 1).sum())}")
print(f"pool with a known id: {len(pool & known):,} / {len(pool):,} ({len(pool & known) / len(pool):.1%}); non-pool ids: {len(known - pool):,}")
src = rows.explode("sources").groupby("sources").user_id.nunique().sort_values(ascending=False)
print(src.to_string())
