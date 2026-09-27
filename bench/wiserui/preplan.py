#!/usr/bin/env python3
"""Plan personas once for pairs without cached A0 personas, and write the same planner call into several run
ledgers, so parallel arms (e.g. S2 and S2-strict) judge with identical personas.

usage: preplan.py --indices @file OUT_DIR [OUT_DIR ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_bench as rb  # noqa: E402
from mvp.fast_plan import ab_personas_prompt  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outs", nargs="+")
    ap.add_argument("--indices", required=True)
    args = ap.parse_args()
    raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
    idxs = [int(i) for i in raw.replace("\n", ",").split(",") if i.strip()]
    a0 = rb.load_a0_personas(rb.BENCH / "results" / "full" / "calls.jsonl")
    data = {x["index"]: x for x in json.load(open(rb.DATA))}
    need = [i for i in idxs if i not in a0]
    ledgers = [rb.Ledger(Path(o) / "calls.jsonl") for o in args.outs]
    sem = asyncio.Semaphore(32)

    async def one(i: int) -> None:
        k = f"{i}|planner"
        have = next((lg.cache[k] for lg in ledgers if k in lg.cache and not lg.cache[k].get("error")), None)
        if have is None:
            call = rb.make_call(ledgers[0], sem, f"{i}")
            await call("planner", [ab_personas_prompt(rb.ctx_of(data[i]))], temperature=0.3, max_tokens=2048)
            have = ledgers[0].cache[k]
        for lg in ledgers:
            if k not in lg.cache or lg.cache[k].get("error"):
                lg.put(dict(have, cost_usd=0.0) if lg is not ledgers[0] else have)

    await asyncio.gather(*(one(i) for i in need))
    print(f"[preplan] {len(need)} pairs without A0 personas planned into {len(ledgers)} ledgers", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
