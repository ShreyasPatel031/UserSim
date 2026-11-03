"""Share of API comment rows whose commenter_user_id resolves to a pool member (counts only).
Usage: python resolve_commenters.py USER_ID_MAP.jsonl PERSONS_PARQUET COMMENT_FILES... [--unresolved OUT]
Comment rows: any jsonl row with commenter_user_id (live/comments_ts.jsonl, api_full comments). Unresolved ids -> OUT (GCS only),
one per line, for a profile read each when route 4 reopens (pool-growth candidates)."""
import json, sys
import pandas as pd

m = pd.read_json(sys.argv[1], lines=True, dtype={"user_id": str})
latest = m.sort_values("last_seen").groupby("user_id").username.last()
pool = set(pd.read_parquet(sys.argv[2]).ph_username.str.lower())
args = sys.argv[3:]
out = args[args.index("--unresolved") + 1] if "--unresolved" in args else None
files = [a for a in args if a != "--unresolved" and a != out]
ids = []
for f in files:
    for l in open(f):
        r = json.loads(l)
        uid = r.get("commenter_user_id")
        if uid is None and isinstance(r.get("extra"), dict):
            uid = r["extra"].get("commenter_user_id")
        if uid is not None:
            ids.append(str(uid))
s = pd.Series(ids, dtype=str)
name = s.map(latest)
inpool = name.isin(pool)
u = s.drop_duplicates()
print(f"comment rows {len(s):,}; distinct commenters {u.size:,}")
print(f"rows resolved to a username {name.notna().mean():.1%}; to a pool member {inpool.mean():.1%}")
print(f"distinct commenters in pool {u.map(latest).isin(pool).mean():.1%}; known non-pool {(u.map(latest).notna() & ~u.map(latest).isin(pool)).mean():.1%}; "
      f"unknown id {u.map(latest).isna().mean():.1%}")
if out:
    open(out, "w").write("\n".join(sorted(set(s[name.isna()]))) + "\n")
