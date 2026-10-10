"""Gemini predictions for the HUMAINE benchmark, one 'arm' per information condition.

Arms (context given to the model; never any HUMAINE rows):
  plain      product IDs and the segment only
  meta       + public product metadata from OpenRouter (description, release date, price) where an exact ID match exists
  arena      + public LMArena leaderboard ratings (overall, multi-turn, category ratings) for each product, where mapped
Calibration from other benchmarks is applied after prediction (see humaine_eval.py), not here.

Usage: python -m human_sim.humaine_predict ARM [p4|p3|both] [MAX_CELLS]
Writes results/humaine/preds_{arm}_{task}.jsonl (one JSON per cell; reruns skip cells already done)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim.humaine_bench import METRICS, OUT

MODEL = os.environ.get("HUMAINE_MODEL", "gemini-2.5-flash")
STUDY = ("In a 2025-2026 study, adults in the United Kingdom and the United States, recruited through an online research panel, "
         "each had a multi-turn conversation about a topic of their own choosing with two AI chat assistants shown side by side as "
         "'Assistant A' and 'Assistant B'. They were not told which products these were. Afterwards each person judged which assistant "
         "was better on five questions, answering A, B, or tie.")
DIM_TEXT = {"overall_winner": "Which assistant was better overall?",
            "core_task_performance_and_reasoning": "Which was better at the core task and reasoning?",
            "interaction_fluidity_and_adaptiveness": "Which interacted more fluidly and adapted better to the person?",
            "communication_style_and_presentation": "Which had the better communication style and presentation?",
            "trust_ethics_and_safety": "Which was more trustworthy, ethical and safe?"}

_client = None
_lock = threading.Lock()


def client():
    global _client
    with _lock:
        if _client is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import auth
            from google import genai
            p = auth._materialize_adc_from_env()
            if p:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p)
            _client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.environ.get("VERTEX_LOCATION", "us-central1"),
                                   credentials=auth.vertex_credentials())
    return _client


def ask(prompt, max_tokens=400, retries=6):
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=0, max_output_tokens=max_tokens, response_mime_type="application/json",
                                      thinking_config=types.ThinkingConfig(thinking_budget=0))
    for i in range(retries):
        try:
            r = client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
            u = r.usage_metadata
            return r.text, (u.prompt_token_count or 0), (u.candidates_token_count or 0)
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                return f"ERROR: {e}", 0, 0
            time.sleep(min(60, 2 ** i + np.random.rand()))


def norm3(v):
    a = np.clip(np.asarray(v, float), 0, None)
    return (a / a.sum()).tolist() if a.sum() > 0 else [1 / 3] * 3


def parse_p4(text):
    try:
        d = json.loads(text)
        out = {}
        for m in METRICS:
            x = d.get(m) or d.get(m.split("_")[0])
            if isinstance(x, dict):
                x = [x.get("A", 0), x.get("B", 0), x.get("tie", 0)]
            out[m] = norm3(x)
        return out, True
    except Exception:  # noqa: BLE001
        return {m: [1 / 3] * 3 for m in METRICS}, False


def parse_p3(text):
    try:
        d = json.loads(text)
        x = d.get("distribution") if isinstance(d, dict) else d
        if isinstance(x, dict):
            x = [x.get(str(k), 0) for k in range(1, 6)]
        a = np.clip(np.asarray(x, float), 0, None)
        return (a / a.sum()).tolist(), True
    except Exception:  # noqa: BLE001
        return [0.2] * 5, False


# ---------------------------------------------------------------- context builders (external data only)
def context_for(arm, products, task=None):
    if arm == "plain":
        return ""
    if arm == "meta":
        from human_sim.humaine_external import openrouter_card
        lines = [openrouter_card(p) for p in products]
        return "Public product information (from a model marketplace listing):\n" + "\n".join(lines) + "\n"
    if arm == "arena":
        from human_sim.humaine_external import arena_card
        lines = [arena_card(p, task) for p in products]
        return ("Public ratings from a separate, larger online arena where other people vote between anonymous AI assistants "
                "(Elo-style; higher is better; about 400 points apart means the higher one wins about 91% of the time):\n" + "\n".join(lines) + "\n")
    raise ValueError(arm)


def p4_prompt(row, arm):
    ctx = context_for(arm, [row["m1"], row["m2"]])
    dims = "\n".join(f'- "{m}": {DIM_TEXT[m]}' for m in METRICS)
    return (f"{STUDY}\n\nAssistant A is the product '{row['m1']}'. Assistant B is the product '{row['m2']}'.\n"
            f"The people: {row['seg_desc']}.\n\n{ctx}\n"
            f"For each question below, estimate the percentage of these people who answered A, B, and tie.\n{dims}\n\n"
            'Return only JSON mapping each key to [percent_A, percent_B, percent_tie], each list summing to 100.')


def p3_prompt(row, arm):
    ctx = context_for(arm, [row["model"]], task=row["task_type"])
    return (f"{STUDY}\n\nEach conversation was also scored for how well the person's goal was achieved, from 1 (not at all) to 5 (completely).\n"
            f"Product: '{row['model']}'. Conversations of type: {row['task_type'].replace('_', ' ')}.\n\n{ctx}\n"
            "Estimate the percentage of these conversations that received each score from 1 to 5.\n"
            'Return only JSON: {"distribution": [p1, p2, p3, p4, p5]} summing to 100.')


def run(arm, task, max_cells=None, workers=16):
    cells = pd.read_pickle(OUT / f"{task}_cells.pkl")
    if max_cells:
        cells = cells.sample(min(max_cells, len(cells)), random_state=0)
    path = OUT / f"preds_{arm}_{task}.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["cell"] for l in path.read_text().splitlines() if l.strip()}
    todo = [r for _, r in cells.iterrows() if r["cell"] not in done]
    print(f"{arm}/{task}: {len(cells)} cells, {len(done)} cached, {len(todo)} to run", flush=True)
    tok_in = tok_out = fails = 0
    t0 = time.time()

    def job(r):
        prompt = p4_prompt(r, arm) if task == "p4" else p3_prompt(r, arm)
        text, ti, to = ask(prompt)
        pred, ok = parse_p4(text) if task == "p4" else parse_p3(text)
        return {"cell": r["cell"], "pred": pred, "ok": ok, "raw": text[:600], "tin": ti, "tout": to}

    with open(path, "a") as fh, ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(job, r) for r in todo]
        for i, fu in enumerate(as_completed(futs)):
            rec = fu.result()
            fh.write(json.dumps(rec) + "\n")
            tok_in += rec["tin"]; tok_out += rec["tout"]; fails += (not rec["ok"])
            if (i + 1) % 250 == 0:
                fh.flush()
                print(f"  {i + 1}/{len(todo)}  {time.time() - t0:.0f}s  parse failures {fails}  tokens in/out {tok_in}/{tok_out}", flush=True)
    print(f"done {arm}/{task}: parse failures {fails}, tokens in {tok_in}, out {tok_out}, {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    arm = sys.argv[1]
    which = sys.argv[2] if len(sys.argv) > 2 else "both"
    mx = int(sys.argv[3]) if len(sys.argv) > 3 else None
    for t in (["p4", "p3"] if which == "both" else [which]):
        run(arm, t, mx)
