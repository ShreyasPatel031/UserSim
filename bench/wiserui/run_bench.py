#!/usr/bin/env python3
"""WiserUI-Bench Task 1 (which A/B variant won?) through UserSim's shared pairwise judge.

Thin loader: each pair becomes two ``mvp.pairwise.PairEvidence`` (win / lose screenshots), fed to
``mvp.pairwise.compare_pair`` with the flags of one ablation arm. All prompts and aggregation live in product code.

Side A is the winner for half the pairs (fixed by a hash of the index), so nothing in the call order encodes
the answer. compare_pair judges both presentation orders; each order is written as a row in the old
judgments.jsonl format (order wl = winner shown first as Version X), so score.py still works, and the full
compare_pair output goes to pairs.jsonl for ablate.py.

Every model call is cached in $OUT/calls.jsonl keyed by (index, call key), so runs resume and cost is metered from
Vertex usage metadata. The dataset's ``rationale`` / ``ui_change`` are never shown to the model.

Personas: ``--personas-from results/full/calls.jsonl`` reuses the six visitors the old UserSim arm (A0) planned
for each page (same planner prompt, now mvp.fast_plan._AB_PERSONAS), so arms differ only in the judge; otherwise
compare_pair plans them with mvp.fast_plan.ab_personas.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from mvp.fast_plan import ab_personas  # noqa: E402
from mvp.pairwise import PAIRWISE_MODEL, PairEvidence, PairFlags, compare_pair, parse_json  # noqa: E402

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
DATA = BENCH / "repo" / "WiserUI_Bench.json"
IMAGES = BENCH / "images_clean"
# Vertex list price (USD / 1M tokens): input, output.
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-pro": (1.25, 10.0)}
STREAMS = {
    "s1": PairFlags(both_orders=True, goal_diffs=False, debias=False),
    "s2": PairFlags(both_orders=True, goal_diffs=True, debias=False),
    "s3": PairFlags(both_orders=True, goal_diffs=True, debias=True),
}


def source_of(item: dict) -> str:
    s = item["source"]
    return "goodui" if "goodui" in s else "vwo" if "vwo" in s else "abtest"


def ctx_of(item: dict) -> dict:
    return {"company": item["company"], "page_type": item["page_type"], "industry": item["industry_domain"],
            "platform": "mobile app or mobile site" if item["web_mobile"] == "mobile" else "website"}


def a_is_win(idx: int) -> bool:
    return int(hashlib.sha256(f"wiserui|{idx}".encode()).hexdigest(), 16) % 2 == 0


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.cache: dict[str, dict] = {}
        if path.exists():
            for line in path.open():
                try:
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec
                except Exception:  # noqa: BLE001
                    pass
        self.cost = sum(r.get("cost_usd", 0.0) for r in self.cache.values())
        self.new_cost = 0.0

    def put(self, rec: dict) -> None:
        self.cache[rec["key"]] = rec
        self.cost += rec.get("cost_usd", 0.0)
        self.new_cost += rec.get("cost_usd", 0.0)
        with self.path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def make_call(ledger: Ledger, sem: asyncio.Semaphore, prefix: str):
    from mvp.pairwise import default_call

    async def call(key: str, contents: list, *, temperature: float, max_tokens: int, media_resolution=None):
        k = f"{prefix}|{key}"
        hit = ledger.cache.get(k)
        if hit and not hit.get("error"):
            return hit["text"], hit["tokens_in"], hit["tokens_out"]
        async with sem:
            t0 = time.time()
            try:
                text, tin, tout = await default_call(key, contents, temperature=temperature, max_tokens=max_tokens,
                                                     media_resolution=media_resolution)
                err = None
            except Exception as exc:  # noqa: BLE001
                text, tin, tout, err = "", 0, 0, repr(exc)[:300]
        pin, pout = PRICE.get(PAIRWISE_MODEL, (0.30, 2.50))
        ledger.put({"key": k, "model": PAIRWISE_MODEL, "text": text, "tokens_in": tin, "tokens_out": tout,
                    "cost_usd": tin / 1e6 * pin + tout / 1e6 * pout, "secs": round(time.time() - t0, 2),
                    "error": err, "ts": time.time()})
        return text, tin, tout

    return call


def load_a0_personas(path: Path) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for line in path.open():
        rec = json.loads(line)
        parts = rec["key"].split("|")
        if len(parts) >= 4 and parts[0] == "usersim" and parts[3] == "planner" and not rec.get("error"):
            out[int(parts[1])] = parse_json(rec["text"]) or {}
    return out


def evidence(idx: int, label: str) -> PairEvidence:
    return PairEvidence(label=label, screenshots=[(IMAGES / str(idx) / f"{label}.png").read_bytes()])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="", help="comma list or @file")
    ap.add_argument("--stream", default="s1", choices=sorted(STREAMS), help="ablation arm (flags)")
    ap.add_argument("--personas-from", default=str(BENCH / "results" / "full" / "calls.jsonl"))
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-cost", type=float, default=15.0, help="stop scheduling new pairs above this spend")
    ap.add_argument("--aa", action="store_true", help="A/A check: the winner screenshot as both versions")
    args = ap.parse_args()

    flags = STREAMS[args.stream]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {x["index"]: x for x in json.load(open(DATA))}
    raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
    idxs = [int(i) for i in raw.replace("\n", ",").split(",") if i.strip()]
    idxs = [i for i in idxs if (IMAGES / str(i) / "win.png").exists() and (IMAGES / str(i) / "lose.png").exists()]
    a0 = load_a0_personas(Path(args.personas_from)) if args.personas_from and Path(args.personas_from).exists() else {}
    ledger = Ledger(out / "calls.jsonl")
    sem = asyncio.Semaphore(args.concurrency)
    cond = f"pw_{args.stream}" + ("_aa" if args.aa else "")
    print(f"[wiserui] {len(idxs)} pairs stream={args.stream} flags={flags} model={PAIRWISE_MODEL} "
          f"a0_personas={len(a0)} prior_spend=${ledger.cost:.3f}", flush=True)
    (out / "config.json").write_text(json.dumps({"stream": args.stream, "flags": flags.__dict__, "model": PAIRWISE_MODEL,
                                                 "personas_from": args.personas_from, "aa": args.aa, "n": len(idxs)}, indent=1))

    results: dict[int, dict] = {}
    done = 0

    async def pair(i: int) -> None:
        nonlocal done
        if ledger.cost > args.max_cost:
            return
        item = data[i]
        ctx = ctx_of(item)
        call = make_call(ledger, sem, f"{i}")
        personas = ab_personas(a0[i], ctx) if i in a0 else None
        aw = a_is_win(i)
        if args.aa:
            ev_a, ev_b = evidence(i, "win"), evidence(i, "win")
            ev_b.label = "win_copy"
        else:
            ev_a, ev_b = (evidence(i, "win"), evidence(i, "lose")) if aw else (evidence(i, "lose"), evidence(i, "win"))
        try:
            res = await compare_pair(ev_a, ev_b, personas, ctx, flags, call=call)
        except Exception as exc:  # noqa: BLE001
            print(f"[wiserui] pair {i} failed: {exc!r}"[:300], flush=True)
            return
        res.update({"index": i, "a_is_win": aw, "source": source_of(item), "web_mobile": item["web_mobile"],
                    "personas_used": personas or []})
        results[i] = res
        done += 1
        if done % 10 == 0 or done == len(idxs):
            print(f"[wiserui] {done}/{len(idxs)} pairs  spend=${ledger.cost:.3f} (this run ${ledger.new_cost:.3f})", flush=True)

    psem = asyncio.Semaphore(max(2, args.concurrency))

    async def guarded(i: int) -> None:
        async with psem:
            await pair(i)

    await asyncio.gather(*(guarded(i) for i in idxs))

    rows = []
    with (out / "pairs.jsonl").open("w") as f:
        for i in sorted(results):
            res = results[i]
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            win_side = "A" if res["a_is_win"] else "B"
            for o, ov in res["orders"].items():
                # order ab shows A as Version X (first). wl = winner shown first.
                winner_first = (o == "ab") == (win_side == "A")
                pick = {"X": "First", "Y": "Second"}.get(ov["pick"], "tie")
                votes = [{"choice": "First" if (j["rating_x"] > j["rating_y"]) else "Second" if j["rating_x"] < j["rating_y"] else None,
                          "persona": j["persona"], "rating_x": j["rating_x"], "rating_y": j["rating_y"]}
                         for j in res["judgments"] if j["order"] == o and j["ok"]]
                rows.append({"condition": cond, "index": i, "order": "wl" if winner_first else "lw", "pick": pick,
                             "votes": votes, "tie_vote": ov["pick"] == "tie", "x_minus_y": ov["x_minus_y"],
                             "source": res["source"], "web_mobile": res["web_mobile"]})
    with (out / "judgments.jsonl").open("w") as f:
        for r in sorted(rows, key=lambda r: (r["index"], r["order"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    errs = sum(1 for r in ledger.cache.values() if r.get("error"))
    print(f"[wiserui] wrote {len(results)} pairs; total spend ${ledger.cost:.3f}; call errors={errs}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
