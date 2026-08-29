"""Minimal Vertex Gemini runner for SimBench (verbalized distributions).

Uses UserSim auth (ADC / Vertex), not google.generativeai API keys.

Smoke:
  PYTHONPATH=src python -m human_sim.simbench_run --split Pop --limit 3

Full (expensive-ish; see simbench_cost):
  PYTHONPATH=src python -m human_sim.simbench_run --split both --model gemini-2.5-flash-lite
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, RESULTS_DIR, ROOT
from human_sim.simbench_cost import PRICES, _generate_prompt

DATA = ROOT / "data" / "simbench"


def _client(model: str) -> genai.Client:
    # Flash-Lite / Flash on us-central1; keep same as config unless overridden
    return genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
    )


def _parse_dist(raw: str, keys: list[str]) -> dict[str, float] | None:
    try:
        m = re.search(r"\{[\s\S]*?\}", raw)
        if not m:
            return None
        data = json.loads(m.group(0))
        vals = {k: float(data[k]) for k in keys}
        s = sum(vals.values())
        if s <= 0:
            return None
        return {k: v / s for k, v in vals.items()}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def run_split(
    split: str,
    model: str,
    limit: int | None,
    temperature: float = 0.0,
) -> dict:
    path = DATA / f"SimBench{split}.pkl"
    with path.open("rb") as f:
        df = pickle.load(f)
    if limit is not None:
        df = df.iloc[:limit].copy()

    client = _client(model)
    rows_out = []
    prompt_tok = output_tok = 0
    ok = fail = 0
    t0 = time.time()

    for i, (_, row) in enumerate(df.iterrows()):
        system, user = _generate_prompt(row)
        keys = list(row["human_answer"].keys())
        try:
            resp = client.models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    max_output_tokens=250,
                    response_mime_type="application/json",
                ),
            )
            raw = (resp.text or "").strip()
            usage = getattr(resp, "usage_metadata", None)
            pt = int(getattr(usage, "prompt_token_count", 0) or 0)
            ot = int(getattr(usage, "candidates_token_count", 0) or 0)
            prompt_tok += pt
            output_tok += ot
            dist = _parse_dist(raw, keys)
            if dist is None:
                fail += 1
                rows_out.append({"i": i, "error": "parse", "raw": raw[:300], "pt": pt, "ot": ot})
            else:
                ok += 1
                rows_out.append(
                    {
                        "i": i,
                        "dataset_name": row.get("dataset_name"),
                        "llm_answer": dist,
                        "human_answer": dict(row["human_answer"]),
                        "pt": pt,
                        "ot": ot,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            fail += 1
            rows_out.append({"i": i, "error": str(exc)[:300]})

        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{split}] {i+1}/{len(df)} ok={ok} fail={fail}")

    price = PRICES.get(model, PRICES["gemini-2.5-flash"])
    cost = prompt_tok / 1e6 * price["in"] + output_tok / 1e6 * price["out"]
    summary = {
        "split": split,
        "model": model,
        "n": len(df),
        "ok": ok,
        "fail": fail,
        "prompt_tokens": prompt_tok,
        "output_tokens": output_tok,
        "estimated_cost_usd": round(cost, 4),
        "elapsed_s": round(time.time() - t0, 1),
        "rows": rows_out,
    }
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=["Pop", "Grouped", "both"], default="Pop")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", type=str, default=None)
    args = p.parse_args()

    splits = ["Pop", "Grouped"] if args.split == "both" else [args.split]
    out_dir = Path(args.out) if args.out else RESULTS_DIR / "simbench"
    out_dir.mkdir(parents=True, exist_ok=True)

    for split in splits:
        print(f"Running SimBench{split} model={args.model} limit={args.limit}")
        summary = run_split(split, args.model, args.limit)
        out_path = out_dir / f"SimBench{split}_{args.model.replace('/', '_')}_n{summary['n']}.json"
        # keep full rows for smoke; for huge runs still fine (~MBs)
        out_path.write_text(json.dumps(summary, indent=2))
        print(
            f"Done {split}: ok={summary['ok']} fail={summary['fail']} "
            f"tok in={summary['prompt_tokens']} out={summary['output_tokens']} "
            f"~${summary['estimated_cost_usd']} -> {out_path}"
        )


if __name__ == "__main__":
    main()
