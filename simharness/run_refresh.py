"""Nightly refresh of the benchmark tables from the current store, with the forward overlays applied.

  python -m simharness.run_refresh --store STORE --out BENCH [--day D] [--prev DIR] [--forward-root FWD]
                                   [--lineup today_0005.json] [--slug-items items.parquet ...] [--sync gs://prefix]

  STORE   a local copy of the population store: persons.parquet, tabs.parquet, events.parquet and, for comment text,
          records/part-*.parquet (without the records no comment text is read and the comment check will fail)
  BENCH   a builds folder. Each run writes BENCH/<UTC stamp>/ and, only when every check passes, points
          BENCH/latest (a one-line text file with the stamp) at it. `Benchmark(BENCH)` follows the pointer.
  --prev  the build to stay compatible with (default: the build BENCH/latest points at). Needed on the first run.
  --day   the day the histories are for (default: today in the benchmark's time zone). With --lineup, that day's
          00:05 line-up is appended to the items so prompts for D can be built before D's overlay exists.

What a refresh keeps and adds:
  * every person and item of the previous build keeps its index; people complete now and new launches are appended;
  * history, comments, pools and positives are rebuilt from the current store (same schema, same salted keys);
  * the forward overlays under --forward-root (live-stream comments, line-up items) are written into the tables, so a
    history for day D holds everything dated before D that the store and the stream hold.

Checks before the pointer moves (any failure leaves BENCH/latest untouched, keeps the build as <stamp>.failed and
exits 1): row counts not lower than the previous build; no person_idx or item_idx reassigned; same columns and
types; no event dated on or after D in any history for D; the new build loads. Not scheduled by this module.

Everything under BENCH is private (salted ids, comment text).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TABLES = ("people", "items", "history", "comments", "pool", "positives")


def _rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def _load_tables(d: str) -> dict:
    t = {k: pd.read_parquet(f"{d}/{k}.parquet") for k in TABLES}
    t["meta"] = json.load(open(f"{d}/meta.json"))
    return t


def check_history_before(bench, day: str, sample: int = 400, seed: int = 0) -> dict:
    """No event dated on or after `day` may reach a history built for `day`."""
    from simharness.bench import KIND_CODE, _day_bounds_utc, day_ord
    from simharness.schema import COMMENT, ENDORSE
    o = day_ord(day)
    start, _ = _day_bounds_utc(day, bench.cfg.day_tz)
    h = bench.hist
    st = bench.state(day)
    end = h[(h["kind"] == KIND_CODE[ENDORSE]) & (h["day_ord"] < o)]
    com = h[(h["kind"] == KIND_CODE[COMMENT]) & (h["day_ord"] < o) & (h["ts"].isna() | (h["ts"] < start))]
    res = {"day": day,
           "endorsements_in_state": int(st["n_all"].sum()), "endorsements_dated_before_day": int(len(end)),
           "comments_in_state": int(st["n_comments"].sum()), "comments_dated_before_day": int(len(com)),
           "events_on_or_after_day_in_tables": int((h["day_ord"] >= o).sum())}
    rng = np.random.default_rng(seed)
    people = rng.choice(h["person_idx"].unique(), min(sample, h["person_idx"].nunique()), replace=False)
    hb = bench.batch(day, people)
    late_day = late_ts = late_line = 0
    for j in range(len(people)):
        ev = hb.events(j)
        late_day += int((ev["day_ord"] >= o).sum())
        late_ts += int((ev["ts"].notna() & (ev["ts"] >= start)).sum())
        for line in hb.render(j).split("\n"):
            if line.startswith("- 20") and line[2:12] >= day:
                late_line += 1
    res.update(people_sampled=int(len(people)), sampled_history_events_on_or_after_day=late_day,
               sampled_history_events_timed_after_day_start=late_ts, rendered_lines_on_or_after_day=late_line)
    res["ok"] = bool(res["endorsements_in_state"] == res["endorsements_dated_before_day"]
                     and res["comments_in_state"] == res["comments_dated_before_day"]
                     and late_day == 0 and late_ts == 0 and late_line == 0)
    return res


def run_checks(prev: dict, new_dir: str, day: str) -> dict:
    from simharness.bench import Benchmark
    new = _load_tables(new_dir)
    c = {"row_counts": {}, "ok": True}
    for k in ("people", "items", "history", "comments"):
        c["row_counts"][k] = {"previous": int(len(prev[k])), "new": int(len(new[k])), "ok": bool(len(new[k]) >= len(prev[k]))}
    for kind, n_prev in prev["history"].groupby("kind").size().items():
        n_new = int((new["history"]["kind"] == kind).sum())
        c["row_counts"][f"history_kind_{int(kind)}"] = {"previous": int(n_prev), "new": n_new, "ok": bool(n_new >= n_prev)}
    pp, npp = prev["people"].sort_values("person_idx"), new["people"].sort_values("person_idx")
    same_p = bool((npp["person_id"].to_numpy()[:len(pp)] == pp["person_id"].to_numpy()).all()
                  and (npp["person_idx"].to_numpy() == np.arange(len(npp))).all() and npp["person_id"].is_unique)
    pi, ni = prev["items"].sort_values("item_idx"), new["items"].sort_values("item_idx")
    same_i = bool((ni["item_id"].astype(str).to_numpy()[:len(pi)] == pi["item_id"].astype(str).to_numpy()).all()
                  and (ni["item_idx"].to_numpy() == np.arange(len(ni))).all() and ni["item_id"].is_unique)
    c["no_person_idx_reassigned"] = same_p
    c["no_item_idx_reassigned"] = same_i
    c["people_appended"], c["items_appended"] = int(len(npp) - len(pp)), int(len(ni) - len(pi))
    c["schema_same"] = {k: bool(list(prev[k].columns) == list(new[k].columns)
                                and [str(x) for x in prev[k].dtypes] == [str(x) for x in new[k].dtypes]) for k in TABLES}
    bench = Benchmark(new_dir)
    c["history_before_day"] = check_history_before(bench, day)
    c["loads"] = True
    c["ok"] = bool(all(v["ok"] for v in c["row_counts"].values()) and same_p and same_i
                   and all(c["schema_same"].values()) and c["history_before_day"]["ok"])
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--day")
    ap.add_argument("--prev")
    ap.add_argument("--forward-root")
    ap.add_argument("--lineup")
    ap.add_argument("--slug-items", action="append", default=[])
    ap.add_argument("--sync", default="")
    a = ap.parse_args(argv)
    from simharness import bench as B
    from simharness.domains import producthunt as ph
    from simharness.schema import COMMENT
    t0 = time.time()
    timing = {}
    os.makedirs(a.out, exist_ok=True)
    latest = os.path.join(a.out, "latest")
    prev_dir = a.prev or (os.path.join(a.out, open(latest).read().strip()) if os.path.exists(latest) else None)
    if not prev_dir or not os.path.exists(f"{prev_dir}/meta.json"):
        print("no previous build: pass --prev", file=sys.stderr)
        return 2
    prev = _load_tables(prev_dir)
    cfg = B.BenchConfig(**{k: tuple(v) if isinstance(v, list) else v for k, v in prev["meta"]["config"].items()})
    cfg.forward_from = None                      # the base build has no forward days; overlays set it below
    day = a.day or dt.datetime.now(ZoneInfo(cfg.day_tz)).date().isoformat()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tmp, final = os.path.join(a.out, stamp + ".tmp"), os.path.join(a.out, stamp)
    shutil.rmtree(tmp, ignore_errors=True)

    # 1. comment text from the store's verbatim records
    recs = sorted(glob.glob(os.path.join(a.store, "records", "part-*.parquet")))
    texts = None
    if recs:
        parts = [ph.extract_comment_texts([f]) for f in recs]          # one part in memory at a time
        texts = pd.concat(parts, ignore_index=True).drop_duplicates(["person_id", "comment_id"])
        del parts
    timing["comment_text_s"] = round(time.time() - t0, 1)

    # 2. launch slugs (the store targets comments by slug): carried forward, recovered from the store, and new ones
    t = time.time()
    events_path = os.path.join(a.store, "events.parquet")
    slugs = {}
    kf = f"{prev_dir}/item_keys.parquet"
    if os.path.exists(kf):
        k = pd.read_parquet(kf)
        slugs.update({i: s for i, s in zip(k["item_id"].astype(str), k["slug"]) if s})
    slugs.update(ph.recover_slugs(events_path, prev["people"], prev["items"], prev["history"], B.KIND_CODE[COMMENT]))
    for f in a.slug_items:
        k = pd.read_parquet(f)
        idc = "item_id" if "item_id" in k.columns else "id"
        slugs.update({str(i): s for i, s in zip(k[idc], k["slug"]) if isinstance(s, str) and s})
    overlays = []
    if a.forward_root:
        from simharness.run_forward_day import overlay_dirs
        overlays = overlay_dirs(a.forward_root)
        for d in overlays:
            k = pd.read_parquet(f"{d}/items.parquet")
            if "slug" in k.columns:
                slugs.update({str(i): s for i, s in zip(k["item_id"], k["slug"]) if isinstance(s, str) and s})
    lineup_items = None
    if a.lineup:
        from simharness.domains.ph_live_comments import read_lineup
        lineup_items, _ = read_lineup(a.lineup, day)
        slugs.update({str(i): s for i, s in zip(lineup_items["item_id"], lineup_items["slug"]) if s})
    timing["slugs_s"] = round(time.time() - t, 1)

    # 3. base tables from the store, indexes kept
    t = time.time()
    tables = ph.refresh_tables(a.store, prev["people"], prev["items"], slugs, texts)
    del texts
    B.build(tables, tmp, cfg, prev_people=prev["people"], prev_items=prev["items"])
    del tables
    timing["build_s"] = round(time.time() - t, 1)

    # 4. write the overlays and the day's line-up into the tables
    t = time.time()
    b = B.Benchmark(tmp)
    infos = b.add_overlays(overlays) if overlays else []
    if lineup_items is not None:
        known = set(b.items["item_id"].astype(str))
        new = lineup_items[~lineup_items["item_id"].isin(known)].sort_values("item_id").reset_index(drop=True)
        if len(new):
            add = pd.DataFrame({"item_idx": np.arange(len(b.items), len(b.items) + len(new), dtype=np.int32),
                                "item_id": new["item_id"].astype(b.items["item_id"].dtype),
                                "day": new["day"].astype(b.items["day"].dtype),
                                "day_ord": new["day"].map(B.day_ord).astype(np.int32),
                                "title": new["title"].astype(b.items["title"].dtype),
                                "summary": new["summary"].astype(b.items["summary"].dtype),
                                "description": new["description"].astype(b.items["description"].dtype),
                                "tags": new["tags"].map(list)})
            b.items = pd.concat([b.items, add], ignore_index=True)
        infos.append({"overlay": f"line-up {day}", "items_new": int(len(new))})
    b.items.to_parquet(f"{tmp}/items.parquet")
    b.hist.sort_values(["day_ord", "person_idx"], kind="stable").reset_index(drop=True).to_parquet(f"{tmp}/history.parquet")
    b.comments.reset_index(drop=True).to_parquet(f"{tmp}/comments.parquet")
    keys = pd.DataFrame({"item_id": b.items["item_id"].astype(str)})
    keys["slug"] = keys["item_id"].map(slugs).fillna("")
    keys.to_parquet(f"{tmp}/item_keys.parquet")
    meta = json.load(open(f"{tmp}/meta.json"))
    if overlays or lineup_items is not None:
        meta["config"]["forward_from"] = B.ord_day(B.day_ord(cfg.test[1]) + 1)
    meta.update(n_items=int(len(b.items)), n_history_events=int(len(b.hist)), n_comment_texts=int(len(b.comments)))
    meta["refresh"] = {"stamp": stamp, "for_day": day, "previous_build": os.path.basename(os.path.normpath(prev_dir)),
                       "overlays_applied": infos, "items_with_slug": int((keys["slug"] != "").sum()),
                       "store_files": {f: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(os.path.join(a.store, f))))
                                       for f in ("persons.parquet", "tabs.parquet", "events.parquet")},
                       "record_parts": len(recs)}
    json.dump(meta, open(f"{tmp}/meta.json", "w"), indent=1)
    del b
    timing["overlays_s"] = round(time.time() - t, 1)

    # 5. checks, then the pointer
    t = time.time()
    checks = run_checks(prev, tmp, day)
    timing["checks_s"] = round(time.time() - t, 1)
    timing["total_s"] = round(time.time() - t0, 1)
    meta["refresh"].update(checks=checks, timing=timing, peak_memory_mb=_rss_mb())
    json.dump(meta, open(f"{tmp}/meta.json", "w"), indent=1, default=float)
    summary = {"stamp": stamp, "for_day": day, "ok": checks["ok"], "row_counts": checks["row_counts"],
               "people_appended": checks["people_appended"], "items_appended": checks["items_appended"],
               "timing": timing, "peak_memory_mb": meta["refresh"]["peak_memory_mb"]}
    if not checks["ok"]:
        shutil.rmtree(final + ".failed", ignore_errors=True)
        os.rename(tmp, final + ".failed")
        print(json.dumps(summary, indent=1))
        print("CHECKS FAILED: pointer not moved", file=sys.stderr)
        return 1
    os.rename(tmp, final)
    with open(latest + ".tmp", "w") as f:
        f.write(stamp + "\n")
    os.replace(latest + ".tmp", latest)
    if a.sync:
        dest = a.sync.rstrip("/")
        r = subprocess.run(["gsutil", "-q", "-m", "cp", *glob.glob(f"{final}/*"), f"{dest}/{stamp}/"], check=False)
        if r.returncode == 0:                    # the remote pointer moves only after the build is fully copied
            subprocess.run(["gsutil", "-q", "cp", latest, f"{dest}/latest"], check=False)
        summary["synced"] = r.returncode == 0
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
