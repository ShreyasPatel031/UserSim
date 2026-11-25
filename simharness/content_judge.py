"""Task C content measure: does a candidate comment make the SAME POINT as the person's real comment?

A frozen judge prompt labels (real, candidate) pairs in batches: same_point 0/1 and the shared point in a few words.
Three runs, each with its own batch composition and order (seeded); the label is the majority of the three.
Judge: Claude Opus 5.5 on Vertex AI (rawPredict, adaptive thinking at low effort). Inputs must already have @handles
removed; the prompt carries launch name + tagline and the two comment texts only.

    from simharness.content_judge import ContentJudge
    labels = ContentJudge(project).label(pairs_df)   # columns: pair_id, launch, real, cand

FROZEN_PROMPT is versioned (PROMPT_VERSION); change the version when the wording changes.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import threading
import time

import numpy as np
import pandas as pd

PROMPT_VERSION = "same-point-v1"
FROZEN_PROMPT = """You compare pairs of short comments about Product Hunt launches.
In each pair, A is a real comment a person wrote about the launch and B is a candidate comment about the same launch.
Decide whether B makes the SAME SPECIFIC POINT as A: the same praise of the same aspect, the same concern or criticism,
the same question, the same feature request, or the same comparison. Mentioning the same product or topic is not enough,
and generic enthusiasm ("great launch", "congrats", "looks useful") only counts when A is itself only generic enthusiasm.
If A makes several points, B needs to make at least one of them.

Return JSON only: {{"labels": [{{"id": <pair id>, "same_point": 0 or 1, "point": "<the shared point in at most 10 words, or empty>"}}, ...]}}
with one entry per pair, in any order.

Pairs:
{pairs}"""

PRICE_IN, PRICE_OUT = 4.00, 20.00   # USD per 1M tokens (Claude Opus 5.5 list price)


class ContentJudge:
    def __init__(self, project: str, model: str = "claude-opus-5-5", region: str = "global", batch: int = 12,
                 runs: int = 3, workers: int = 6, cap_usd: float = 3.5, effort: str = "low"):
        self.project, self.model, self.region, self.batch = project, model, region, batch
        self.runs, self.workers, self.cap, self.effort = runs, workers, cap_usd, effort
        self.tok_in = self.tok_out = 0
        self._lk = threading.Lock()

    @property
    def usd(self) -> float:
        return self.tok_in * PRICE_IN / 1e6 + self.tok_out * PRICE_OUT / 1e6

    def _call(self, prompt: str) -> str:
        from simharness.models.llm import _host, _post
        if self.usd > self.cap:
            raise RuntimeError(f"content judge budget cap ${self.cap} reached")
        url = (f"https://{_host(self.region)}/v1/projects/{self.project}/locations/{self.region}"
               f"/publishers/anthropic/models/{self.model}:rawPredict")
        d = _post(url, {"anthropic_version": "vertex-2023-10-16", "max_tokens": 6000,
                        "output_config": {"effort": self.effort},
                        "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        u = d.get("usage", {})
        with self._lk:
            self.tok_in += u.get("input_tokens", 0)
            self.tok_out += u.get("output_tokens", 0)
        return "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")

    @staticmethod
    def render(rows: pd.DataFrame) -> str:
        out = []
        for r in rows.itertuples():
            out.append(f"Pair {r.pair_id}\nLaunch: {r.launch}\nA (real): {r.real}\nB (candidate): {r.cand}")
        return FROZEN_PROMPT.format(pairs="\n\n".join(out))

    def _batch(self, rows: pd.DataFrame) -> dict:
        for attempt in range(3):
            try:
                txt = self._call(self.render(rows))
                m = re.search(r"\{.*\}", txt, re.S)
                labs = json.loads(m.group(0)).get("labels", []) if m else []
                got = {int(x["id"]): (int(x.get("same_point", 0)), str(x.get("point", ""))) for x in labs if "id" in x}
                if set(got) >= set(rows["pair_id"]):
                    return got
            except RuntimeError:
                raise
            except Exception:  # noqa: BLE001
                time.sleep(2 * (attempt + 1))
        return {}

    def label(self, pairs: pd.DataFrame, cache: dict | None = None) -> pd.DataFrame:
        """One row per (pair_id, run) with same_point and point; `cache` maps (run, batch key) -> result."""
        cache = cache if cache is not None else {}
        jobs = []
        for run in range(self.runs):
            order = np.random.default_rng(1000 + run).permutation(len(pairs))
            for k in range(0, len(order), self.batch):
                jobs.append((run, pairs.iloc[order[k:k + self.batch]]))

        def go(job):
            run, rows = job
            key = (run, tuple(sorted(rows["pair_id"].tolist())))
            if key not in cache:
                cache[key] = self._batch(rows)
            return run, cache[key]

        with cf.ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(go, jobs))
        out = [{"pair_id": pid, "run": run, "same_point": sp, "point": pt}
               for run, got in res for pid, (sp, pt) in got.items()]
        return pd.DataFrame(out)


def majority(labels: pd.DataFrame) -> pd.DataFrame:
    g = labels.groupby("pair_id")
    out = g["same_point"].agg(["mean", "size"]).reset_index()
    out["same_point"] = (out["mean"] > 0.5).astype(int)
    out["unanimous"] = out["mean"].isin([0.0, 1.0])
    return out.rename(columns={"mean": "share_of_runs", "size": "runs"})
