"""Dry run of the bundle-11 people step from store_v3 (no writes, counts only; the salt is read from a file, never printed).
usage: PEOPLE_SALT_FILE=<salt file> python test_people_store.py <dir with events.parquet + tabs.parquet> [<day>] [--sample N]
Runs this folder's daily.py against the local warehouse copy (warehouse.connect(do_sync=False)); with --sample N it first writes a
slice of N random store people to <dir>/slice/ and runs on that."""
import os, sys, time, types, shutil, tempfile, resource
HERE = os.path.dirname(os.path.abspath(__file__)); EXP = os.path.dirname(os.path.dirname(HERE))


def main(src, d="2026-11-13", sample=None):
    import numpy as np, pyarrow as pa, pyarrow.parquet as pq, pyarrow.compute as pc
    if sample:
        T = pq.read_table(f"{src}/tabs.parquet"); ids = np.array(T.column("person_id").unique().to_pylist(), dtype=object)
        keep = pa.array(np.random.default_rng(0).choice(ids, min(sample, len(ids)), replace=False).tolist())
        os.makedirs(f"{src}/slice", exist_ok=True)
        pq.write_table(T.filter(pc.is_in(T.column("person_id"), keep)), f"{src}/slice/tabs.parquet")
        E = pq.read_table(f"{src}/events.parquet", columns=["person_id", "kind", "target_id", "first_seen_at", "source"])
        pq.write_table(E.filter(pc.is_in(E.column("person_id"), keep)), f"{src}/slice/events.parquet"); src = f"{src}/slice"
    pkg = tempfile.mkdtemp(prefix="b11pkg_"); os.makedirs(f"{pkg}/pipeline")
    for f in os.listdir(f"{EXP}/pipeline"):
        if f.endswith(".py"):
            shutil.copy(f"{EXP}/pipeline/{f}", f"{pkg}/pipeline/{f}")
    shutil.copy(f"{HERE}/daily.py", f"{pkg}/pipeline/daily.py")
    sys.path[:0] = [pkg, EXP]
    if "curl_cffi" not in sys.modules:   # fetch.py imports it; the people step never fetches
        sys.modules["curl_cffi"] = types.ModuleType("curl_cffi"); sys.modules["curl_cffi"].requests = types.SimpleNamespace(Session=object)
    import pipeline.daily as D, pipeline.warehouse as W
    con = W.connect(do_sync=False); t = time.time()
    res, out = D.people_from_store(con, d, True, local=src)
    print(out); print("seconds", round(time.time() - t), "max_rss_GB", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2))
    if res:
        ev, fo, st, _ = res
        for nm, df, want in (("events", ev, ["person", "launch_id", "date", "kind", "date_quality"]),
                             ("follows", fo, ["person", "followee", "observed_on", "new_since_last"]),
                             ("fetch_state", st, ["person", "source", "last_fetched", "status", "items", "complete"])):
            assert list(df.columns) == want or df.empty, (nm, list(df.columns)); print(nm, len(df), "columns ok")
    shutil.rmtree(pkg, ignore_errors=True)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]; n = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else None
    if n: a = [x for x in a if x != str(n)]
    main(a[0], a[1] if len(a) > 1 else "2026-11-13", n)
