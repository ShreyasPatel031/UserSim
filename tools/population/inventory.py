"""Population data inventory: per source, people covered and history depth.

Reads raw files downloaded from gs://.../usersim_sim/raw/ into DATA_DIR (never committed) and prints counts only.
Usage: python tools/population/inventory.py DATA_DIR [--json OUT]
Depth = items per person and days back (person's fetch time minus their oldest event). "exact" = the event carries
its own timestamp; "proxy" = dated by the upvoted launch's day (PH shows no cast time); "none" = undated.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

D = sys.argv[1]
rows = []


def jl(path):
    out = []
    for p in sorted(glob.glob(path)):
        with open(p) as f:
            out += [json.loads(l) for l in f if l.strip()]
    return pd.DataFrame(out)


def q(s, p):
    s = pd.Series(s).dropna()
    return float(np.percentile(s, p)) if len(s) else None


def add(source, people, items, days, oldest, dated, note=""):
    rows.append(dict(source=source, people=int(people),
                     items_med=q(items, 50), items_p90=q(items, 90),
                     days_med=q(days, 50), days_p90=q(days, 90),
                     oldest=str(oldest)[:10] if oldest is not None else None, dated=dated, note=note))


def depth(df, user, ts, fetched):
    df = df.copy()
    df["_ts"] = pd.to_datetime(df[ts], utc=True, errors="coerce", format="mixed")
    df["_f"] = pd.to_datetime(df[fetched], utc=True, errors="coerce", format="mixed")
    g = df.groupby(user)
    items = g.size()
    days = (g["_f"].max() - g["_ts"].min()).dt.total_seconds() / 86400
    return items, days, df["_ts"].min()


# 1. PH upvotes page 1, full pool, Nov 1
u = jl(f"{D}/up/upvotes_page1_full.jsonl")
ok = u[u.get("post_id").notna()] if "post_id" in u else u
it, dy, old = depth(ok, "username", "launched_at", "fetched_at")
hm = ok.groupby("username")["has_more"].first().mean()
add("PH upvotes page 1 (Nov 1, full pool)", u.username.nunique(), it, dy, old,
    "proxy 100% (launch day); exact 0%", f"has_more {hm:.0%}; {u.username.nunique()-ok.username.nunique()} empty/error")

# 2-3. person store v3g events
e = pd.read_parquet(f"{D}/people_v3g/events.parquet")
built = pd.Timestamp("2026-11-02", tz="UTC")
for (plat, kind), g in e.groupby(["platform", "kind"]):
    ts = pd.to_datetime(g.ts, utc=True, errors="coerce", format="mixed")
    gg = g.assign(_ts=ts).groupby("person_id")
    days = (built - gg["_ts"].min()).dt.total_seconds() / 86400
    qual = g.ts_quality.value_counts(normalize=True).round(3).to_dict()
    n_sep = int((gg["_ts"].min() <= pd.Timestamp("2026-09-02", tz="UTC")).sum())
    add(f"store v3g {plat} {kind}", g.person_id.nunique(), gg.size(), days, ts.min(), str(qual),
        f"{len(g):,} events; people reaching back to <= Sep 2: {n_sep:,}")

# 4. daily refreshes (upvotes page 1)
for day in ["1102", "1103"]:
    d = jl(f"{D}/daily/{day}/upvotes_page1.jsonl")
    if len(d):
        d = d[d.post_id.notna()]
        it, dy, old = depth(d, "username", "launched_at", "fetched_at")
        add(f"PH daily upvotes page 1 ({day})", d.username.nunique(), it, dy, old, "proxy (launch day); first-seen vs prior read")

# 5. follows page 1
for name, path in [("PH following page 1 (Nov 2)", f"{D}/daily/1102/following_page1.jsonl"),
                   ("PH following page 1 (rota pilot Nov 3)", f"{D}/daily/pilot_following.jsonl")]:
    f = jl(path)
    if not len(f) or "followee" not in f:
        continue
    f = f[f.followee.notna()]
    g = f.groupby("username")
    tot = g["followings"].max()
    comp = (g.size() >= tot).mean()
    add(name, f.username.nunique(), g.size(), None, None, "none (follow time not shown; first-seen by diff)",
        f"total followings med {tot.median():.0f} p90 {tot.quantile(.9):.0f}; complete list {comp:.0%}")

# 6. followers of makers/hunters (at-launch capture)
fo = jl(f"{D}/ph_followers/*/*.jsonl")
if len(fo):
    g = fo.groupby("of")
    add("PH followers of makers/hunters (Nov 3 capture)", fo["of"].nunique(), g.username.nunique(), None, None,
        "none (first-seen by diff from Nov 3)",
        f"{fo.username.nunique():,} distinct followers; capped targets {g.capped.first().mean():.0%}")

# 7. profiles
p = pd.read_parquet(f"{D}/people_v3g/profiles.parquet")
for plat, g in p.groupby("platform"):
    add(f"store v3g {plat} profile", g.person_id.nunique(), None, None, None,
        str(g.observed_on_quality.value_counts().to_dict()),
        f"followers count present {g.followers.notna().mean():.0%}")
h = pd.read_parquet(f"{D}/people_v3g/handles.parquet")
xh = h[h.platform == "x"]
add("store v3g X handles", xh.person_id.nunique(), None, None, None, "n/a",
    f"conf>=0.8: {xh[xh.confidence>=0.8].person_id.nunique():,}")
xl = json.load(open(f"{D}/x_lookup/x_lookup.json"))
add("X users lookup (Nov 2)", sum(1 for v in xl.values() if v.get("exists")), None, None, None, "snapshot",
    f"{len(xl)} handles looked up")

# 8. X posts/engagement files
for name, path, user, ts in [("X prelaunch posts", f"{D}/x/prelaunch_posts.jsonl", "handle", "posted_at"),
                             ("X launch engagement (posts by makers/hunters)", f"{D}/x/engagement.jsonl", "handle", "post_at"),
                             ("X prelaunch engagers", f"{D}/x/prelaunch_engagers.jsonl", "user", None),
                             ("X follow checks pilot", f"{D}/x/follow_checks_pilot.jsonl", "person_x", None)]:
    x = jl(path)
    if not len(x):
        continue
    if ts and ts in x:
        it, dy, old = depth(x, user, ts, "fetched_at")
        add(name, x[user].nunique(), it, dy, old, "exact")
    else:
        add(name, x[user].nunique(), x.groupby(user).size(), None, None, "none")

out = pd.DataFrame(rows)
pd.set_option("display.width", 250, "display.max_colwidth", 70)
print(out.to_string(index=False))
if "--json" in sys.argv:
    out.to_json(sys.argv[sys.argv.index("--json") + 1], orient="records", indent=1)
