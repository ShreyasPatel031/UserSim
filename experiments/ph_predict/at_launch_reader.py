"""Reader for Data Feeder's at-launch capture (raw/ph_at_launch/<day>/: posts, products, makers, external .jsonl; schema
from pilot_2026-11-02 and raw/ph_at_launch/README.md) -> dated rows in the raw/ph_userbase schema, scored by
c2_user_base.py with no new code.

Pre-launch rule (strict; orchestrator, Nov 3, tightened after the first real day). A value is pre-launch only if all hold:
  1. fetched within STRICT_MIN (20) min of the launch start (featured_at, else 00:01 PT);
  2. fetched before the launch's first non-zero vote snapshot (warehouse vote_snapshots, hourly; no snapshot -> not);
  3. not a post activity count (votes or comments at fetch), and for post rows PH did not show votes > 0.
Rule 1 is needed because PH hides vote counts for ~4 h (on the page and in the API: shown as 0, hide_votes_count), so
the first non-zero snapshot comes ~04:00 PT, hours after voting starts; rule 2 alone would pass late captures.
Each row is judged on its own fetch time (X counts are filled later than the page fetch: x_fetched_at).
as_of_date: c2 keeps only rows dated strictly before the launch day, so pre-launch rows get as_of_date = day - 1 and
the rest get the launch day (c2 drops and counts them). fetched_at, first_vote_at and pre_launch are kept on every row.
Timing: Data Feeder's capture is due by ~00:20 PT from Nov 4 (trigger raw/daily/<day>/today_0005.json); a later capture
fails rule 1. It still lands after the 00:05 forecast, so it serves research and a later shadow, not the 00:05 headline.
Relaxed variant (orchestrator, Nov 3; report it labelled, never as the headline rule): for profile-level sources (not
atl_post), a row fetched within RELAX_MIN (60) minutes of the launch's start (featured_at, else 00:01 PT) is
pre_launch_relaxed; RELAXED=1 also dates those rows day - 1 for c2.

Rows (JSON lines): launch_id, source, metric, as_of_date, count, fetched_at, first_vote_at, pre_launch
  + username, role for per-person rows (makers / hunters, and their X / GitHub counts).
Outputs contain usernames: write them to the bucket or ~ only, never to the repo.
Prior pulls: makers with a store_v3 full pull fetched before 00:00 PT of the day get dated profile rows (atl_profile_v3;
V3=0 turns it off).
usage: python at_launch_reader.py <day dir, local or gs://...> <out prefix>
       -> <out prefix>_launch.jsonl, <out prefix>_people.jsonl; prints coverage and the pre-launch share as JSON."""
import datetime as dt, json, os, subprocess, sys, tempfile
import pandas as pd

POST = {"votes_at_fetch": "votes", "comments_count_at_fetch": "comments", "media_count": "media", "launch_number": "launch_number"}
PRODUCT = {"followers": "followers", "reviews_count": "reviews", "posts_count": "posts", "first_launch": "first_launch"}
PROFILE = {"followers": "followers", "followings": "followings", "products_made": "products_made", "hunted": "hunted",
           "upvotes_total": "upvotes_total", "reviews_count": "reviews", "badges_total": "badges", "visit_streak_days": "visit_streak"}
RELAXED = os.environ.get("RELAXED") == "1"   # date relaxed-only rows as pre-launch too (report it labelled)
RELAX_MIN = int(os.environ.get("RELAX_MIN", "60"))
STRICT_MIN = int(os.environ.get("STRICT_MIN", "20"))   # the capture target is 00:20 PT
ACTIVITY = {("atl_post", "votes"), ("atl_post", "comments")}
EXT = {"x_free_quota": ("x", "followers"), "github_api": ("github", "stargazers_count")}


def need(rows, cols, what):
    for r in rows[:50]:
        miss = [c for c in cols if c not in r]
        if miss:
            raise SystemExit(f"{what}: missing {miss}; has {sorted(r)[:30]}")


def load(src):
    if src.startswith("gs://"):
        d = tempfile.mkdtemp(prefix="atl_")
        for f in ("posts", "products", "makers", "external"):
            subprocess.run(["gsutil", "-q", "cp", f"{src.rstrip('/')}/{f}.jsonl", d], check=f != "external")
        src = d
    rd = lambda f: [json.loads(l) for l in open(os.path.join(src, f"{f}.jsonl")) if l.strip()] if os.path.exists(os.path.join(src, f"{f}.jsonl")) else []
    return rd("posts"), rd("products"), rd("makers"), rd("external")


def first_votes(ids):
    """{launch_id: first `at` (UTC ISO) with votes > 0} from the warehouse vote_snapshots."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import warehouse as W
    q = ",".join(repr(str(i)) for i in ids) or "''"
    V = W.query(f"SELECT launch_id::VARCHAR AS id, min(CAST(\"at\" AS VARCHAR)) AS t FROM vote_snapshots WHERE votes > 0 AND launch_id::VARCHAR IN ({q}) GROUP BY 1")
    return dict(zip(V.id, V.t))


def ts(x):
    return pd.Timestamp(x).tz_convert("UTC") if pd.Timestamp(x).tzinfo else pd.Timestamp(x).tz_localize("UTC")


def rows_from(posts, products, makers, ext, fv):
    need(posts, ["day", "launch_id", "slug", "fetched_at", "votes_at_fetch", "status"], "posts.jsonl")
    need(products, ["slug", "launch_ids", "fetched_at", "status"], "products.jsonl")
    need(makers, ["username", "roles", "launch_ids", "fetched_at", "profile", "status"], "makers.jsonl")
    day = posts[0]["day"]; prev = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    slug2ids = {}
    for p in posts:
        slug2ids.setdefault(p["slug"], set()).add(str(p["launch_id"]))
    for p in products:
        slug2ids.setdefault(p["slug"], set()).update(map(str, p["launch_ids"]))

    start = {str(p["launch_id"]): p.get("featured_at") or p.get("created_at") for p in posts}
    day0 = pd.Timestamp(f"{day} 00:01", tz="America/Los_Angeles").tz_convert("UTC")

    def row(lid, source, metric, value, fetched, extra_ok=True, **kw):
        t = fv.get(str(lid))
        s0 = ts(start[str(lid)]) if start.get(str(lid)) else day0
        # strict: before the first non-zero vote snapshot AND within STRICT_MIN of the launch start (PH hides vote
        # counts for ~4 h, in the API too, so the snapshot alone would pass captures made hours into voting);
        # activity counts read off the post (votes, comments) are never pre-launch
        pre = bool(extra_ok and t is not None and fetched and ts(fetched) < ts(t)
                   and ts(fetched) <= s0 + pd.Timedelta(minutes=STRICT_MIN) and (source, metric) not in ACTIVITY)
        # relaxed (labelled, profile-level sources only): fetched within RELAX_MIN of the launch's 00:01 PT start
        rel = bool(source != "atl_post" and fetched and ts(fetched) <= s0 + pd.Timedelta(minutes=RELAX_MIN))
        use = (pre or rel) if RELAXED else pre
        return {"launch_id": str(lid), "source": source, "metric": metric, "as_of_date": prev if use else day,
                "count": float(value), "fetched_at": fetched, "first_vote_at": t, "pre_launch": pre,
                "pre_launch_relaxed": rel, **kw}

    L, P = [], []
    for p in posts:
        if str(p["status"]) != "200":   # Nov 4 files carry the status as a string
            continue
        # PH hides vote counts early in the day (hide_votes_count: shown as 0), so the shown count only rules a row out
        # when visible and > 0; the vote-snapshot timing is the rule
        zero = bool(p.get("hide_votes_count")) or p.get("votes_at_fetch") == 0
        for k, m in POST.items():
            if isinstance(p.get(k), (int, float, bool)):
                L.append(row(p["launch_id"], "atl_post", m, p[k], p["fetched_at"], zero))
    for pr in products:
        if str(pr["status"]) != "200":   # Nov 4 files carry the status as a string
            continue
        for lid in map(str, pr["launch_ids"]):
            for k, m in PRODUCT.items():
                if isinstance(pr.get(k), (int, float, bool)):
                    L.append(row(lid, "atl_product", m, pr[k], pr["fetched_at"]))
    for mk in makers:
        if str(mk["status"]) != "200":   # Nov 4 files carry the status as a string
            continue
        prof = mk["profile"] or {}
        for lid in map(str, mk["launch_ids"]):
            for role in mk["roles"]:
                for k, m in PROFILE.items():
                    if isinstance(prof.get(k), (int, float)) and not isinstance(prof.get(k), bool):
                        P.append(row(lid, "atl_profile", m, prof[k], mk["fetched_at"], username=mk["username"].lower(), role=role))
    who = {}
    for mk in makers:
        for lid in map(str, mk["launch_ids"]):
            for role in mk["roles"]:
                who.setdefault(mk["username"].lower(), set()).add((lid, role))
    for e in ext:
        if e.get("source") not in EXT or str(e.get("status")) != "200":
            continue
        name, field = EXT[e["source"]]
        v = e.get(field, e.get("followers"))
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fetched = e.get("x_fetched_at") or e.get("fetched_at")
        if e.get("owner_kind") == "product":
            for lid in slug2ids.get(e.get("owner"), ()):
                L.append(row(lid, f"atl_{name}", field, v, fetched))
        elif e.get("owner_kind") == "person":
            for lid, role in who.get((e.get("owner") or "").lower(), ()):
                P.append(row(lid, f"atl_{name}", field, v, fetched, username=e["owner"].lower(), role=role))
    return day, L, P


V3_TABS = os.environ.get("V3_TABS", "gs://usersim-bakeoff-347838016394/usersim_sim/raw/population/store_v3/tabs.parquet")
V3_METRIC = {"followers": "followers", "following": "followings", "hunted": "hunted", "upvotes": "upvotes_total",
             "reviews": "reviews", "collections": "collections", "stacks": "stacks"}


def v3_profiles(makers, day):
    """Prior full pulls (orchestrator, Nov 4 13:06 UTC): a maker / hunter with a store_v3 full pull (tabs.parquet, one
    header count per tab) fetched before 00:00 PT of the launch day has a dated pre-launch profile: source atl_profile_v3,
    strict (pre_launch) when fetched_at < 00:00 PT of the day, as_of_date day - 1. The latest such pull per person is
    used. store_v3 is keyed on salted hashes ("p_" + sha256(salt + "producthunt:" + lower(username))[:16]); the salt
    (raw/population/_salt) is read only to match and never printed. fetched_quality is kept (store_v3 marks the pull
    times estimated: an upper bound on the fetch, so the date rule stays strict)."""
    import hashlib
    path = V3_TABS
    if path.startswith("gs://"):
        loc = os.path.join(tempfile.mkdtemp(prefix="v3_"), "tabs.parquet")
        subprocess.run(["gsutil", "-q", "cp", path, loc], check=True); path = loc
    T = pd.read_parquet(path)
    T = T[T.tab.isin(V3_METRIC) & T.header.notna()]
    salt = subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/raw/population/_salt"],
                          capture_output=True, text=True, check=True).stdout.strip()
    d0 = pd.Timestamp(f"{day} 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    prev = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    T = T[pd.to_datetime(T.fetched_at, utc=True) < d0]
    last = T.sort_values("fetched_at").groupby(["person_id", "tab"]).tail(1)
    by = {pid: g for pid, g in last.groupby("person_id")}
    rows, seen, hit = [], set(), set()
    for mk in makers:
        u = str(mk.get("username") or "").lower()
        if not u or u in ("[redacted]", "redacted", "none", "nan"):
            continue
        seen.add(u)
        g = by.get("p_" + hashlib.sha256((salt + "producthunt:" + u).encode()).hexdigest()[:16])
        if g is None:
            continue
        hit.add(u)
        for lid in map(str, mk["launch_ids"]):
            for role in mk["roles"]:
                for r in g.itertuples():
                    rows.append({"launch_id": lid, "source": "atl_profile_v3", "metric": V3_METRIC[r.tab], "as_of_date": prev,
                                 "count": float(r.header), "fetched_at": pd.Timestamp(r.fetched_at).isoformat(),
                                 "fetched_quality": r.fetched_quality, "first_vote_at": None, "pre_launch": True,
                                 "pre_launch_relaxed": True, "username": u, "role": role})
    return rows, {"makers_named": len(seen), "makers_with_prior_v3_pull": len(hit), "v3_people_before_day": int(T.person_id.nunique())}


def main(src, out):
    posts, products, makers, ext = load(src)
    if not posts:
        raise SystemExit(f"no posts.jsonl rows in {src}")
    fv = first_votes({str(p["launch_id"]) for p in posts})
    day, L, P = rows_from(posts, products, makers, ext, fv)
    v3 = {}
    if os.environ.get("V3", "1") == "1":
        R3, v3 = v3_profiles(makers, day); P += R3
    for suf, R in (("launch", L), ("people", P)):
        with open(f"{out}_{suf}.jsonl", "w") as f:
            for r in R:
                f.write(json.dumps(r) + "\n")
    D = pd.DataFrame(L + P)
    rep = {"day": day, "launches": len(posts), "launches_with_first_vote": len(fv),
           "rows": len(D), "pre_launch_rows": int(D.pre_launch.sum()) if len(D) else 0,
           "launches_with_any_pre_launch_row": int(D[D.pre_launch].launch_id.nunique()) if len(D) else 0,
           "v3_prior_pulls": v3, "relaxed": RELAXED, "relax_min": RELAX_MIN, "pre_launch_relaxed_rows": int(D.pre_launch_relaxed.sum()) if len(D) else 0,
           "by_source": D.groupby("source").agg(rows=("pre_launch", "size"), pre=("pre_launch", "sum"), relaxed=("pre_launch_relaxed", "sum")).astype(int).to_dict("index") if len(D) else {},
           "capture_minus_first_vote_min": (D.assign(g=[(ts(a) - ts(b)).total_seconds() / 60 if a and b else None for a, b in zip(D.fetched_at, D.first_vote_at)])
                                           .groupby("source").g.median().round(1).to_dict()) if len(D) else {}}
    print(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    main(*sys.argv[1:3])
