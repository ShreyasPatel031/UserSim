"""Exit interview: after a run, the simulated user rates its own experience.

The run's prediction is the runner's own first-person rating of what it went through, not a forecaster
converting pass/fail into stars. Input: the same permitted packet the runner had (profile for UserSim,
plus O/C/T in full context), its step-by-step thoughts and the page responses from the trace, and the
final screenshot when it still exists. Never shown: success checks, step-limit notes, the judge, hidden
ratings. UserSim cells answer in persona; generic cells answer as a neutral evaluator. Same model and
settings as predict.py, so B0/B1 stay comparable.

  python exit_interview.py --runs results/execution --out results/predictions_exit.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import glob
import hashlib
import json
from pathlib import Path

import llm

HERE = Path(__file__).resolve().parent
PACKETS = HERE / "packets"
CELL = {("base", "generic"): "B2", ("full", "generic"): "B3", ("base", "usersim"): "B4", ("full", "usersim"): "B5"}

SCHEMA = """JSON shape:
{"ease_of_use_rating": [p1,p2,p3,p4,p5],
 "functionality_rating": [p1,p2,p3,p4,p5],
 "overall_rating": [p1,p2,p3,p4,p5],
 "value_for_money_rating": [p1,p2,p3,p4,p5],
 "benefits": [{"aspect": "..", "claim": "..", "basis_ids": [".."]}],
 "frictions": [{"aspect": "..", "claim": "..", "basis_ids": [".."]}],
 "unknowns": [".."]}"""

USERSIM = """You are the person described below. You just used {product} to do the task below; your own
step-by-step notes from that session follow. Rate {product} the way you would on Capterra, from what you
experienced: how easy it was to use, how well it did what you needed, and overall. Judge the product, not
your own mistakes or the time you had. Give a probability for each star value 1-5 (ordered 1 to 5, summing
to 1) for each rating, and up to three specific benefits and three frictions you would mention. Cite
basis_ids ("EXEC", "P", evidence ids). Reply with JSON only."""

GENERIC = """You are evaluating {product}. A test agent just did the task below; its step-by-step notes
follow. From what the session showed about the product, rate how easy {product} is to use, how well it does
what the task needed, and overall, on Capterra's 1-5 scale. Judge the product, not the agent's mistakes or the
time it had. Give a probability for each star value 1-5 (ordered 1 to 5, summing to 1) for each rating, and up
to three specific benefits and three frictions. Cite basis_ids ("EXEC", "P", evidence ids). Reply with JSON only."""


def session_notes(trace: list[dict]) -> str:
    lines = []
    for s in trace:
        if not s.get("step"):
            continue
        thought = " ".join(str(s.get("thought") or "").split())[:240]
        obs = " ".join(str(s.get("observation") or "").split())[:240]
        lines.append(f"{s['step']}. I tried: {thought} -> what happened: {obs}")
    return "\n".join(lines)


async def interview(rec: dict, sem: asyncio.Semaphore, use_shots: bool = True) -> dict:
    from predict import claims, vector

    cid, ctx, eng = rec["case_id"], rec["context"], rec["engine"]
    packets = json.loads((PACKETS / f"{cid}.json").read_text())
    product = packets["M"]["product"]
    trace = json.loads((HERE / rec["trace_path"]).read_text())
    blocks = [f"### Task\n{packets['Q']['text']}", f"### Who you are (recorded facts)\n{packets['P']['text']}"]
    if ctx == "full":
        blocks += [f"### O*NET tasks for this role\n{packets['O']['text']}",
                   f"### Other people's reviews of competing products\n{packets['C']['text']}",
                   f"### Other people's reviews of {product}\n{packets['T']['text']}"]
    blocks.append("### Your session notes\n" + session_notes(trace["trace"]))
    system = (USERSIM if eng == "usersim" else GENERIC).format(product=product)
    prompt = "\n\n".join(blocks) + "\n\n" + SCHEMA
    msg = {"role": "user", "content": prompt}
    shot = Path(trace.get("final_screenshot") or "")
    # The screenshot must come from this run: written during it, so before the trace file. Reruns reuse the
    # run folder, so a newer screenshot belongs to a later run.
    trace_mtime = Path(HERE / rec["trace_path"]).stat().st_mtime
    if use_shots and shot.is_file() and trace_mtime - 900 <= shot.stat().st_mtime <= trace_mtime:
        msg["image_b64"] = base64.b64encode(shot.read_bytes()).decode()
        msg["image_mime"] = "image/png"
    contents, sys_inst = llm._to_vertex([{"role": "system", "content": system}, msg])
    async with sem:
        res = await llm.call_contents(contents, sys_inst)
    j = res["json"] or {}
    return {
        "case_id": cid, "condition": CELL[(ctx, eng)], "replicate": 1, "method": "exit_interview",
        "ratings": {k: vector(j.get(k)) for k in
                    ["ease_of_use_rating", "functionality_rating", "overall_rating", "value_for_money_rating"]},
        "benefits": claims(j.get("benefits")), "frictions": claims(j.get("frictions")),
        "task_hypotheses": [], "unknowns": [str(u) for u in (j.get("unknowns") or [])][:5],
        "execution": {k: rec[k] for k in ["run_id", "engine", "status", "trace_path", "actions", "elapsed_seconds"]},
        "usage": res["usage"], "model": f"{res['model']} ({res['model_version']}), temperature {llm.FORECAST_TEMPERATURE}",
        "packet_sha256": hashlib.sha256((system + prompt).encode()).hexdigest(),
        "used_screenshot": "image_b64" in msg,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="results/execution")
    ap.add_argument("--out", default="results/predictions_exit.jsonl")
    ap.add_argument("--no-shots", action="store_true")
    a = ap.parse_args()
    recs = []
    for f in sorted(glob.glob(str(HERE / a.runs / "case_*.json"))):
        if f.endswith(".trace.json"):
            continue
        r = json.load(open(f))
        if r.get("trace_path") and r["status"] != "environment_failure":
            if not (HERE / r["trace_path"]).exists():  # archived run: trace sits next to it
                r["trace_path"] = str(Path(a.runs) / (Path(f).stem + ".trace.json"))
            recs.append(r)
    sem = asyncio.Semaphore(4)
    rows = await asyncio.gather(*(interview(r, sem, not a.no_shots) for r in recs))
    out = HERE / a.out
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(json.dumps({"interviews": len(rows), "cost_usd": round(sum(r["usage"]["cost_usd"] for r in rows), 4),
                      "with_screenshot": sum(r["used_screenshot"] for r in rows), "out": str(out)}))


if __name__ == "__main__":
    asyncio.run(main())
