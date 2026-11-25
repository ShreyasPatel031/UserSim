"""PERSON-VOICE-1: tuned Qwen vs untuned Qwen vs Gemini Flash (history prompt) on person match, on the Task C rows of
test and forward days that have a second commenter (benchmark + FORWARD-C-1 overlays).

  python -m simharness.run_person_voice rows  --bench BENCH --forward-root FWD --out OUT   # rows, eval.jsonl, leak checks
  PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_person_voice flash --bench ... --cap 1.0
  python -m simharness.run_person_voice score --bench ... --gen tuned=gen_tuned.jsonl base=gen_base.jsonl

The Qwen generations come from a generate-only GPU job (simharness/finetune/gcp/launch.sh with FT_ADAPTER) reading
OUT/eval.jsonl (the fine-tune prompt, simharness.finetune.export.prompt_for). OUT holds real and simulated comment text
and person indexes: private.
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

TAU = 0.7497
GROUPS = ("all", "forward days (Nov 23-24)", "test days, rows new from the stream", "test days, rows already in the benchmark")


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def _task(a):
    from simharness import task_c as tc
    from simharness.bench import Benchmark
    dirs = sorted(d for d in glob.glob(os.path.join(a.forward_root, "20*")) if os.path.exists(f"{d}/comments.parquet"))
    b = Benchmark(a.bench, overlays=dirs)
    T = tc.TaskC(b)
    T.tau = TAU
    return tc, b, T


def stage_rows(a):
    from simharness import task_c as tc
    from simharness.bench import Benchmark, _day_bounds_utc, day_ord
    from simharness.finetune.export import prompt_for
    old = tc.TaskC(Benchmark(a.bench))._day_of
    old_keys = set(zip(old["person_idx"].tolist(), old["item_idx"].tolist()))
    _, b, T = _task(a)
    parts = []
    for split in ("test", "forward"):
        r = T.rows(split)
        r = r[r["same_item_other"].notna()].copy()
        r["split"] = split
        parts.append(r)
    R = pd.concat(parts, ignore_index=True)
    R["is_new"] = [(int(p), int(i)) not in old_keys for p, i in zip(R["person_idx"], R["item_idx"])]
    R["group"] = np.where(R["split"] == "forward", GROUPS[1], np.where(R["is_new"], GROUPS[2], GROUPS[3]))
    R.to_parquet(f"{a.out}/rows.parquet")
    # leak checks and the eval file
    bad_day = bad_ts = own_item = same_day_item = 0
    with open(f"{a.out}/eval.jsonl", "w") as f:
        for r in R.itertuples():
            hb = b.batch(r.day, np.array([r.person_idx]))
            ev = hb.events(0)
            start, _ = _day_bounds_utc(r.day, b.cfg.day_tz)
            bad_day += int((ev["day_ord"] >= day_ord(r.day)).sum())
            bad_ts += int((ev["ts"].notna() & (ev["ts"] >= start)).sum())
            own_item += int((ev["item_idx"] == r.item_idx).sum())
            p = prompt_for(b, r)
            same_day_item += int(str(r.text)[:60] in p)
            f.write(json.dumps({"messages": [{"role": "user", "content": p}],
                                "meta": {"split": r.split, "person_idx": int(r.person_idx), "item_idx": int(r.item_idx),
                                         "day": r.day}}) + "\n")
    train_last = "2026-10-31"
    res = {"rows": int(len(R)), "by_group": R["group"].value_counts().to_dict(), "people": int(R["person_idx"].nunique()),
           "launches": int(R["item_idx"].nunique()), "days": int(R["day"].nunique()),
           "leak": {"history_events_on_or_after_day": bad_day, "history_events_timed_after_day_start": bad_ts,
                    "the_launch_itself_in_history": own_item, "real_comment_text_inside_prompt": same_day_item,
                    "fine_tune_training_rows_last_day": train_last,
                    "rows_on_or_before_training_last_day": int((R["day"] <= train_last).sum())}}
    json.dump(res, open(f"{a.out}/rows_info.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
    sync([f"{a.out}/rows.parquet", f"{a.out}/eval.jsonl", f"{a.out}/rows_info.json"], a.sync)


def stage_flash(a):
    from simharness.models.llm import Budget, GeminiBackend
    tc, b, T = _task(a)
    R = pd.read_parquet(f"{a.out}/rows.parquet")
    cp = f"{a.out}/flash_cache.pkl"
    cache = pickle.load(open(cp, "rb")) if os.path.exists(cp) else {}
    budget = Budget(a.cap)
    backend = GeminiBackend("gemini-2.5-flash", price_in=0.30, price_out=2.50, temperature=0.7, budget=budget)
    model = tc.PromptComment(backend, label="pv1")
    for i in range(0, len(R), 150):
        T.generate(model, R.iloc[i:i + 150], workers=10, cache=cache)
        pickle.dump(cache, open(cp, "wb"))
        sync([cp], a.sync)
        print("flash", i + 150, round(backend.cost_usd, 4), flush=True)
    rows = [{"meta": {"person_idx": int(r.person_idx), "item_idx": int(r.item_idx)},
             "text": cache.get((model.name, int(r.person_idx), int(r.item_idx)), "")} for r in R.itertuples()]
    with open(f"{a.out}/gen_flash.jsonl", "w") as f:
        for x in rows:
            f.write(json.dumps(x) + "\n")
    json.dump({"cost_usd_estimated": round(backend.cost_usd, 4), "calls": backend.calls, "empty": sum(not x["text"] for x in rows)},
              open(f"{a.out}/flash_info.json", "w"))
    print(json.dumps({"cost_usd": backend.cost_usd, "calls": backend.calls}))
    sync([f"{a.out}/gen_flash.jsonl", f"{a.out}/flash_info.json"], a.sync)


def _load_gen(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        out[(int(r["meta"]["person_idx"]), int(r["meta"]["item_idx"]))] = r["text"]
    return out


def stage_score(a):
    tc, b, T = _task(a)
    R = pd.read_parquet(f"{a.out}/rows.parquet")
    gens = dict(g.split("=", 1) for g in a.gen)
    gens.setdefault("flash", f"{a.out}/gen_flash.jsonl")
    sc = {}
    for name, path in gens.items():
        g = _load_gen(path)
        sc[name] = T.score(R, [g.get((int(r.person_idx), int(r.item_idx))) for r in R.itertuples()])
    sc["own_last_comment"] = T.score(R, [x if isinstance(x, str) else None for x in R["own_past_comment"]])
    key = ["day", "person_idx", "item_idx"]
    res = {"tau": TAU, "groups": {}}
    pairs = [("tuned", "flash"), ("tuned", "base"), ("flash", "base"), ("tuned", "own_last_comment")]
    for gname in GROUPS:
        sub = R if gname == "all" else R[R["group"] == gname]
        k = sub[key]
        e = {"rows": int(len(sub)), "days": int(sub["day"].nunique()), "models": {}, "paired": {}}
        s = {n: df.merge(k, on=key) for n, df in sc.items()}
        for n, df in s.items():
            d = df[df["has"]] if n == "own_last_comment" else df
            e["models"][n] = {**tc.summarize(d, n_boot=2000), "empty": int((~df["has"]).sum())}
        for x, y in pairs:
            if x in s and y in s:
                for m in ("own_vs_other", "match"):
                    e["paired"][f"{x} - {y}: {m}"] = tc.paired_diff(s[x], s[y], m, n_boot=2000)
        res["groups"][gname] = e
        pct = lambda d: f"{100 * d['value']:.1f} [{100 * d['ci95'][0]:.1f}, {100 * d['ci95'][1]:.1f}]"  # noqa: E731
        print(gname, e["rows"], flush=True)
        for n, v in e["models"].items():
            print(f"  {n:18s} person {pct(v['own_vs_other'])} | content {pct(v['match'])} | len {v['len_ratio_median']['value']:.2f} | empty {v['empty']}")
        for n, v in e["paired"].items():
            print(f"  {n}: {100 * v['diff']:+.1f} [{100 * v['ci95'][0]:+.1f}, {100 * v['ci95'][1]:+.1f}] n={v['rows']}")
    json.dump(res, open(f"{a.out}/person_voice_scores.json", "w"), indent=1)
    sync([f"{a.out}/person_voice_scores.json"], a.sync)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["rows", "flash", "score"])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--forward-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sync", default="")
    ap.add_argument("--cap", type=float, default=1.0)
    ap.add_argument("--gen", nargs="*", default=[])
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
