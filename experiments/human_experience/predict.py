"""Final forecaster for phase B: one fixed model, prompt and schema in every cell.

The prompt carries only permitted packets (and, in B2-B5, the observations
derived from that case's actual execution trace). It never names the
condition. Writes results/predictions.jsonl (appending only missing keys) and
the exact serialized prompt for each record under results/prompts/.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import llm

HERE = Path(__file__).resolve().parent
PACKETS = HERE / "packets"
RESULTS = HERE / "results"
EXEC = HERE / "results" / "execution"

CELLS = {
    "B0": {"packs": ["M", "D", "P", "Q"], "engine": None},
    "B1": {"packs": ["M", "D", "P", "Q", "O", "C", "T"], "engine": None},
    "B2": {"packs": ["M", "D", "P", "Q"], "engine": "generic"},
    "B3": {"packs": ["M", "D", "P", "Q", "O", "C", "T"], "engine": "generic"},
    "B4": {"packs": ["M", "D", "P", "Q"], "engine": "usersim"},
    "B5": {"packs": ["M", "D", "P", "Q", "O", "C", "T"], "engine": "usersim"},
}
CONTEXT = {"B0": "base", "B1": "full", "B2": "base", "B3": "full", "B4": "base", "B5": "full"}

HEADINGS = {
    "M": "Product",
    "D": "Public product pages (current versions; testimonials and ratings removed)",
    "P": "Recorded reviewer context (from the review form; not a verified identity)",
    "Q": "Neutral task used for this forecast",
    "O": "O*NET occupation task statements for plausible occupations of this role",
    "C": "Evidence reviews of the two competing products (other reviewers)",
    "T": "Evidence reviews of the target product (other reviewers)",
}

SYSTEM = """You forecast how one specific software reviewer rated a product on Capterra.
Ratings are 1-5 stars. Give a probability for each star value, ordered 1 to 5, summing to 1.
Base the forecast only on the material supplied. Evidence reviews come from OTHER people, not
this reviewer. The reviewer context fields are recorded facts; do not infer income, personality
or technical skill from them. If an execution observation section is present, it describes a
short fresh-account test run of the task in today's product, not the reviewer's own experience.
Predict up to three specific benefits and up to three specific frictions this reviewer is likely
to report. Be concrete (name the feature, object or situation), not generic. Cite basis_ids
(evidence ids like Capterra___123, or "D", "Q", "P", "O", "EXEC") for each claim.
Reply with JSON only."""

SCHEMA = """JSON shape:
{"ease_of_use_rating": [p1,p2,p3,p4,p5],
 "functionality_rating": [p1,p2,p3,p4,p5],
 "overall_rating": [p1,p2,p3,p4,p5],
 "value_for_money_rating": [p1,p2,p3,p4,p5],
 "benefits": [{"aspect": "..", "claim": "..", "basis_ids": [".."]}],
 "frictions": [{"aspect": "..", "claim": "..", "basis_ids": [".."]}],
 "unknowns": [".."]}"""


def exec_record(case_id: str, context: str, engine: str) -> dict | None:
    path = EXEC / f"{case_id}__{context}__{engine}.json"
    return json.loads(path.read_text()) if path.exists() else None


def exec_text(rec: dict) -> str:
    """Trace-supported observations only. A blocked run says so and carries no product observations."""
    lines = [
        f"Status: {rec['status']}",
        f"Product capture date: {rec['product_version_or_capture_date']}; plan: {rec['plan']}",
        f"Actions taken: {rec['actions']}; elapsed seconds: {rec['elapsed_seconds']}",
    ]
    for c in rec.get("success_criteria_results") or []:
        lines.append(f"Success check '{c['criterion']}': {c['result']}")
    for o in rec.get("observations") or []:
        lines.append(f"Observed (step {o.get('step')}): {o['text']}")
    for e in rec.get("errors") or []:
        lines.append(f"Error ({e.get('kind')}): {e.get('text')}")
    for m in rec.get("environment_mismatches") or []:
        lines.append(f"Environment note: {m}")
    return "\n".join(lines)


def build_prompt(packets: dict, cell: str, case_id: str) -> tuple[str, dict | None]:
    spec = CELLS[cell]
    parts = [f"### {HEADINGS[k]}\n{packets[k]['text']}" for k in spec["packs"]]
    rec = None
    if spec["engine"]:
        rec = exec_record(case_id, CONTEXT[cell], spec["engine"])
        if rec is None:
            raise FileNotFoundError(f"no execution record for {case_id} {cell}")
        parts.append("### Execution observations from a test run of the task\n" + exec_text(rec))
    return "\n\n".join(parts) + "\n\n" + SCHEMA, rec


def vector(v) -> dict | None:
    if not isinstance(v, list) or len(v) != 5:
        return None
    try:
        ps = [max(0.0, float(x)) for x in v]
    except (TypeError, ValueError):
        return None
    s = sum(ps)
    if s <= 0:
        return None
    ps = [round(x / s, 6) for x in ps]
    ps[4] = round(1.0 - sum(ps[:4]), 6)
    if ps[4] < 0:  # rounding pushed the tail negative
        ps[4] = 0.0
        ps[3] = round(1.0 - sum(ps[:3]), 6)
    return {"probabilities": ps}


def claims(v) -> list[dict]:
    out = []
    for c in (v or [])[:3]:
        if isinstance(c, dict) and c.get("claim"):
            out.append({"aspect": str(c.get("aspect") or ""), "claim": str(c["claim"]),
                        "basis_ids": [str(b) for b in (c.get("basis_ids") or [])]})
    return out


async def forecast(case_id: str, cell: str, sem: asyncio.Semaphore) -> dict:
    packets = json.loads((PACKETS / f"{case_id}.json").read_text())
    prompt, rec = build_prompt(packets, cell, case_id)
    phash = hashlib.sha256((SYSTEM + "\n" + prompt).encode()).hexdigest()
    (RESULTS / "prompts").mkdir(parents=True, exist_ok=True)
    (RESULTS / "prompts" / f"{case_id}__{cell}.txt").write_text(SYSTEM + "\n\n" + prompt)
    async with sem:
        res = await llm.call(prompt, system=SYSTEM)
    j = res["json"] or {}
    return {
        "case_id": case_id,
        "condition": cell,
        "replicate": 1,
        "ratings": {k: vector(j.get(k)) for k in
                    ["ease_of_use_rating", "functionality_rating", "overall_rating", "value_for_money_rating"]},
        "benefits": claims(j.get("benefits")),
        "frictions": claims(j.get("frictions")),
        "task_hypotheses": [],
        "unknowns": [str(u) for u in (j.get("unknowns") or [])][:5],
        "execution": None if rec is None else {k: rec[k] for k in
                                               ["run_id", "engine", "status", "trace_path", "actions", "elapsed_seconds"]},
        "usage": res["usage"],
        "model": f"{res['model']} ({res['model_version']}), temperature {llm.FORECAST_TEMPERATURE}, thinking off",
        "packet_sha256": phash,
        "packets": {k: packets[k]["sha256"] for k in CELLS[cell]["packs"]},
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="B0,B1")
    ap.add_argument("--cases", default="core", help="core | all")
    a = ap.parse_args()
    manifest = json.loads((PACKETS / "manifest.json").read_text())
    case_ids = [c for c, v in manifest["cases"].items() if a.cases == "all" or v["core"]]
    out = RESULTS / "predictions.jsonl"
    RESULTS.mkdir(exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["case_id"], r["condition"]) for r in map(json.loads, out.read_text().splitlines()) if r}
    todo = [(c, cell) for cell in a.cells.split(",") for c in case_ids if (c, cell) not in done]
    sem = asyncio.Semaphore(4)
    rows = await asyncio.gather(*(forecast(c, cell, sem) for c, cell in todo))
    with out.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cost = sum(r["usage"]["cost_usd"] for r in rows)
    print(json.dumps({"written": len(rows), "skipped_existing": len(done), "cost_usd": round(cost, 4)}))


if __name__ == "__main__":
    asyncio.run(main())
