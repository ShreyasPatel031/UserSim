#!/usr/bin/env python3
"""WiserUI-Bench Task 1 (which A/B variant won?) through UserSim's shared pairwise judge.

Thin loader: each pair becomes two ``mvp.pairwise.PairEvidence`` (win / lose screenshots), fed to
``mvp.pairwise.compare_pair`` with the flags of one ablation arm. All prompts and aggregation live in product code.

Side A is the winner for half the pairs (fixed by a hash of the index), so nothing in the call order encodes
the answer. compare_pair judges both presentation orders; each order is written as a row in the old
judgments.jsonl format (order wl = winner shown first as Version X), so score.py still works, and the full
compare_pair output goes to pairs.jsonl for ablate.py.

Every model call is cached in $OUT/calls.jsonl keyed by (index, call key), so runs resume and cost is metered from
Vertex usage metadata. ``--max-cost`` is a hard cap on the ledger total (cached spend included): every paid call first
reserves its worst-case cost (``worst_call_cost``) and is refused if the reservation would cross the cap; short-pick
pairs reserve all their uncached calls up front and wait for in-flight work to settle rather than start a pair that
might not finish, so pairs are done in index order and a capped run stops on a clean prefix. The dataset's ``rationale`` / ``ui_change`` are never shown to the model.

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
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from mvp.fast_plan import ab_personas  # noqa: E402
from mvp.e2e_ui_run import think_headroom  # noqa: E402
from mvp.pairwise import (GF_INPUTS, PAIRWISE_MODEL, SAMPLE_STAGES, FewShotExample, PairEvidence, PairFlags,  # noqa: E402
                          compare_pair, parse_json, short_call_tag)

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
DATA = BENCH / "repo" / "WiserUI_Bench.json"
IMAGES = BENCH / "images_clean"
# Composite pairs split into panels by composites.py (win/lose crops); preferred over IMAGES when present.
RECOVERED = BENCH / "images_recovered"
# Vertex list price (USD / 1M tokens): input, output.
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-3.1-pro-preview": (2.00, 12.00),
         "claude-sonnet-4-6": (3.00, 15.00), "claude-haiku-4-5@20251001": (1.00, 5.00),
         "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60), "gpt-5-mini": (0.25, 2.00),
         "gpt-6-sol": (2.00, 10.00), "gpt-6-luna": (0.10, 0.50), "gpt-6-astra": (10.00, 50.00),
         "gemini-3.8-flash": (0.75, 3.75), "claude-haiku-4-5": (1.00, 5.00), "claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5": (2.00, 10.00), "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-pro": (1.25, 10.0)}
STREAMS = {
    "s1": PairFlags(both_orders=True, goal_diffs=False, debias=False),
    "s2": PairFlags(both_orders=True, goal_diffs=True, debias=False),
    "s3": PairFlags(both_orders=True, goal_diffs=True, debias=True),
    # S2 with per-order goal/diffs only (no merge across orders): each order's pick is independent, as in the paper.
    "s2strict": PairFlags(both_orders=True, goal_diffs=True, debias=False, strict_orders=True),
    # Full G-FOCUS (arXiv 2505.05026v1 Appendix E prompts), strict per-order: goal, diffs, argue both sides, Evaluator.
    "gfocus": PairFlags(both_orders=True, goal_diffs=True, strict_orders=True, argue_both=True, v1_prompts=True,
                        use_personas=False),
    # The same, but each of the 6 personas (same as S2-strict) argues both sides and evaluates as that visitor.
    "gfocus_personas": PairFlags(both_orders=True, goal_diffs=True, strict_orders=True, argue_both=True,
                                 v1_prompts=True, use_personas=True),
    # One call per order: "Better version: First/Second" + 1-2 sentence reason, temperature 0, screenshots fit in
    # 768x768 (the SFT experiment's prompt; --model picks the base model or a tuned endpoint).
    "shortpick": PairFlags(both_orders=True, short_pick=True, temperature=0.0, max_tokens=200, image_max_px=768),
    # The WiserUI paper's vanilla zero-shot prompt, one call per order, any provider via --model; screenshots fit in
    # 1568x1568 (Claude's own limit) so every model gets the same bytes.
    "vanilla": PairFlags(both_orders=True, short_pick=True, vanilla=True, temperature=0.0, max_tokens=2048,
                         image_max_px=1568),
    # H1 (RESEARCH_HYPOTHESES.md): the vanilla prompt, but each call gives P(First more effective) 0-100 and the harness
    # averages both orders into one order-invariant answer. Same model settings as "vanilla" (paired with it).
    "h1": PairFlags(both_orders=True, short_pick=True, vanilla=True, graded=True, temperature=0.0, max_tokens=2048,
                    image_max_px=1568),
    # H1 + a short debiasing instruction (screenshot order is random; more content is not better; judge conversion).
    "h1_debias": PairFlags(both_orders=True, short_pick=True, vanilla=True, graded=True, debias=True, temperature=0.0,
                           max_tokens=2048, image_max_px=1568),
}


def source_of(item: dict) -> str:
    s = item["source"]
    return "goodui" if "goodui" in s else "vwo" if "vwo" in s else "abtest"


def ctx_of(item: dict) -> dict:
    return {"company": item["company"], "page_type": item["page_type"], "industry": item["industry_domain"],
            "platform": "mobile app or mobile site" if item["web_mobile"] == "mobile" else "website"}


def change_of(item: dict) -> str:
    """The dataset's ui_change ({element: [attributes]}) as text: what the test changed, never which side won."""
    return "; ".join(f"{el}: {', '.join(attrs)}" for el, attrs in (item.get("ui_change") or {}).items())


OCR = BENCH / "ocr"


def page_text(idx: int, label: str) -> str:
    """Tesseract OCR of the full-resolution screenshot (stand-in for the product's DOM/accessibility text), cached."""
    f = OCR / f"{idx}_{label}.txt"
    if not f.exists():
        import subprocess

        OCR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tesseract", str(image_dir(idx) / f"{label}.png"), str(f)[:-4], "--psm", "3"],
                       capture_output=True, check=False)
    return f.read_text(errors="ignore") if f.exists() else ""


def a_is_win(idx: int) -> bool:
    return int(hashlib.sha256(f"wiserui|{idx}".encode()).hexdigest(), 16) % 2 == 0


# Worst-case billed input per call: two screenshots fit into 1568 x 1568 (Claude/Gemini bill well under 3k tokens
# each) plus the prompt. Output: max_tokens plus the thinking headroom llm_generate adds for that model
# (mvp.e2e_ui_run.think_headroom, env-tunable); at least 8192 for unknown endpoints (tuned models etc.).
WORST_IN_TOKENS = 8000
THINK_HEADROOM = 8192


def worst_call_cost(model: str, max_tokens: int) -> float:
    pin, pout = price_of(model)
    known = model in PRICE or str(model).startswith(("gemini-", "claude-", "gpt-"))
    head = think_headroom(model) if known else THINK_HEADROOM
    return WORST_IN_TOKENS / 1e6 * pin + (max_tokens + head) / 1e6 * pout


class BudgetExhausted(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.reserved = 0.0  # worst-case cost of calls (or whole pairs) in flight
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


def price_of(model: str) -> tuple[float, float]:
    """List price per 1M tokens; a tuned endpoint of gemini-2.5-flash bills at the base model's price."""
    return PRICE.get(model, PRICE["gemini-2.5-flash"])


def make_call(ledger: Ledger, sem: asyncio.Semaphore, prefix: str, max_cost: float | None = None,
              covered: bool = False):
    """Cached, metered model call. With max_cost, an uncached call reserves worst_call_cost first and raises
    BudgetExhausted if ledger.cost + reservations would exceed it (covered=True: the pair already reserved it)."""
    from mvp.pairwise import default_call

    async def call(key: str, contents: list, *, temperature: float, max_tokens: int, media_resolution=None,
                   json_mode: bool = True, model: str | None = None):
        k = f"{prefix}|{key}"
        hit = ledger.cache.get(k)
        if hit and not hit.get("error"):
            return hit["text"], hit["tokens_in"], hit["tokens_out"]
        w = 0.0
        if max_cost is not None and not covered:
            w = worst_call_cost(model or PAIRWISE_MODEL, max_tokens)
            if ledger.cost + ledger.reserved + w > max_cost:
                raise BudgetExhausted(f"{k}: ${ledger.cost:.3f} spent + ${ledger.reserved:.3f} reserved + "
                                      f"${w:.3f} worst case > cap ${max_cost:.2f}")
            ledger.reserved += w
        try:
            async with sem:
                t0 = time.time()
                try:
                    text, tin, tout = await default_call(key, contents, temperature=temperature, max_tokens=max_tokens,
                                                         media_resolution=media_resolution, json_mode=json_mode,
                                                         model=model)
                    err = None
                except Exception as exc:  # noqa: BLE001
                    text, tin, tout, err = "", 0, 0, repr(exc)[:300]
        finally:
            ledger.reserved -= w
        pin, pout = price_of(model or PAIRWISE_MODEL)
        ledger.put({"key": k, "model": model or PAIRWISE_MODEL, "text": text, "tokens_in": tin, "tokens_out": tout,
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


def image_dir(idx: int) -> Path:
    rec = RECOVERED / str(idx)
    return rec if (rec / "win.png").exists() and (rec / "lose.png").exists() else IMAGES / str(idx)


def evidence(idx: int, label: str, text: bool = False) -> PairEvidence:
    return PairEvidence(label=label, screenshots=[(image_dir(idx) / f"{label}.png").read_bytes()],
                        summary=page_text(idx, label) if text else "")


async def main() -> None:
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(96))  # default pool (~12) caps concurrency
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="", help="comma list or @file")
    ap.add_argument("--stream", default="s1", choices=sorted(STREAMS), help="ablation arm (flags)")
    ap.add_argument("--personas-from", default=str(BENCH / "results" / "full" / "calls.jsonl"))
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-cost", type=float, default=15.0,
                    help="hard cap on this ledger's total spend (cached calls included): no call starts unless its "
                         "worst-case cost still fits")
    ap.add_argument("--aa", action="store_true", help="A/A check: the winner screenshot as both versions")
    ap.add_argument("--model", default="", help="model for the short-pick stream: base name or tuned endpoint resource")
    ap.add_argument("--argue-temperature", type=float, default=None, help="PairFlags.argue_temperature (G-FOCUS stages)")
    ap.add_argument("--samples-per-order", type=int, default=None, help="PairFlags.samples_per_order (majority vote)")
    ap.add_argument("--sample-stage", default=None, choices=SAMPLE_STAGES, help="PairFlags.sample_stage")
    ap.add_argument("--few-shot-k", type=int, default=0, help="PairFlags.few_shot_k: solved examples in the Evaluator")
    ap.add_argument("--few-shot-pool", default="", help="indices (comma list or @file) of the example pool; the pair "
                                                         "being judged is always left out")
    ap.add_argument("--seed-ledger", default="",
                    help="before a fresh run, copy this ledger's calls for the selected pairs in at $0 (e.g. an earlier "
                         "single-sample run whose calls are sample 0 of a vote run); new runs never share keys otherwise")
    ap.add_argument("--seed-match", default="", help="only seed calls whose key (after the pair index) matches this regex")
    ap.add_argument("--failure-modes", action="store_true", help="graded streams: PairFlags.failure_modes preamble")
    ap.add_argument("--graded-scale", type=int, default=None, choices=(100, 7), help="graded streams: answer scale")
    ap.add_argument("--graded-shots", type=int, default=0,
                    help="graded streams: solved examples per call from --few-shot-pool (use dev pairs only)")
    ap.add_argument("--inputs", default="", help=f"extra G-FOCUS inputs (PairFlags.gf_*), comma list of {','.join(GF_INPUTS)}")
    args = ap.parse_args()

    import dataclasses

    flags = STREAMS[args.stream]
    extra = [x.strip() for x in args.inputs.split(",") if x.strip()]
    bad = [x for x in extra if x not in GF_INPUTS]
    if bad:
        raise SystemExit(f"unknown --inputs {bad}; choose from {GF_INPUTS}")
    flags = dataclasses.replace(flags, **{f"gf_{x}": True for x in extra})
    if args.model:
        flags = dataclasses.replace(flags, model=args.model)
    if args.few_shot_k:
        flags = dataclasses.replace(flags, few_shot_k=args.few_shot_k)
    if args.failure_modes:
        flags = dataclasses.replace(flags, failure_modes=True)
    if args.graded_scale:
        flags = dataclasses.replace(flags, graded_scale=args.graded_scale)
    if args.graded_shots:
        flags = dataclasses.replace(flags, graded_shots=args.graded_shots)
    for opt in ("argue_temperature", "samples_per_order", "sample_stage"):
        if getattr(args, opt) is not None:
            flags = dataclasses.replace(flags, **{opt: getattr(args, opt)})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {x["index"]: x for x in json.load(open(DATA))}
    raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
    idxs = [int(i) for i in raw.replace("\n", ",").split(",") if i.strip()]
    idxs = [i for i in idxs if (image_dir(i) / "win.png").exists() and (image_dir(i) / "lose.png").exists()]
    a0 = load_a0_personas(Path(args.personas_from)) if args.personas_from and Path(args.personas_from).exists() else {}
    if args.seed_ledger and not (out / "calls.jsonl").exists():
        keep, n = {str(i) for i in idxs}, 0
        with (out / "calls.jsonl").open("w") as f:
            for line in Path(args.seed_ledger).open():
                rec = json.loads(line)
                idx, _, rest = rec["key"].partition("|")
                if idx in keep and not rec.get("error") and (not args.seed_match or re.match(args.seed_match, rest)):
                    f.write(json.dumps({**rec, "cost_usd": 0.0, "copied_from": args.seed_ledger}, ensure_ascii=False) + "\n")
                    n += 1
        print(f"[wiserui] seeded {n} calls from {args.seed_ledger} at $0", flush=True)
    ledger = Ledger(out / "calls.jsonl")
    pool = None
    if flags.few_shot_k or flags.graded_shots:
        from mvp.pairwise import _clean_rationale

        praw = Path(args.few_shot_pool[1:]).read_text() if args.few_shot_pool.startswith("@") else args.few_shot_pool
        pids = [int(x) for x in praw.replace("\n", ",").split(",") if x.strip()]
        pool = [FewShotExample(id=j, ctx=ctx_of(data[j]), win=(image_dir(j) / "win.png").read_bytes(),
                               lose=(image_dir(j) / "lose.png").read_bytes(),
                               rationale=_clean_rationale(data[j].get("rationale", "")))
                for j in pids if (image_dir(j) / "win.png").exists() and (image_dir(j) / "lose.png").exists()]
        print(f"[wiserui] few-shot pool: {len(pool)} pairs, k={flags.few_shot_k or flags.graded_shots}", flush=True)
    sem = asyncio.Semaphore(args.concurrency)
    cond = f"pw_{args.stream}" + ("_aa" if args.aa else "")
    print(f"[wiserui] {len(idxs)} pairs stream={args.stream} flags={flags} model={flags.model or PAIRWISE_MODEL} "
          f"a0_personas={len(a0)} prior_spend=${ledger.cost:.3f}", flush=True)
    (out / "config.json").write_text(json.dumps({"stream": args.stream, "inputs": extra, "flags": flags.__dict__, "model": flags.model or PAIRWISE_MODEL,
                                                 "personas_from": args.personas_from, "aa": args.aa, "n": len(idxs),
                                                 "seed_ledger": args.seed_ledger, "seed_match": args.seed_match,
                                                 "few_shot_pool": args.few_shot_pool,
                                                 "env": {k: os.environ.get(k) for k in ("OPENAI_REASONING_EFFORT", "MVP_GEMINI3_THINKING")}}, indent=1))

    results: dict[int, dict] = {}
    done = 0
    skipped: list[int] = []
    settle = asyncio.Condition()

    async def admit(i: int) -> float | None:
        """Short-pick streams: reserve the worst case of this pair's uncached calls, waiting while other pairs are in
        flight; None = does not fit even with nothing in flight (budget exhausted)."""
        orders = ("ab", "ba") if flags.both_orders else ("ab",)
        tag = short_call_tag(flags)
        w = worst_call_cost(flags.model or PAIRWISE_MODEL, flags.max_tokens)
        need = sum(w for o in orders if (ledger.cache.get(f"{i}|{tag}|{o}") or {"error": 1}).get("error"))
        async with settle:
            while ledger.cost + ledger.reserved + need > args.max_cost:
                if ledger.reserved <= 0:
                    return None
                await settle.wait()
            ledger.reserved += need
        return need

    async def pair(i: int) -> None:
        nonlocal done
        need = 0.0
        if flags.short_pick:
            got = await admit(i)
            if got is None:
                skipped.append(i)
                return
            need = got
        try:
            await pair_body(i, covered=flags.short_pick)
        finally:
            if flags.short_pick:
                async with settle:
                    ledger.reserved -= need
                    settle.notify_all()

    async def pair_body(i: int, covered: bool) -> None:
        nonlocal done
        item = data[i]
        ctx = ctx_of(item)
        if flags.gf_change:
            ctx["change"] = change_of(item)
        call = make_call(ledger, sem, f"{i}", max_cost=args.max_cost, covered=covered)
        personas = ab_personas(a0[i], ctx) if i in a0 else None
        aw = a_is_win(i)
        if args.aa:
            ev_a, ev_b = evidence(i, "win"), evidence(i, "win")
            ev_b.label = "win_copy"
        else:
            t = flags.gf_page_text
            ev_a, ev_b = ((evidence(i, "win", t), evidence(i, "lose", t)) if aw else
                          (evidence(i, "lose", t), evidence(i, "win", t)))
        try:
            res = await compare_pair(ev_a, ev_b, personas, ctx, flags, call=call, few_shot_pool=pool, pair_id=i)
        except Exception as exc:  # noqa: BLE001
            print(f"[wiserui] pair {i} failed: {exc!r}"[:300], flush=True)
            return
        res.update({"index": i, "a_is_win": aw, "source": source_of(item), "web_mobile": item["web_mobile"],
                    "personas_used": personas or [], "ctx": ctx,
                    "images": {"a": str(image_dir(i) / f"{ev_a.label.replace('_copy', '')}.png"),
                               "b": str(image_dir(i) / f"{ev_b.label.replace('_copy', '')}.png")}})
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
                row = {"condition": cond, "index": i, "order": "wl" if winner_first else "lw", "pick": pick,
                   "votes": votes, "tie_vote": ov["pick"] == "tie", "x_minus_y": ov["x_minus_y"],
                   "source": res["source"], "web_mobile": res["web_mobile"]}
            if "graded" in res:  # graded harness: pick is the order-invariant answer; the call's own P(First) too
                row.update({"p_a": res["p_a"], "confidence": res["confidence"],
                            "call_p_first": next((j["p_first"] for j in res["judgments"] if j["order"] == o), None)})
            rows.append(row)
    with (out / "judgments.jsonl").open("w") as f:
        for r in sorted(rows, key=lambda r: (r["index"], r["order"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    errs = sum(1 for r in ledger.cache.values() if r.get("error"))
    if skipped:
        print(f"[wiserui] budget cap ${args.max_cost:.2f}: skipped {len(skipped)} pairs (first {min(skipped)})", flush=True)
    print(f"[wiserui] wrote {len(results)} pairs; total spend ${ledger.cost:.3f}; call errors={errs}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
