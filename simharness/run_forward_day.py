"""Forward days for Task C: build a day's overlay from the live comment stream, report, and score the new rows.

  # build one day (run the morning after; earlier overlays under --forward-root are loaded first)
  python -m simharness.run_forward_day --day 2026-11-23 --bench BENCH --forward-root FWD \\
      --stream comments_ts.jsonl --lineup today_0005.json --persons persons.parquet [--sync gs://.../forward]

  # per-day table and totals (no model call)
  python -m simharness.run_forward_day --report --bench BENCH --forward-root FWD --out OUT

  # person match on the NEW rows: history prompt vs item-only prompt, paired (Gemini; --cap is a hard dollar limit)
  PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_forward_day --score --bench BENCH \\
      --forward-root FWD --out OUT --cap 1.0 [--gen-cache earlier_gen_cache.pkl]

Using the overlays elsewhere:
    bench = Benchmark(BENCH, overlays=sorted(glob.glob(FWD + "/20*")))
    rows = TaskC(bench).rows("forward")        # days after the test split; rows("test") gains the new test-day rows

Overlays and OUT hold real comment text and person indexes: private, never in this repository.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import subprocess

import numpy as np
import pandas as pd

REFS = ("floor_other_item", "own_past_comment", "same_item_other")


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def overlay_dirs(root: str, before: str | None = None) -> list[str]:
    ds = sorted(d for d in glob.glob(os.path.join(root, "20*")) if os.path.exists(os.path.join(d, "comments.parquet")))
    return [d for d in ds if before is None or os.path.basename(d) < before]


def build(a):
    from simharness.bench import Benchmark
    from simharness.domains.ph_live_comments import build_day, write_overlay
    bench = Benchmark(a.bench, overlays=overlay_dirs(a.forward_root, before=a.day))
    items, comments, rep = build_day(bench, a.day, a.stream, a.lineup, a.persons)
    have = set(zip(bench.comments["person_idx"].to_numpy().tolist(), bench.comments["item_idx"].to_numpy().tolist()))
    new = np.array([(int(p), int(i)) not in have for p, i in zip(comments["person_idx"], comments["item_idx"])], dtype=bool)
    files = write_overlay(os.path.join(a.forward_root, a.day), items, comments[new].reset_index(drop=True), rep)
    print(json.dumps(rep))
    sync(files, f"{a.sync.rstrip('/')}/{a.day}" if a.sync else "")


def _load(a):
    from simharness import task_c as tc
    from simharness.bench import Benchmark
    dirs = overlay_dirs(a.forward_root)
    b0 = Benchmark(a.bench)
    old = tc.TaskC(b0)._day_of
    old = old[~old["is_maker"]]
    old_keys = set(zip(old["person_idx"].tolist(), old["item_idx"].tolist()))
    b1 = Benchmark(a.bench, overlays=dirs)
    T = tc.TaskC(b1)
    rows = {s: T.rows(s) for s in ("test", "forward")}
    for s, r in rows.items():
        r["is_new"] = [(int(p), int(i)) not in old_keys for p, i in zip(r["person_idx"], r["item_idx"])]
    metas = {os.path.basename(d): json.load(open(os.path.join(d, "meta.json"))) for d in dirs}
    return tc, b1, T, rows, metas


def report(a):
    tc, b1, T, rows, metas = _load(a)
    allr = pd.concat([rows["test"].assign(split="test"), rows["forward"].assign(split="forward")], ignore_index=True)
    per_day = []
    for d in sorted(metas):
        m, r = metas[d], allr[allr["day"] == d]
        n = r[r["is_new"]]
        per_day.append({"day": d, "split": b1.cfg.split_of(d), "comments_in_stream": m["comments_in_stream"],
                        "top_level_on_the_day": m["written_on_the_day"],
                        "by_complete_held_people": m["by_complete_held_people"],
                        "kept_by_the_builder": m["first_per_person_and_launch"],
                        "already_in_benchmark": m["already_in_benchmark"], "new_rows": int(len(n)),
                        "stream_covers_the_whole_day": m.get("stream_covers_the_whole_day"),
                        "new_rows_with_a_second_commenter": int(n["same_item_other"].notna().sum()),
                        "new_rows_people": int(n["person_idx"].nunique()),
                        "task_c_rows_that_day_before": int((~r["is_new"]).sum()), "task_c_rows_that_day_now": int(len(r))})
    tot = {}
    for s in ("test", "forward"):
        r = rows[s]
        tot[s] = {"rows_before": int((~r["is_new"]).sum()), "rows_now": int(len(r)), "new_rows": int(r["is_new"].sum()),
                  "rows_with_a_second_commenter_now": int(r["same_item_other"].notna().sum()),
                  "people_now": int(r["person_idx"].nunique()), "launches_now": int(r["item_idx"].nunique()),
                  "days": int(r["day"].nunique())}
    tot["test_plus_forward"] = {k: tot["test"][k] + tot["forward"][k] for k in ("rows_before", "rows_now", "new_rows",
                                                                                 "rows_with_a_second_commenter_now")}
    res = {"per_day": per_day, "totals": tot, "overlays_loaded": b1.overlays}
    os.makedirs(a.out, exist_ok=True)
    json.dump(res, open(f"{a.out}/forward_report.json", "w"), indent=1)
    print(pd.DataFrame(per_day).to_string(index=False))
    print(json.dumps(tot, indent=1))
    sync([f"{a.out}/forward_report.json"], a.sync)
    return res


def score(a):
    from simharness.models.llm import Budget, GeminiBackend
    tc, b1, T, rows, metas = _load(a)
    os.makedirs(a.out, exist_ok=True)
    cache_path = f"{a.out}/gen_cache_forward.pkl"
    cache = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
    if a.gen_cache and os.path.exists(a.gen_cache):          # earlier generations for the old rows (read only)
        for k, v in pickle.load(open(a.gen_cache, "rb")).items():
            cache.setdefault(k, v)
    budget = Budget(a.cap)
    allr = pd.concat([rows["test"].assign(split="test"), rows["forward"].assign(split="forward")], ignore_index=True)
    if a.max_new and allr["is_new"].sum() > a.max_new:
        # fixed subsample of the new rows to stay inside the cap: every forward-day row, the rest spread over days
        rng = np.random.default_rng(0)
        fw = allr.index[allr["is_new"] & (allr["split"] == "forward")]
        te = allr.index[allr["is_new"] & (allr["split"] == "test")]
        keep = set(fw.tolist()) | set(rng.choice(te, max(a.max_new - len(fw), 0), replace=False).tolist())
        allr = allr[~allr["is_new"] | allr.index.isin(keep)].reset_index(drop=True)
    groups = {"new rows (test days + forward days)": allr[allr["is_new"]],
              "new rows, test days Nov 11-22": allr[allr["is_new"] & (allr["split"] == "test")],
              "new rows, forward days": allr[allr["split"] == "forward"],
              "old test rows (already in the benchmark)": allr[~allr["is_new"] & (allr["split"] == "test")]}
    name = a.model
    res = {"tau": T.tau, "model": name, "temperature": a.temperature, "groups": {}, "spend_usd": {},
           "new_rows_scored": int(allr["is_new"].sum()), "new_rows_subsample_limit": a.max_new or None}
    scored = {}
    for kind, cls in (("plain", tc.PlainComment), ("history", tc.PromptComment)):
        backend = GeminiBackend(name, price_in=0.30, price_out=2.50, temperature=a.temperature, budget=budget)
        model = cls(backend)
        new = groups["new rows (test days + forward days)"].reset_index(drop=True)
        old = groups["old test rows (already in the benchmark)"].reset_index(drop=True)
        cached_old = old[[(model.name, int(p), int(i)) in cache for p, i in zip(old["person_idx"], old["item_idx"])]]
        texts_new = T.generate(model, new, workers=10, cache=cache)
        pickle.dump(cache, open(cache_path, "wb"))
        texts_old = T.generate(model, cached_old.reset_index(drop=True), workers=10, cache=cache)  # cache hits only
        scored[kind] = pd.concat([T.score(new, texts_new), T.score(cached_old.reset_index(drop=True), texts_old)],
                                 ignore_index=True)
        res["spend_usd"][model.name] = round(backend.cost_usd, 4)
        res.setdefault("calls", {})[model.name] = backend.calls
        res.setdefault("old_rows_from_earlier_cache", {})[model.name] = int(len(cached_old))
    key = ["day", "person_idx", "item_idx"]
    for gname, g in groups.items():
        k = g[key].drop_duplicates()
        e = {"rows": int(len(g))}
        sub = {kind: df.merge(k, on=key) for kind, df in scored.items()}
        if len(sub["history"]) >= 20:
            for kind in ("plain", "history"):
                e[kind] = {**tc.summarize(sub[kind]), "empty": int((~sub[kind]["has"]).sum())}
            e["history_minus_plain"] = {m: tc.paired_diff(sub["history"], sub["plain"], m)
                                        for m in ("match", "sim", "own_vs_other")}
            for ref in REFS:
                e[ref] = tc.summarize(T.score_reference(g.reset_index(drop=True), ref))
        res["groups"][gname] = e
        print(gname, json.dumps({kk: (vv["match"] if isinstance(vv, dict) and "match" in vv else None)
                                 for kk, vv in e.items() if kk in ("plain", "history")}), flush=True)
    res["budget_spent_usd"] = round(budget.spent, 4)
    json.dump(res, open(f"{a.out}/forward_score.json", "w"), indent=1, default=float)
    sync([f"{a.out}/forward_score.json"], a.sync)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--bench", required=True)
    ap.add_argument("--forward-root", required=True)
    ap.add_argument("--stream")
    ap.add_argument("--lineup")
    ap.add_argument("--persons")
    ap.add_argument("--out", default="")
    ap.add_argument("--sync", default="")
    ap.add_argument("--cap", type=float, default=1.0)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--gen-cache", default="")
    ap.add_argument("--max-new", type=int, default=0)
    a = ap.parse_args(argv)
    if a.report:
        report(a)
    elif a.score:
        score(a)
    else:
        if not (a.day and a.stream and a.lineup and a.persons):
            ap.error("--day needs --stream, --lineup and --persons")
        build(a)


if __name__ == "__main__":
    main()
