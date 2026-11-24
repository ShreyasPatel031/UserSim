"""Task C context ablation: what should a prompt show about the person? Same model, same rows, different history.

    PYTHONPATH=src:. GOOGLE_CLOUD_PROJECT=... python -m simharness.run_taskc_context --bench BENCH --out OUT \\
        [--model gemini-2.5-flash] [--tau 0.7497]

Variants (person match of each, and each minus the baseline, paired, day-clustered):
  base        30 latest upvoted launches + 10 latest comments     (the history prompt used so far)
  comments30  30 latest upvoted launches + 30 latest comments
  comments    10 latest comments only
  upvotes     30 latest upvoted launches only
  retrieved   30 latest upvoted launches + the 10 past comments most similar to this launch
Scores every validation and test row. OUT holds real and simulated text: keep it private.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle

from simharness import task_c as tc
from simharness.bench import Benchmark
from simharness.models.llm import GeminiBackend
from simharness.run_taskc import PRICES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--tau", type=float)
    ap.add_argument("--temperature", type=float, default=0.7)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    bench = Benchmark(a.bench)
    T = tc.TaskC(bench)
    if a.tau:
        T.tau = a.tau
    cache_path = f"{a.out}/gen_cache.pkl"
    cache = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
    pin, pout = PRICES[a.model]
    res = {"model": a.model, "tau": T.tau, "splits": {}, "spend_usd": 0.0}
    for split in ("val", "test"):
        rows = T.rows(split)
        mk = lambda: GeminiBackend(a.model, price_in=pin, price_out=pout, temperature=a.temperature)  # noqa: E731
        variants = {
            "base": tc.PromptComment(mk(), 30, 10, label="base"),
            "comments30": tc.PromptComment(mk(), 30, 30, label="comments30"),
            "comments": tc.PromptComment(mk(), 0, 10, label="comments"),
            "upvotes": tc.PromptComment(mk(), 30, 0, label="upvotes"),
            "retrieved": tc.RetrievedComment(mk(), 30, 10),
        }
        variants["retrieved"].prepare(bench, rows, T.emb)
        scored, R = {}, {"rows": len(rows), "models": {}, "paired": {}}
        for name, model in variants.items():
            texts = T.generate(model, rows, workers=12, cache=cache)
            pickle.dump(cache, open(cache_path, "wb"))
            scored[name] = T.score(rows, texts)
            R["models"][name] = {**tc.summarize(scored[name], n_boot=1000), "empty": int((~scored[name]["has"]).sum()),
                                 "cost_usd": round(model.cost_usd, 3)}
            res["spend_usd"] += model.cost_usd
            v = R["models"][name]
            print(split, name, "person", v["own_vs_other"], "content", v["match"]["value"], "len",
                  v["len_ratio_median"]["value"], "empty", v["empty"], "$", v["cost_usd"], flush=True)
        R["models"]["own_past_comment"] = tc.summarize(T.score_reference(rows, "own_past_comment"), n_boot=1000)
        for name in variants:
            if name != "base":
                R["paired"][f"{name}-minus-base"] = tc.paired_diff(scored[name], scored["base"], "own_vs_other", n_boot=1000)
                print(split, "PAIRED", name, R["paired"][f"{name}-minus-base"], flush=True)
        res["splits"][split] = R
        json.dump(res, open(f"{a.out}/context_ablation.json", "w"), indent=1)


if __name__ == "__main__":
    main()
