"""Planner-only probe: run the compare plan the way POST /api/studies does, no browsers.

Runs the full plan (plan_from_url) and the early-start starter call concurrently,
splices them like mvp/server.py, counts Gemini calls, and writes one JSON per run.

  MVP_STUDY_MODE=compare python scripts/plan_probe.py https://www.zo.computer/ --label base --out /tmp/x
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path


async def probe(url: str) -> dict:
    import capability.gemini_config as gc

    calls: list[dict] = []
    real = gc.gemini_chat

    async def counted(messages, **kw):
        t0 = time.monotonic()
        raw = ""
        try:
            raw = await real(messages, **kw)
            return raw
        finally:
            calls.append({"s": round(time.monotonic() - t0, 2), "prompt_head": str(messages[-1].get("content", ""))[:70],
                          "reply": str(raw)[:4000]})

    gc.gemini_chat = counted
    from mvp import early_start
    from mvp.fast_plan import plan_from_url

    t0 = time.monotonic()
    plan_task = asyncio.create_task(plan_from_url(url))
    starter = await early_start.starter_plan(url) if early_start.enabled() else None
    starter_s = round(time.monotonic() - t0, 2)
    plan = await plan_task
    plan_s = round(time.monotonic() - t0, 2)
    spliced = early_start.splice_plan(plan, starter) if plan and starter and plan.get("mode") == "compare" else plan
    gc.gemini_chat = real
    out = {
        "url": url,
        "framing_mode": os.environ.get("MVP_PLAN_FRAMING", "(default)"),
        "starter_wall_s": starter_s,
        "plan_wall_s": plan_s,
        "gemini_calls": len(calls),
        "gemini_call_detail": calls,
        "starter": starter,
        "plan_raw": plan,
        "final": None,
    }
    if spliced:
        out["final"] = {
            "product": spliced.get("product"),
            "segment": spliced.get("segment"),
            "positioning": spliced.get("positioning"),
            "verified": spliced.get("verified"),
            "competitors": spliced.get("competitors"),
            "competitor_names": spliced.get("competitor_names"),
            "persona_names": [p.get("name") for p in spliced.get("personas") or []],
            "personas": [f"{p.get('name')} | {p.get('role')} | favors {p.get('favors')}" for p in spliced.get("personas") or []],
            "tasks": list(spliced.get("tasks") or []),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", default="/workspace/planner-framing-results")
    a = ap.parse_args()
    res = asyncio.run(probe(a.url))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    host = a.url.split("//")[-1].strip("/").removeprefix("www.")
    path = Path(a.out) / f"{a.label}__{host}__{time.strftime('%H%M%S')}.json"
    path.write_text(json.dumps(res, indent=1))
    f = res.get("final") or {}
    print(json.dumps({"file": str(path), "plan_wall_s": res["plan_wall_s"], "starter_wall_s": res["starter_wall_s"],
                      "gemini_calls": res["gemini_calls"], **{k: f.get(k) for k in ("segment", "positioning", "verified", "competitors", "persona_names", "tasks")}}, indent=1))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
