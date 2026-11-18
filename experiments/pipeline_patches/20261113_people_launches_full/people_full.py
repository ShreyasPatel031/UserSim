"""Full `people` snapshot from the population store (Bundle 10, prepared Nov 13; awaits Shreyas). Deployed as pipeline/people_full.py.

Why: the pipeline's people writers (daily.py "people" step, pool_grow.py, voters.py) write only person + first_seen, so every person
added after build_initial.py has blank joined / headline / about / followers. The population agent's store_v3 now keeps every
field of every pull (persons.parquet + records/part-*.parquet, lossless since 14:35Z Nov 13).

What it writes (warehouse snapshot tables, newest row per key wins):
  people          one FULL row per known person: every existing column kept (same names and types), store values fill
                  headline / about / joined / ph_followers / ph_followings / upvotes_total where the store has them, plus every
                  persons.parquet field as new columns (store_person_id, ph_user_id, name, bio, badges_count, streak, links_json,
                  badges_json, ranks_text_json, maker_history_json, header_json, in_pool, complete, pull_finished_utc,
                  pulls_merged, has_record, has_provenance) and record_sha256 / record_part.
  people_records  (with --records) the verbatim per-person record JSON (record_json), keyed by person, so people stays small.
Key: the warehouse's existing `person` (handle). Store rows are salted (store_person_id); a store person is joined only when
its salted id matches the hash of a handle already in the people table (rows are never added: that would change
incremental.py's known set and the pool's first_seen definition). No handle is
taken from the store and no new handle column is added; unmatched store people are counted, never written.
Never prints handles or values: counts only. The salt is read to hash, never printed.

usage (VM, from experiments/):  python3 -m pipeline.people_full                       # dry run: counts only
                                python3 -m pipeline.people_full --write --records     # one-off full rebuild
                                python3 -m pipeline.people_full --write --records --changed   # daily refresh (daily.py step)
"""
import glob, hashlib, json, os, subprocess, sys, tempfile
import numpy as np, pandas as pd
from . import warehouse as W

STORE = os.environ.get("PEOPLE_STORE", f"{W.BUCKET}/raw/population/store_v3")
EXISTING = ["person", "first_seen", "headline", "about", "twitter", "joined", "ph_followers", "ph_followings", "is_maker",
            "upvotes_total", "li_headline", "li_company", "li_location", "x_bio", "x_followers", "segments", "stacks", "reviews"]
STORE_COLS = ["ph_user_id", "name", "bio", "badges_count", "streak", "links_json", "badges_json", "ranks_text_json",
              "maker_history_json", "header_json", "in_pool", "complete", "pull_finished_utc", "pulls_merged", "has_record",
              "has_provenance"]


def salt():
    return subprocess.run(["gsutil", "cat", f"{W.BUCKET}/raw/population/_salt"], capture_output=True, text=True, check=True).stdout.strip()


def hid(sl, u):
    return "p_" + hashlib.sha256((sl + "producthunt:" + str(u).lower()).encode()).hexdigest()[:16]


def handles(con):
    """Every handle the warehouse already holds (no new handles enter the warehouse)."""
    q = lambda s: {r[0] for r in con.execute(s).fetchall() if isinstance(r[0], str) and r[0] and not r[0].startswith("[")}
    hs = q("SELECT person FROM people")
    for t, c in (("events", "person"), ("comments", "person"), ("follows", "person"), ("follows", "followee")):
        try:
            hs |= q(f"SELECT DISTINCT {c} FROM {t}")
        except Exception:  # noqa: BLE001  (table missing in a test cache)
            pass
    return hs


def _num(v, k):
    try:
        x = json.loads(v).get(k) if isinstance(v, str) else None
        return int(x) if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit()) else None
    except Exception:  # noqa: BLE001
        return None


def build(con, store_dir, sl, with_records=False):
    """-> (people frame to write, records frame or None, stats). store_dir holds persons.parquet (+ records/part-*.parquet)."""
    P = pd.read_parquet(f"{store_dir}/persons.parquet")
    # rows are written ONLY for people already in the people table: adding rows would change incremental.py's "known" set
    # (new-people queue) and the pool definition (first_seen); other warehouse handles are only counted
    allh = handles(con); hs = {r[0] for r in con.execute("SELECT person FROM people").fetchall() if isinstance(r[0], str)}
    key = {hid(sl, h): h for h in hs}; other = {hid(sl, h) for h in allh - hs}
    P = P[P.person_id.isin(key)].copy(); P["person"] = P.person_id.map(key)
    cur = con.execute("SELECT * FROM people").df(); ncols0 = len(cur.columns)
    cur = cur[[c for c in EXISTING if c in cur]]   # only the original columns: store columns are always rewritten from the store
    out = P[["person", "person_id"] + [c for c in STORE_COLS if c in P]].rename(columns={"person_id": "store_person_id"})
    out = out.merge(cur, on="person", how="left")
    # store values fill the existing columns (store first, then the old warehouse value), same column types as today
    fill = {"headline": P.set_index("person").headline, "about": P.set_index("person").bio,
            "joined": P.set_index("person").joined.dt.strftime("%Y-%m-%d") if "joined" in P else None,
            "ph_followers": P.set_index("person").header_json.map(lambda v: _num(v, "followers")),
            "ph_followings": P.set_index("person").header_json.map(lambda v: _num(v, "following")),
            "upvotes_total": P.set_index("person").header_json.map(lambda v: _num(v, "upvotes"))}
    for c, s in fill.items():
        if s is None:
            continue
        new = out.person.map(s)
        out[c] = new.where(new.notna() & (new.astype(str) != ""), out[c] if c in out else None)
    for c in EXISTING:
        if c not in out:
            out[c] = None
    out["ph_followers"] = pd.array(pd.to_numeric(out.ph_followers, errors="coerce").round(), dtype="Int64")
    out["ph_followings"] = pd.array(pd.to_numeric(out.ph_followings, errors="coerce").round(), dtype="Int64")
    out["upvotes_total"] = pd.to_numeric(out.upvotes_total, errors="coerce").astype("float64")
    out["is_maker"] = pd.array(out.is_maker, dtype="boolean")
    for c in ("headline", "about", "twitter", "joined", "li_headline", "li_company", "li_location", "x_bio", "segments", "stacks",
              "reviews", "first_seen"):
        out[c] = out[c].astype("string")
    out["x_followers"] = pd.to_numeric(out.x_followers, errors="coerce").astype("float64")
    out["has_provenance"] = out.has_provenance.astype("string") if "has_provenance" in out else None
    rec = None; out["record_sha256"] = None; out["record_part"] = None
    parts = sorted(glob.glob(f"{store_dir}/records/part-*.parquet"))
    if parts:
        keep = set(out.store_person_id); R_ = []
        for f in parts:
            R = pd.read_parquet(f, columns=["person_id", "record_sha256"] + (["record_json"] if with_records else []))
            R = R[R.person_id.isin(keep)].assign(record_part=os.path.basename(f)); R_.append(R)
        R = pd.concat(R_) if R_ else pd.DataFrame(columns=["person_id", "record_sha256", "record_part"])
        m = R.drop_duplicates("person_id", keep="last").set_index("person_id")
        out["record_sha256"] = out.store_person_id.map(m.record_sha256); out["record_part"] = out.store_person_id.map(m.record_part)
        if with_records:
            rec = m.reset_index().rename(columns={"person_id": "store_person_id"})
            rec["person"] = rec.store_person_id.map(dict(zip(out.store_person_id, out.person)))
            rec = rec[["person", "store_person_id", "record_sha256", "record_part", "record_json"]]
    out = out[EXISTING + [c for c in out.columns if c not in EXISTING]]
    st = {"store_persons": int(len(pd.read_parquet(f"{store_dir}/persons.parquet", columns=["person_id"]))),
          "people_handles": len(hs), "matched": int(len(out)),
          "store_people_matching_other_warehouse_handles_not_written": int(len(other & set(pd.read_parquet(f"{store_dir}/persons.parquet", columns=["person_id"]).person_id))), "people_rows_before": int(len(cur)),
          "people_cols_before": int(ncols0), "people_cols_after": int(len(out.columns)) + 1,
          "matched_with_joined": int(out.joined.notna().sum()), "matched_with_record": int(out.record_sha256.notna().sum()),
          "existing_people_not_in_store": int((~cur.person.isin(out.person)).sum())}
    return out, rec, st


def fetch_store(dst, with_records):
    os.makedirs(f"{dst}/records", exist_ok=True)
    subprocess.run(["gsutil", "-q", "cp", f"{STORE}/persons.parquet", dst], check=True)
    subprocess.run(["gsutil", "-q", "-m", "cp", f"{STORE}/records/part-*.parquet", f"{dst}/records/"], check=True)
    return dst


def changed(con, out, rec):
    """Daily refresh: keep only people whose store pull is new or changed since the last full write (pull_finished_utc /
    record_sha256 differ, or the person has no store columns yet), so the daily run appends small parts."""
    try:
        prev = con.execute("SELECT person, pull_finished_utc, record_sha256 FROM people").df()
    except Exception:  # noqa: BLE001  (first run: no store columns in the table yet)
        return out, rec
    m = out.merge(prev, on="person", how="left", suffixes=("", "_prev"))
    keep = m.pull_finished_utc_prev.isna() | (m.pull_finished_utc.astype(str) != m.pull_finished_utc_prev.astype(str)) | \
        (m.record_sha256.astype(str) != m.record_sha256_prev.astype(str))
    ids = set(m.person[keep.values])
    return out[out.person.isin(ids)], (rec[rec.person.isin(ids)] if rec is not None else None)


def main(argv):
    write, with_records, only_changed = "--write" in argv, "--records" in argv, "--changed" in argv
    con = W.connect(do_sync=True)
    tmp = tempfile.mkdtemp(prefix="people_full_")
    try:
        out, rec, st = build(con, fetch_store(tmp, with_records), salt(), with_records)
        if only_changed:
            out, rec = changed(con, out, rec)
        st.update(write=write, rows_written=int(len(out)) if write else 0, records_written=int(len(rec)) if (write and rec is not None) else 0)
        if write:
            W.write("people", out)
            if rec is not None and len(rec):
                for i in range(0, len(rec), 5000):   # parts of 5,000 records (each record ~40 KB)
                    W.write("people_records", rec.iloc[i:i + 5000])
        print(json.dumps(st))
        return st
    finally:
        subprocess.run(["rm", "-rf", tmp], check=False)


if __name__ == "__main__":
    main(sys.argv[1:])
