"""Population person store: loaders, validation and build (population data agent).

Inputs are raw rows keyed by username (GCS raw/ only). Output keys people on a salted person_id; usernames never leave raw/.
Every event row: person_id, platform, kind, target_id, ts_lo, ts_hi, ts_quality, first_seen_at, fetched_at, source, extra.
  ts_quality: exact (event carries its own time) | bounded (upvote: [lo, hi] from list order + reads) | snapshot (edge seen, time unknown)
Upvote bounds: PH lists upvotes newest-vote-first and shows no cast time, so for position k in one read
  lo = max(launched_at of items k..end)   (a vote can't precede its launch, and is newer than every older vote)
  hi = earliest fetched_at of any read showing it;
  and if an earlier read of the same person did not show it while showing a vote that is older in a later read, lo >= that read's fetched_at.

Usage:
  python tools/population/store.py records DATA_DIR OUT_DIR --salt-file SALT [--complete-file F]  # lossless records (run first)
  python tools/population/store.py build DATA_DIR OUT_DIR --salt-file SALT   # DATA_DIR laid out as in inventory.py
  python tools/population/store.py validate-pilot DIR                         # raw/ph_population/<run>/ as declared by Data Feeder
"""
import argparse, glob, gzip, hashlib, json, os, sys
from collections import defaultdict

import pandas as pd

TS = lambda s: pd.to_datetime(s, utc=True, errors="coerce", format="mixed")


# ---------- ids ----------
class Ids:
    def __init__(self, salt: str):
        self.salt = salt

    def __call__(self, username, platform="producthunt"):
        if username is None or (isinstance(username, float) and pd.isna(username)):
            return None
        u = str(username).strip().lstrip("@").lower()
        return "p_" + hashlib.sha256(f"{self.salt}{platform}:{u}".encode()).hexdigest()[:16]


def read_jsonl(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        return [json.loads(l) for l in f if l.strip()]


def rows_glob(pattern):
    out = []
    for p in sorted(glob.glob(pattern)):
        out += read_jsonl(p)
    return out


# ---------- generic Apollo / GraphQL walker (for saved page JSON) ----------
CONN_KEYS = {"votedPosts": "upvote", "followers": "follower", "following": "following", "followings": "following",
             "comments": "comment", "activityItems": "activity", "activities": "activity", "reviews": "review",
             "collections": "collection", "stacks": "stack", "madePosts": "made", "submittedPosts": "hunted"}


def walk_connections(obj, path=()):
    """Yield (key, connection) for every {..., "edges": [...]} under a known key, anywhere in the tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict) and isinstance(v.get("edges"), list) and k in CONN_KEYS:
                yield k, v
            yield from walk_connections(v, path + (k,))
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_connections(v, path)


def parse_page_json(obj):
    """Return {kind: {"nodes": [...], "has_more", "end_cursor"}} from a saved Apollo/GraphQL page."""
    out = {}
    for k, conn in walk_connections(obj):
        kind = CONN_KEYS[k]
        pi = conn.get("pageInfo") or {}
        nodes = [e.get("node") for e in conn["edges"] if isinstance(e, dict) and isinstance(e.get("node"), dict)]
        prev = out.get(kind)
        if prev is None or len(nodes) > len(prev["nodes"]):  # Apollo caches can repeat a connection; keep the fullest
            out[kind] = {"nodes": nodes, "has_more": pi.get("hasNextPage"), "end_cursor": pi.get("endCursor")}
    return out


# ---------- loaders: existing raw files ----------
def load_upvote_reads(paths, source):
    """Page-1 or paged upvote rows: username, position, post_id, launched_at, fetched_at -> list of reads."""
    rows = []
    for p in paths:
        rows += [r for r in read_jsonl(p) if r.get("post_id")]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["source"] = source
    return df


def upvote_events(reads: pd.DataFrame, ids: Ids) -> pd.DataFrame:
    """reads: rows with username, position, post_id, launched_at, fetched_at, (page_no). One read = (username, fetched_at run)."""
    df = reads.copy()
    df["launched"] = TS(df.launched_at)
    df["fetched"] = TS(df.fetched_at)
    df["page_no"] = df.get("page_no", pd.Series(1, index=df.index)).fillna(1).astype(int)
    df["read_id"] = df.username.str.lower() + "|" + df.fetched.dt.floor("D").astype(str) + "|" + df.source
    # global order within a read: page then position
    df = df.sort_values(["read_id", "page_no", "position"])
    df["rank"] = df.groupby("read_id").cumcount()
    # lo within read = running max of launched over older items (reverse order)
    df["lo"] = df.iloc[::-1].groupby("read_id")["launched"].cummax().iloc[::-1]
    out = []
    for user, g in df.groupby(df.username.str.lower()):
        reads = sorted(g.read_id.unique(), key=lambda r: g[g.read_id == r].fetched.min())
        first_seen, lo = {}, {}
        for pid_, r in g.groupby("post_id"):
            first_seen[pid_] = r.fetched.min()
            lo[pid_] = r.lo.max()
        # first-seen tightening across reads
        seen_sets = [(g[g.read_id == r].fetched.min(), set(g[g.read_id == r].post_id),
                      g[g.read_id == r].set_index("post_id")["rank"].to_dict()) for r in reads]
        for i in range(1, len(seen_sets)):
            t_prev, s_prev, _ = seen_sets[i - 1]
            _, s_cur, rank_cur = seen_sets[i]
            for post in s_cur - s_prev:
                older = [p for p, rk in rank_cur.items() if rk > rank_cur[post]]
                if any(p in s_prev for p in older):  # previous read reached past this vote's slot and didn't show it
                    lo[post] = max(lo[post], t_prev) if pd.notna(lo[post]) else t_prev
        pid = ids(user)
        last = g.sort_values("fetched").groupby("post_id").last()
        for post, r in last.iterrows():
            # lo > hi: the list put this vote above a vote on a later launch although we saw it earlier -> a re-vote
            # (unvote + upvote moves an item up). Keep first_seen as hi, drop lo, flag it.
            conflict = pd.notna(lo[post]) and lo[post] > first_seen[post] + pd.Timedelta(minutes=1)
            out.append(dict(person_id=pid, platform="producthunt", kind="upvote", target_id=str(post),
                            ts_lo=pd.NaT if conflict else lo[post], ts_hi=first_seen[post],
                            ts_quality="order_conflict" if conflict else "bounded",
                            first_seen_at=first_seen[post], fetched_at=r.fetched, source=r.source,
                            extra=json.dumps({"launched_at": str(r.launched)[:25]})))
    return pd.DataFrame(out)


def follow_events(rows, ids: Ids, kind, user_key, other_key, source):
    """Edges seen in list reads: first_seen = earliest read showing the edge; time of follow unknown (snapshot)."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df[other_key].notna()]
    df["fetched"] = TS(df.fetched_at)
    g = df.groupby([df[user_key].str.lower(), df[other_key].str.lower()]).fetched.agg(["min", "max"]).reset_index()
    return pd.DataFrame(dict(person_id=g[user_key].map(ids), platform="producthunt", kind=kind,
                             target_id=g[other_key].map(ids), ts_lo=pd.NaT, ts_hi=g["min"], ts_quality="snapshot",
                             first_seen_at=g["min"], fetched_at=g["max"], source=source, extra=None))


def comment_events_from_store(events_parquet, ids_map):
    """Exact-time comments from the v3g store (keyed 'ph:<username>'); re-keyed to salted ids."""
    e = pd.read_parquet(events_parquet)
    c = e[(e.platform == "producthunt") & (e.kind == "comment")].copy()
    c["person_id"] = c.person_id.str.replace("^ph:", "", regex=True).map(ids_map)
    t = TS(c.ts)  # v3g comment ts is a date only (YYYY-MM-DD), despite its "exact" label; timezone not recorded
    return pd.DataFrame(dict(person_id=c.person_id, platform="producthunt", kind="comment", target_id=c.target_id.astype(str),
                             ts_lo=t - pd.Timedelta(hours=12), ts_hi=t + pd.Timedelta(hours=36), ts_quality="day",
                             first_seen_at=pd.NaT, fetched_at=pd.NaT, source="v3g:" + c.source, extra=None))


def api_comment_events(paths, ids: Ids, id_map_path):
    """PH API v2 comments with commenter_user_id (live snapshots and backfill). Exact createdAt; dedupe on comment_id;
    first_seen = earliest snapshot. Unresolved ids get person_id from the numeric id (platform producthunt_uid) and
    extra.unresolved = true, so they re-key once the id is resolved. Comment text is not carried into the store."""
    m = pd.read_json(id_map_path, lines=True, dtype={"user_id": str})
    latest = m.sort_values("last_seen").groupby("user_id").username.last()
    rows = []
    for p in paths:
        for r in read_jsonl(p):
            x = r.get("extra") if isinstance(r.get("extra"), dict) else {}
            uid = r.get("commenter_user_id", x.get("commenter_user_id"))
            cid = r.get("comment_id", x.get("comment_id"))
            if uid is None or cid is None:
                continue
            rows.append(dict(uid=str(uid), comment_id=str(cid), post_id=str(r.get("post_id") or r.get("target_id")),
                             created=r.get("createdAt") or r.get("ts_lo"), seen=r.get("snapshot_at") or r.get("fetched_at"),
                             parent=r.get("parentId", x.get("parent_id")), votes=r.get("votesCount", x.get("votes")),
                             featured=x.get("post_featured_at") is not None if x else None,
                             src="ph_api_v2:live" if "snapshot_at" in r else "ph_api_v2:backfill"))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["seen"] = TS(df.seen)
    g = df.sort_values("seen").groupby("comment_id")
    df = g.last().assign(first_seen=g.seen.min()).reset_index()
    name = df.uid.map(latest)
    df["person_id"] = [ids(n) if isinstance(n, str) else ids(u, "producthunt_uid") for n, u in zip(name, df.uid)]
    t = TS(df.created)
    extra = [json.dumps({"comment_id": c, "parent_id": p, "votes": v, "unresolved": not isinstance(n, str)})
             for c, p, v, n in zip(df.comment_id, df.parent, df.votes, name)]
    return pd.DataFrame(dict(person_id=df.person_id, platform="producthunt", kind="comment", target_id=df.post_id,
                             ts_lo=t, ts_hi=t, ts_quality="exact", first_seen_at=df.first_seen, fetched_at=df.seen,
                             source=df.src, extra=extra))


# ---------- loaders: Data Feeder population runs (schema in 20261103T2000 reply, DRAFT) ----------
COMMON = ["username", "tab", "page_no", "status", "fetched_at"]
TAB_KEYS = {"profile": ["followers_count", "following_count"], "upvotes": ["post_ids", "has_more"],
            "activity": ["items"], "reviews": ["items"], "collections": ["items"], "stacks": ["items"],
            "made": ["hunted", "made"], "followers": ["users", "has_more"], "following": ["users", "has_more"]}


def validate_pilot(run_dir, profiles=None):
    """Checks a ph_population/<run>/ drop. Returns (ok, report dict). profiles: {username_lower: upvotes_total}."""
    rep, ok = {}, True
    tabs = {os.path.basename(p)[:-6]: read_jsonl(p) for p in glob.glob(f"{run_dir}/*.jsonl")}
    if not tabs:
        return False, {"error": "no tab files"}
    for tab, rows in tabs.items():
        r = {"rows": len(rows)}
        miss = sum(1 for x in rows if any(k not in x for k in COMMON))
        st = pd.Series([x.get("status") for x in rows]).value_counts().to_dict()
        r["missing_common"], r["status"] = miss, {str(k): int(v) for k, v in st.items()}
        good = [x for x in rows if x.get("status") == 200]
        r["missing_payload"] = sum(1 for x in good if any(k not in x for k in TAB_KEYS.get(tab, [])))
        bad_ts = 0
        for x in good:
            f = TS(x.get("fetched_at"))
            if pd.isna(f):
                bad_ts += 1
            for it in x.get("items") or []:
                c = TS(it.get("created_at")) if isinstance(it, dict) else pd.NaT
                if isinstance(it, dict) and (pd.isna(c) or (pd.notna(f) and c > f + pd.Timedelta(minutes=5))):
                    bad_ts += 1
        r["bad_times"] = bad_ts
        # paging continuity: page numbers contiguous per person; no duplicate items across pages
        pages = defaultdict(list)
        for x in good:
            pages[x["username"].lower()].append(x)
        gaps = dups = 0
        for u, xs in pages.items():
            nos = sorted(x.get("page_no", 1) for x in xs)
            gaps += nos != list(range(1, len(nos) + 1))
            if tab == "upvotes":
                ids_ = [p for x in xs for p in (x.get("post_ids") or [])]
                dups += len(ids_) - len(set(ids_))
        r["people"], r["page_gaps"], r["dup_items"] = len(pages), gaps, dups
        if tab == "upvotes" and profiles:
            cov = []
            for u, xs in pages.items():
                tot = profiles.get(u)
                n = len({p for x in xs for p in (x.get("post_ids") or [])})
                last = max(xs, key=lambda x: x.get("page_no", 1))
                if tot and not last.get("has_more"):
                    cov.append(n / tot)
            if cov:
                s = pd.Series(cov)
                r["complete_people_seen_vs_total_med"] = round(float(s.median()), 3)
                r["complete_people_below_90pct"] = int((s < 0.9).sum())
        r_ok = miss == 0 and r["missing_payload"] == 0 and bad_ts == 0 and gaps == 0 and dups == 0
        r["pass"] = r_ok
        ok &= r_ok
        rep[tab] = r
    return ok, rep


def pilot_upvote_reads(run_dir):
    """Flatten Data Feeder upvotes.jsonl pages into the read-row shape upvote_events() takes."""
    rows = []
    for x in read_jsonl(f"{run_dir}/upvotes.jsonl"):
        if x.get("status") != 200:
            continue
        la = x.get("launched_at") or [None] * len(x.get("post_ids") or [])
        for i, p in enumerate(x.get("post_ids") or [], 1):
            rows.append(dict(username=x["username"], page_no=x.get("page_no", 1), position=i, post_id=str(p),
                             launched_at=la[i - 1] if i - 1 < len(la) else None, fetched_at=x["fetched_at"]))
    df = pd.DataFrame(rows)
    if len(df):
        df["source"] = "ph_population"
    return df


# ---------- X drops from Grok Bot (raw/population_data/x*/<run>/{persons,events}.jsonl, already salted) ----------
X_EVENT_COLS = ["person_id", "platform", "kind", "target_id", "ts_lo", "ts_hi", "ts_quality", "first_seen_at", "fetched_at", "source"]


def verify_x_drop(run_dir, pool_ids):
    """Returns (ok, report). Checks: schema, ids join the pool, events join persons, dedupe, exact times <= fetched_at."""
    P = pd.DataFrame(read_jsonl(f"{run_dir}/persons.jsonl"))
    E = pd.DataFrame(read_jsonl(f"{run_dir}/events.jsonl"))
    r = {"persons": len(P), "events": len(E)}
    r["missing_cols"] = [c for c in X_EVENT_COLS + ["extra"] if c not in E] if len(E) else []
    r["persons_dup"] = int(P.person_id.duplicated().sum())
    r["persons_not_in_pool"] = int((~P.person_id.isin(pool_ids)).sum())
    if len(E):
        r["events_not_in_persons"] = int((~E.person_id.isin(P.person_id)).sum())
        r["events_dup"] = int(E.duplicated(["person_id", "target_id"]).sum())
        lo, f = TS(E.ts_lo), TS(E.fetched_at)
        r["bad_times"] = int((lo.isna() | (lo > f + pd.Timedelta(minutes=5)) | (E.ts_lo != E.ts_hi)).sum())
        r["kinds"] = E.kind.value_counts().to_dict()
    ok = not r["missing_cols"] and r["persons_dup"] == 0 and r["persons_not_in_pool"] == 0 and \
        r.get("events_not_in_persons", 0) == 0 and r.get("events_dup", 0) == 0 and r.get("bad_times", 0) == 0
    r["pass"] = ok
    return ok, r


def x_end_reason(row):
    """X pass-1 timeline end (Data Feeder, Nov 8): pass 1 reads 1 page (25 newest posts) and posts since 2026-08-01 only.
    A drop's own end_reason wins; else posts_error -> error, posts_truncated -> cap_1, otherwise -> window. Only x_end
    (X itself ended the timeline) is a complete timeline; every other end is partial (Shreyas decides whether to finish)."""
    er = row.get("end_reason")
    if er:
        return str(er)
    if row.get("posts_error"):
        return "error"
    if row.get("posts_truncated") in (True, "true", "True", 1):
        return "cap_1"
    return "window"


def x_timelines(data_dir, ok_dirs):
    """one row per X person (latest fetch over the passing drops): end_reason and timeline_status (partial unless x_end)."""
    rows = []
    for d in ok_dirs:
        for r in read_jsonl(f"{d}/persons.jsonl"):
            rows.append({"person_id": r.get("person_id"), "x_person_id": r.get("x_person_id"), "drop": os.path.relpath(d, data_dir),
                         "fetched_at": r.get("fetched_at"), "posts_window_start": r.get("posts_window_start"),
                         "oldest_fetched_post_at": r.get("oldest_fetched_post_at"), "posts_calls": r.get("posts_calls"),
                         "posts_truncated": bool(r.get("posts_truncated")), "posts_error": bool(r.get("posts_error")),
                         "end_reason": x_end_reason(r)})
    if not rows:
        return pd.DataFrame()
    t = pd.DataFrame(rows).sort_values("fetched_at").drop_duplicates("person_id", keep="last")
    t["timeline_status"] = t.end_reason.map(lambda e: "complete" if e == "x_end" else "partial")
    return t


OK_X_DIRS = []


def x_events(data_dir, pool_ids):
    out, reps = [], {}; OK_X_DIRS.clear()
    for d in sorted(glob.glob(f"{data_dir}/population_data/x*/*/")) + sorted(glob.glob(f"{data_dir}/population_data/x_pilot50/")):
        if not os.path.exists(f"{d}/events.jsonl"):
            continue
        ok, rep = verify_x_drop(d, pool_ids)
        reps[os.path.relpath(d, data_dir)] = rep
        if not ok:
            continue  # failed drops are reported, never loaded
        OK_X_DIRS.append(d)
        E = pd.DataFrame(read_jsonl(f"{d}/events.jsonl"))
        E["extra"] = E.extra.map(json.dumps)
        out.append(E[X_EVENT_COLS + ["extra"]])
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame()), reps


# ---------- parse cache for person pulls (hourly rebuilds re-read ~1 GB of JSON otherwise) ----------
_FILLED_SIG = [None]


def _cached_load(fp, ids, upload_time, filled, data_dir):
    """(tabs, events) for one pull file, cached by path + size + mtime + loader version + F1 fill map. Cache lives next to the
    raw data (never committed); a changed or new file is re-parsed."""
    import full_pull, pickle
    st = os.stat(fp)
    if _FILLED_SIG[0] is None:
        _FILLED_SIG[0] = hashlib.sha256(json.dumps(filled, sort_keys=True).encode()).hexdigest()[:12]
    code = hashlib.sha256(open(full_pull.__file__, "rb").read()).hexdigest()[:12]
    key = hashlib.sha256(f"{fp}|{st.st_size}|{st.st_mtime_ns}|{code}|{_FILLED_SIG[0]}|{ids.salt[:4]}".encode()).hexdigest()[:24]
    cdir = f"{data_dir}/.parse_cache"; os.makedirs(cdir, exist_ok=True)
    cf = f"{cdir}/{key}.pkl"
    if os.path.exists(cf):
        try:
            return pickle.load(open(cf, "rb"))
        except Exception:
            pass
    out = full_pull.load_full(fp, ids, upload_time=upload_time, filled=filled)
    pickle.dump(out, open(cf + ".tmp", "wb")); os.replace(cf + ".tmp", cf)
    return out


# ---------- lossless person records (14:0xZ Nov 13) ----------
# Shreyas: every piece of information pulled is kept. store_v3 used to carry only 135 of the 1,464 key paths found in the
# per-person files (no join date, ph_user_id, name, bio, headline, links, badges, streak, maker history, upvote taglines,
# follower headlines, ...). records.parquet now holds every person's saved record VERBATIM (record_json = the file's exact
# text, earlier_records and items_earlier included), and persons.parquet gains typed columns for the profile fields.
# The build fails if any person file is not carried byte-for-byte.
PROFILE_COLS = ["ph_user_id", "name", "joined", "headline", "bio", "badges_count", "streak", "links_json", "badges_json",
                "ranks_text_json", "maker_history_json", "header_json", "pull_finished_utc", "pulls_merged", "has_provenance",
                "signed_in_upvotes_json"]


def _latest_person_files(data_dir):
    """newest saved record per person in people_live/vm/ (a <h>_f1fix.json copy only if newer than <h>.json; only those pairs
    are opened to compare)."""
    by = defaultdict(list)
    for fn in os.listdir(f"{data_dir}/people_live/vm"):
        if fn.endswith(".json"):
            by[fn[:-5].replace("_f1fix", "").lower()].append(f"{data_dir}/people_live/vm/{fn}")

    def fin(p):
        try:
            return str((json.load(open(p)).get("run") or {}).get("finished_utc") or "")
        except Exception:
            return ""
    return {h: (ps[0] if len(ps) == 1 else max(ps, key=fin)) for h, ps in by.items()}


def _records_part(args):
    """worker: write one records part file; return profile rows and counts."""
    import pyarrow as pa, pyarrow.parquet as pq
    k, items, out_dir, salt, comp, sio = args
    ids = Ids(salt)
    schema = pa.schema([("person_id", pa.string()), ("complete", pa.bool_()), ("pull_finished_utc", pa.string()),
                        ("record_sha256", pa.string()), ("record_json", pa.large_string())])
    rows, prof, bad = [], [], 0
    dj = lambda x: json.dumps(x, sort_keys=True, default=str) if x is not None else None
    for h, p in items:
        raw = open(p, "rb").read()
        try:
            d = json.loads(raw)
            txt = raw.decode("utf-8")
        except Exception:
            bad += 1
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if hashlib.sha256(txt.encode("utf-8")).hexdigest() != sha:  # carried byte-for-byte or the build fails
            raise RuntimeError("record not carried byte-for-byte")
        pid = ids(h)
        a = d.get("about") or {}
        fin = str((d.get("run") or {}).get("finished_utc") or "")
        rows.append({"person_id": pid, "complete": (h in comp) if comp is not None else None, "pull_finished_utc": fin,
                     "record_sha256": sha, "record_json": txt})
        prof.append({"person_id": pid, "ph_user_id": str(d.get("ph_user_id")) if d.get("ph_user_id") is not None else None,
                     "name": d.get("name"), "joined": a.get("joined"), "headline": a.get("headline"), "bio": a.get("bio"),
                     "badges_count": a.get("badges_count"), "streak": dj(a.get("streak")), "links_json": dj(a.get("links")),
                     "badges_json": dj(a.get("badges")), "ranks_text_json": dj(a.get("ranks_text")),
                     "maker_history_json": dj(a.get("maker_history")), "header_json": dj(d.get("header")),
                     "pull_finished_utc": fin, "pulls_merged": len(d.get("pull_history") or []) or 1,
                     "has_provenance": "provenance" in d,
                     "signed_in_upvotes_json": dj(sio.get(h))})
    if rows:
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), f"{out_dir}/records/part-{k:04d}.parquet", compression="zstd")
    return prof, len(rows), bad


def build_records(data_dir, out_dir, salt, complete=None, workers=4):
    """records/part-*.parquet (every person's newest saved record verbatim) + person_profile.parquet (typed profile columns)."""
    import multiprocessing as mp
    files = sorted(_latest_person_files(data_dir).items())
    os.makedirs(f"{out_dir}/records", exist_ok=True)
    for f in glob.glob(f"{out_dir}/records/part-*.parquet"):
        os.remove(f)
    sio = {}  # signed-in upvote read markers (header, got, utc, vm) from raw/_pacetest/shared/_signedin_upvotes and the babysitter queue
    for p in glob.glob(f"{data_dir}/signedin_upvotes/*.json"):
        try:
            sio[os.path.basename(p)[:-5].lower()] = json.load(open(p))
        except Exception:
            pass
    chunks = [(i // 2000, files[i:i + 2000], out_dir, salt, complete, {h: sio[h] for h, _ in files[i:i + 2000] if h in sio})
              for i in range(0, len(files), 2000)]
    prof, n, bad = [], 0, 0
    with mp.get_context("fork").Pool(workers) as pool:
        for pr, k, b in pool.imap_unordered(_records_part, chunks):
            prof += pr
            n += k
            bad += b
    if n != len(files) - bad:
        raise RuntimeError(f"records: {n} written for {len(files) - bad} readable person files")
    pr = pd.DataFrame(prof)
    pr["joined"] = pd.to_datetime(pr["joined"], utc=True, errors="coerce", format="mixed")
    pr.to_parquet(f"{out_dir}/person_profile.parquet", index=False)
    rep = {"person_files": len(files), "records_written": n, "unreadable_files": bad, "fields_not_carried": 0,
           "joined_present": int(pr.joined.notna().sum()), "ph_user_id_present": int(pr.ph_user_id.notna().sum())}
    json.dump(rep, open(f"{out_dir}/records_report.json", "w"))
    return pr, rep


# ---------- build ----------
def build(data_dir, out_dir, salt, complete=None):
    """complete: optional set of lower-case handles (whole-person rule). When given, full pulls are read only from
    people_live/vm/ for those handles (no lists-only light/pgql/boxbrowser pulls) and persons.parquet gets a `complete` flag."""
    ids = Ids(salt)
    os.makedirs(out_dir, exist_ok=True)
    reads = pd.concat([
        load_upvote_reads([f"{data_dir}/up/upvotes_page1_full.jsonl"], "ph_upvotes_full_p1"),
        load_upvote_reads(sorted(glob.glob(f"{data_dir}/daily/*/upvotes_page1.jsonl")), "ph_people_daily_p1"),
    ] + [pilot_upvote_reads(d) for d in sorted(glob.glob(f"{data_dir}/ph_population/*")) if os.path.exists(f"{d}/upvotes.jsonl")],
        ignore_index=True)
    ev = [upvote_events(reads, ids)]
    fol = rows_glob(f"{data_dir}/daily/*/following_page1.jsonl") + rows_glob(f"{data_dir}/daily/pilot_following.jsonl")
    ev.append(follow_events(fol, ids, "follows", "username", "followee", "ph_following_p1"))
    fo = rows_glob(f"{data_dir}/ph_followers/*/*.jsonl")
    ev.append(follow_events(fo, ids, "follows", "username", "of", "ph_followers_of_team"))
    persons = pd.read_parquet(f"{data_dir}/people_v3g/persons.parquet")
    ids_map = {u.lower(): ids(u) for u in persons.ph_username.dropna()}
    ev.append(comment_events_from_store(f"{data_dir}/people_v3g/events.parquet", ids_map))
    if os.path.exists(f"{data_dir}/user_id_map.jsonl"):
        ac = api_comment_events(sorted(glob.glob(f"{data_dir}/api_comments/**/*.jsonl", recursive=True)) +
                                sorted(glob.glob(f"{data_dir}/population_data/ph_comments/*/*.jsonl")), ids,
                                f"{data_dir}/user_id_map.jsonl")
        if len(ac):
            # an exact API comment supersedes a day-dated v3g comment by the same person on the same launch that day
            v3 = ev[-1]
            key = set(zip(ac.person_id, ac.target_id, TS(ac.ts_lo).dt.date))
            mid = (v3.ts_lo + pd.Timedelta(hours=12)).dt.date
            ev[-1] = v3[[k not in key for k in zip(v3.person_id, v3.target_id, mid)]]
            ev.append(ac)
    # full all-tab pulls (people_live/vm/*.json, people_live/boxbrowser/<user>/<user>_full.json)
    import full_pull
    up_times = {}
    if os.path.exists(f"{data_dir}/people_live/_upload_times.json"):
        up_times = json.load(open(f"{data_dir}/people_live/_upload_times.json"))
    tab_rows, fp_events = [], []
    ev_done = []  # 11:4xZ Nov 13 (complete mode): de-duplicated 2,000-file chunks; holding ~65k small frames and one global
    # sort over all of them ran past the 15 GB memory limit. One file per person in complete mode, so a duplicate (re-pull of
    # the same person) can only sit inside one file and per-chunk de-duplication gives the same rows as the global pass.
    KEY = ["person_id", "kind", "target_id", "ts_lo"]

    def _fold_events(chunk):
        return pd.concat(chunk, ignore_index=True).sort_values("first_seen_at").drop_duplicates(KEY, keep="first")
    filled = json.load(open(f"{data_dir}/people_live/f1_filled.json")) if os.path.exists(f"{data_dir}/people_live/f1_filled.json") else {}
    vm = sorted(glob.glob(f"{data_dir}/people_live/vm/*.json")) + sorted(glob.glob(f"{data_dir}/people_live/light/**/*.json", recursive=True)) \
        + sorted(glob.glob(f"{data_dir}/people_live/vm_pgql/_run_*/*.json"))
    if complete is not None:  # orchestrator 08:30Z Nov 10: store_v3 from complete people only
        vm = [p for p in glob.glob(f"{data_dir}/people_live/vm/*.json")
              if os.path.basename(p)[:-5].replace("_f1fix", "").lower() in complete]
    fixed_h = {p[:-len("_f1fix.json")] for p in vm if p.endswith("_f1fix.json")}

    def _fin(p):
        try:
            return str((json.load(open(p)).get("run") or {}).get("finished_utc") or "")
        except Exception:
            return ""
    # F1: the restamped copy replaces the original it was made from, but never a newer pull of the same person
    # (12:2xZ Nov 10: 140 people had an old _f1fix copy shadowing a newer full pull)
    newer = {b for b in fixed_h if os.path.exists(b + ".json") and _fin(b + ".json") > _fin(b + "_f1fix.json")}
    vm = [p for p in vm if (p.endswith("_f1fix.json") and p[:-len("_f1fix.json")] not in newer)
          or (not p.endswith("_f1fix.json") and (p[:-len(".json")] not in fixed_h or p[:-len(".json")] in newer))]
    for fp in vm + ([] if complete is not None else sorted(glob.glob(f"{data_dir}/people_live/boxbrowser/*/*_full.json"))):
        t_, e_ = _cached_load(fp, ids, up_times.get(os.path.relpath(fp, f"{data_dir}/people_live")), filled, data_dir)
        if len(t_):
            tab_rows.append(t_)
        if len(e_):
            fp_events.append(e_)
        if complete is not None and len(fp_events) >= 2000:
            ev_done.append(_fold_events(fp_events))
            fp_events = []
        if len(tab_rows) >= 2000:
            tab_rows = [pd.concat(tab_rows, ignore_index=True)]
    if complete is not None and fp_events:
        ev_done.append(_fold_events(fp_events))
        fp_events = []
    if fp_events or ev_done:
        if complete is not None:
            e_ = pd.concat(ev_done, ignore_index=True) if len(ev_done) > 1 else ev_done[0]
            del ev_done
        else:
            e_ = pd.concat(fp_events, ignore_index=True)
            # re-pulls of the same person: one row per (person, kind, target, time), earliest first_seen kept
            e_ = e_.sort_values("first_seen_at").drop_duplicates(KEY, keep="first")
        api_cids = set()
        for e0 in ev:
            if len(e0) and "source" in e0:
                a = e0[e0.source.astype(str).str.startswith("ph_api_v2")]
                api_cids |= {json.loads(x).get("comment_id") for x in a.extra}
        cid = e_.extra.map(lambda x: json.loads(x).get("comment_id") if isinstance(x, str) else None)
        ev.append(e_[~((e_.kind == "comment") & cid.isin(api_cids - {None}))])
    if tab_rows:  # latest pull per (person, tab); a light upvotes read never replaces a full pull's other tabs (it has none)
        tr = pd.concat(tab_rows, ignore_index=True).sort_values("fetched_at")
        tr = tr.drop_duplicates(["person_id", "tab"], keep="last")
        tr.to_parquet(f"{out_dir}/tabs.parquet", index=False)
        extra_people = set(tr.person_id) - set(ids_map.values())
    else:
        extra_people = set()
    xe, xrep = x_events(data_dir, set(ids_map.values()))
    print("X drops:", json.dumps(xrep, default=str))
    if len(xe):
        ev.append(xe.drop_duplicates(["person_id", "target_id"]))
    # 11:5xZ Nov 13: events are written piece by piece. The de-dup key includes `source`, so pieces whose source sets
    # do not overlap cannot share a duplicate; overlapping pieces are merged first. Same rows as the old global
    # concat + drop_duplicates, without one ~11 GB frame (the 65k-person build ran past the 15 GB memory limit).
    pieces = [e for e in ev if len(e)]
    del ev
    groups = []  # [(set of sources, [pieces])]
    for e in pieces:
        src = set(e.source.astype(str).unique())
        hit = [g for g in groups if g[0] & src]
        for g in hit:
            groups.remove(g)
        groups.append((src.union(*[g[0] for g in hit]), [x for g in hit for x in g[1]] + [e]))
    del pieces
    import pyarrow as pa, pyarrow.parquet as pq
    writer, schema, stats = None, None, _StoreStats()
    while groups:
        _, parts = groups.pop()
        e = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
        del parts
        e = e.drop_duplicates(["person_id", "kind", "target_id", "ts_lo", "source"])
        for c in ["ts_lo", "ts_hi", "first_seen_at", "fetched_at"]:
            e[c] = pd.to_datetime(e[c], utc=True)
        stats.add(e)
        t = pa.Table.from_pandas(e, preserve_index=False)
        if writer is None:
            schema = t.schema
            writer = pq.ParquetWriter(f"{out_dir}/events.parquet", schema)
        writer.write_table(t.select(schema.names).cast(schema))
        del e, t
    if writer is not None:
        writer.close()
    pool = pd.DataFrame({"person_id": sorted(set(ids_map.values()))})
    pool["in_pool"] = True
    # people pulled who are not in the Nov 2 pool (discovery for the 48 h coverage plan): same salted ids, in_pool False
    pool = pd.concat([pool, pd.DataFrame({"person_id": sorted(extra_people), "in_pool": False})], ignore_index=True)
    if complete is not None:
        cids = {ids(h) for h in complete}
        pool["complete"] = pool.person_id.isin(cids)
    if os.path.exists(f"{out_dir}/person_profile.parquet"):  # written by `store.py records` (run first: the two together outlive a run)
        prof = pd.read_parquet(f"{out_dir}/person_profile.parquet")
        rrep = json.load(open(f"{out_dir}/records_report.json"))
    else:
        prof, rrep = build_records(data_dir, out_dir, salt, complete)
    print("RECORDS:", json.dumps(rrep))
    extra = sorted(set(prof.person_id) - set(pool.person_id))
    if extra:
        add = pd.DataFrame({"person_id": extra, "in_pool": False})
        if "complete" in pool:
            add["complete"] = add.person_id.isin({ids(h) for h in complete})
        pool = pd.concat([pool, add], ignore_index=True)
    pool = pool.merge(prof, on="person_id", how="left")
    pool["has_record"] = pool.ph_user_id.notna() | pool.pull_finished_utc.notna()
    # why each person was pulled (request_provenance.py over every request batch list): earliest entry route plus every
    # route, earliest first; the full table is copied next to persons as request_provenance.parquet
    rp_f = f"{data_dir}/request_provenance.parquet"
    if os.path.exists(rp_f):
        rp = pd.read_parquet(rp_f)
        rp.to_parquet(f"{out_dir}/request_provenance.parquet", index=False)
        rp = rp[rp.person_id.isin(set(pool.person_id))].sort_values(["person_id", "requested_utc", "batch_file", "batch_rank"])
        NONENTRY = {"repull_fix", "completion", "repull_gap", "upvote_refresh_complete", "pool_upvote_refresh"}
        ent = rp[~rp.route.isin(NONENTRY)].groupby("person_id").head(1).set_index("person_id")
        allr = rp.groupby("person_id").apply(lambda g: json.dumps([{"route": r, "seed": sd, "batch": b, "requested_utc": t}
                                                                     for r, sd, b, t in zip(g.route, g.seed, g.batch_file, g.requested_utc)]))
        pool["entry_route"] = pool.person_id.map(ent.route)
        pool["entry_seed"] = pool.person_id.map(ent.seed)
        pool["entry_batch"] = pool.person_id.map(ent.batch_file)
        pool["entry_requested_utc"] = pool.person_id.map(ent.requested_utc)
        pool["request_provenance_json"] = pool.person_id.map(allr)
        pool["n_request_batches"] = pool.person_id.map(rp.groupby("person_id").batch_file.nunique()).fillna(0).astype(int)
        print("PROVENANCE:", json.dumps({"with_record": int(pool.has_record.sum()),
                                         "with_record_attributed": int((pool.has_record & pool.request_provenance_json.notna()).sum()),
                                         "with_record_entry_route": int((pool.has_record & pool.entry_route.notna()).sum()),
                                         "entry_route_counts": pool[pool.has_record].entry_route.value_counts().to_dict()}))
    pool.to_parquet(f"{out_dir}/persons.parquet", index=False)
    xt = x_timelines(data_dir, OK_X_DIRS)  # orchestrator Nov 8 02:39Z: every X timeline labelled; partial unless x_end
    if len(xt):
        xt.to_parquet(f"{out_dir}/x_timelines.parquet", index=False)
        print("X timelines:", json.dumps({"people": len(xt), "end_reason": xt.end_reason.value_counts().to_dict(),
                                          "timeline_status": xt.timeline_status.value_counts().to_dict()}))
    return stats, pool


class _StoreStats:
    """check_store and the kind/source summary, accumulated over event pieces (sources never span pieces)."""

    def __init__(self):
        self.c, self.persons, self.summary = Counter_(), set(), []

    def add(self, e):
        key = ["person_id", "kind", "target_id", "source", "ts_lo"]
        up = e[e.kind == "upvote"]
        self.c["events"] += len(e)
        self.c["dup_keys"] += int(e.duplicated(key).sum())
        self.c["upvote_order_conflicts"] += int((e.ts_quality == "order_conflict").sum())
        self.c["upvote_lo_gt_hi"] += int((up.ts_lo > up.ts_hi + pd.Timedelta(minutes=1)).sum())
        self.c["upvote_lo_missing"] += int((up.ts_lo.isna() & (up.ts_quality == "bounded")).sum())
        self.c["null_person"] += int(e.person_id.isna().sum())
        self.c["fetched_or_exact_n"] += int(((e.fetched_at.notna()) | (e.ts_quality == "exact")).sum())
        self.persons |= set(e.person_id.dropna())
        self._pp = getattr(self, "_pp", [])
        self._pp.append(e.person_id)
        self.summary.append(e.groupby(["kind", "source", "ts_quality"]).agg(events=("person_id", "size"), people=("person_id", "nunique")))

    def check(self, pool):
        c = {k: v for k, v in self.c.items() if k != "fetched_or_exact_n"}
        c["fetched_or_exact"] = self.c["fetched_or_exact_n"] / max(1, self.c["events"])
        core = set(pool[pool.in_pool].person_id)
        c["pool_people_with_events"] = len(self.persons & core)
        c["events_outside_pool_people"] = int(sum((~s.isin(core)).sum() for s in self._pp))
        c["pulled_non_pool_people"] = int((~pool.in_pool).sum())
        c["pass"] = c["dup_keys"] == 0 and c["upvote_lo_gt_hi"] == 0 and c["null_person"] == 0
        return c

    def table(self):
        return pd.concat(self.summary).groupby(level=[0, 1, 2]).sum().to_string() if self.summary else ""


from collections import Counter as Counter_


def check_store(events, pool):
    """Store-level validation (counts only)."""
    c = {}
    c["events"] = len(events)
    key = ["person_id", "kind", "target_id", "source", "ts_lo"]
    timed = events.ts_quality.isin(["exact", "day"])
    c["dup_keys"] = int(events.duplicated(key).sum())
    c["upvote_order_conflicts"] = int((events.ts_quality == "order_conflict").sum())
    up = events[events.kind == "upvote"]
    c["upvote_lo_gt_hi"] = int((up.ts_lo > up.ts_hi + pd.Timedelta(minutes=1)).sum())
    c["upvote_lo_missing"] = int((up.ts_lo.isna() & (up.ts_quality == "bounded")).sum())
    c["null_person"] = int(events.person_id.isna().sum())
    c["fetched_or_exact"] = float(((events.fetched_at.notna()) | (events.ts_quality == "exact")).mean())
    core = pool[pool.in_pool].person_id
    c["pool_people_with_events"] = int(events.person_id.isin(core).groupby(events.person_id).any().sum())
    c["events_outside_pool_people"] = int((~events.person_id.isin(core)).sum())
    c["pulled_non_pool_people"] = int((~pool.in_pool).sum())
    c["pass"] = c["dup_keys"] == 0 and c["upvote_lo_gt_hi"] == 0 and c["null_person"] == 0
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "records", "validate-pilot"])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--salt-file")
    ap.add_argument("--complete-file", help="latest_complete.txt: build full-pull tabs/events from complete people only")
    a = ap.parse_args()
    if a.cmd == "records":
        comp = None
        if a.complete_file:
            comp = {l.split("\t")[0].split()[0].lstrip("@").lower() for l in open(a.complete_file) if l.strip() and not l.startswith("#")}
        os.makedirs(a.paths[1], exist_ok=True)
        print("RECORDS:", json.dumps(build_records(a.paths[0], a.paths[1], open(a.salt_file).read().strip(), comp)[1]))
    elif a.cmd == "build":
        salt = open(a.salt_file).read().strip()
        comp = None
        if a.complete_file:
            comp = {l.split("\t")[0].split()[0].lstrip("@").lower() for l in open(a.complete_file) if l.strip() and not l.startswith("#")}
        stats, pool = build(a.paths[0], a.paths[1], salt, comp)
        print(json.dumps(stats.check(pool), indent=1))
        print(stats.table())
    else:
        ok, rep = validate_pilot(a.paths[0])
        print(json.dumps(rep, indent=1, default=str))
        sys.exit(0 if ok else 1)
