"""Task C first run: references, the item-only prompt and the history-built prompt on the same rows.

    PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_taskc --bench BENCH --out OUT \
        --models gemini-2.5-flash-lite gemini-2.5-flash

Generations are cached in OUT/gen_cache.pkl, so a re-score costs no model calls. OUT holds real and simulated comment
text: keep it private (never in this repository).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle

from simharness import task_c as tc
from simharness.bench import Benchmark
from simharness.models.llm import GeminiBackend

PRICES = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}  # USD per 1M tokens in / out
REFS = ("floor_other_item", "own_past_comment", "same_item_other")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", nargs="+", default=["gemini-2.5-flash-lite"])
    ap.add_argument("--val-rows", type=int, default=400)
    ap.add_argument("--temperature", type=float, default=0.7)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T = tc.TaskC(Benchmark(a.bench))
    cache_path = f"{a.out}/gen_cache.pkl"
    cache = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
    res = {"tau": T.tau, "floor": T.floor, "embedder": T.emb.name, "splits": {}, "spend_usd": {}}
    for split, cap in (("val", a.val_rows), ("test", None)):
        rows = T.rows(split, max_rows=cap)
        R = {"rows": len(rows), "items": int(rows.item_idx.nunique()), "people": int(rows.person_idx.nunique()),
             "days": int(rows.day.nunique()), "models": {}, "paired": {}}
        for ref in REFS:
            R["models"][ref] = tc.summarize(T.score_reference(rows, ref))
        for name in a.models:
            pin, pout = PRICES[name]
            scored = {}
            for kind, cls in (("plain", tc.PlainComment), ("history", tc.PromptComment)):
                backend = GeminiBackend(name, price_in=pin, price_out=pout, temperature=a.temperature)
                model = cls(backend)
                texts = T.generate(model, rows, workers=12, cache=cache)
                pickle.dump(cache, open(cache_path, "wb"))
                scored[kind] = T.score(rows, texts)
                R["models"][model.name] = {**tc.summarize(scored[kind]), "empty": int((~scored[kind]["has"]).sum())}
                res["spend_usd"][f"{model.name}/{split}"] = round(backend.cost_usd, 3)
            for metric in ("match", "sim", "own_vs_other"):
                R["paired"][f"{name}:history-plain:{metric}"] = tc.paired_diff(scored["history"], scored["plain"], metric)
        res["splits"][split] = R
        print(split, json.dumps(R["paired"]), flush=True)
    json.dump(res, open(f"{a.out}/taskc_v0_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
