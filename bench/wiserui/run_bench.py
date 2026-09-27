#!/usr/bin/env python3
"""WiserUI-Bench Task 1 (which A/B variant won?) with UserSim's model stack.

Conditions (each pair judged in BOTH orders: (win, lose) and (lose, win)):
  baseline      one gemini-2.5-flash call, the paper's zero_shot prompt verbatim + two screenshots
  baseline_ctx  same, plus the page context the planner gets (company / page type / industry / platform)
  usersim       UserSim-style: planner invents ~6 visitors for the page (context only, the
                _CMP_PERSONAS shape from mvp/fast_plan.py), each persona views both screenshots and
                says which it would act on; majority vote (tie -> summed confidence -> 'tie' = wrong)

Model access goes through UserSim's own Vertex client (mvp.e2e_ui_run._gemini_client) with
UserSim's call conventions (thinking_budget=0, JSON mime type for structured calls).
The dataset's `rationale` and `ui_change` fields are never shown to any model (rationale names the
winning side: "the right version ...").

Every model call is cached in $OUT/calls.jsonl keyed by (condition, index, order, role, k), so runs resume.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
DATA = BENCH / "repo" / "WiserUI_Bench.json"
IMAGES = BENCH / "images_clean"
PROMPT_ZS = (BENCH / "repo" / "inference" / "prompts_task1" / "zero_shot.txt").read_text()

MODEL = os.environ.get("WISERUI_MODEL", "gemini-2.5-flash")
# Vertex list price, gemini-2.5-flash (USD / 1M tokens): input 0.30 (text/image), output 2.50.
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-pro": (1.25, 10.0)}

ORDERS = {"wl": ("win", "lose"), "lw": ("lose", "win")}


def source_of(item: dict) -> str:
    s = item["source"]
    return "goodui" if "goodui" in s else "vwo" if "vwo" in s else "abtest"


def context_line(item: dict) -> str:
    return (f"{item['company']} {item['page_type']} ({item['industry_domain']}, "
            f"{item['web_mobile']} {'app/site' if item['web_mobile'] == 'mobile' else 'site'})")


# ----------------------------------------------------------------- prompts

PLANNER = """Invent six realistic visitors for a study of one page: the {page_type} of {company} ({industry}, {platform}). Reply with JSON only.

Return {{"personas": [{{"name": "first and last name", "role": "who they are (job or life situation)",
  "bio": "at most 25 words: situation, what they need from this page, how they judge it",
  "goal": "what they came to this page to do, 3-10 words"}}]}}
Rules: people who would really land on this page, spread evenly across intent: at least one ready to act now,
at least one comparing options or hesitant, at least one first-time visitor who does not know {company} yet.
Vary age, tech comfort and price sensitivity. Use the page's likely language market. No quotes."""

PERSONA = """You are {name}, {role}. {bio}
You came to {company}'s {page_type} ({platform}) to: {goal}.

The two screenshots show two versions of this page: the first image is the First version, the second image is the Second version.
Look at each one as if it were the page in front of you right now, as yourself (not as a designer).
Then say which version you would be more likely to act on: take the page's main next step (click the main button, add to cart, sign up, search, continue).

Return JSON only:
{{"noticed_first": "what catches your eye first on the First version, at most 15 words",
  "noticed_second": "what catches your eye first on the Second version, at most 15 words",
  "choice": "First or Second",
  "confidence": 1-5,
  "reason": "one sentence in your own voice"}}"""


# ----------------------------------------------------------------- model calls

class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.cache: dict[str, dict] = {}
        if path.exists():
            for line in path.open():
                try:
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec
                except Exception:
                    pass
        self.lock = asyncio.Lock()
        self.cost = 0.0
        self.new_cost = 0.0
        for rec in self.cache.values():
            self.cost += rec.get("cost_usd", 0.0)

    async def put(self, rec: dict) -> None:
        async with self.lock:
            self.cache[rec["key"]] = rec
            self.cost += rec.get("cost_usd", 0.0)
            self.new_cost += rec.get("cost_usd", 0.0)
            with self.path.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


_CLIENT = None


def client():
    global _CLIENT
    if _CLIENT is None:
        from mvp.e2e_ui_run import _gemini_client  # UserSim's Vertex client (auth.vertex_credentials)
        _CLIENT = _gemini_client()
    return _CLIENT


def _call(parts: list[Any], *, temperature: float, json_mode: bool, max_tokens: int) -> tuple[str, int, int]:
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # UserSim convention (gemini_config.py)
        response_mime_type="application/json" if json_mode else None,
        # UserSim leaves media resolution at the API default (~258 tokens/image); WISERUI_MEDIA_RES=high overrides.
        media_resolution=(types.MediaResolution.MEDIA_RESOLUTION_HIGH
                          if os.environ.get("WISERUI_MEDIA_RES") == "high" else None),
    )
    last = None
    for attempt in range(6):
        try:
            resp = client().models.generate_content(model=MODEL, contents=parts, config=cfg)
            um = resp.usage_metadata
            return (resp.text or "").strip(), int(um.prompt_token_count or 0), int(um.candidates_token_count or 0)
        except Exception as exc:  # 429 / 5xx: back off
            last = exc
            time.sleep(min(60, 3 * 2 ** attempt))
    raise RuntimeError(f"model call failed: {last!r}")


def img_part(idx: int, label: str):
    from google.genai import types
    return types.Part.from_bytes(data=(IMAGES / str(idx) / f"{label}.png").read_bytes(), mime_type="image/png")


async def cached_call(ledger: Ledger, sem: asyncio.Semaphore, key: str, parts_fn, **kw) -> dict:
    if key in ledger.cache and not ledger.cache[key].get("error"):
        return ledger.cache[key]
    async with sem:
        t0 = time.time()
        try:
            text, tin, tout = await asyncio.to_thread(_call, parts_fn(), **kw)
            err = None
        except Exception as exc:  # noqa: BLE001
            text, tin, tout, err = "", 0, 0, repr(exc)[:300]
    pin, pout = PRICE.get(MODEL, (0.30, 2.50))
    rec = {"key": key, "model": MODEL, "text": text, "tokens_in": tin, "tokens_out": tout,
           "cost_usd": tin / 1e6 * pin + tout / 1e6 * pout, "secs": round(time.time() - t0, 2), "error": err,
           "ts": time.time()}
    await ledger.put(rec)
    return rec


def parse_first_second(text: str) -> str | None:
    m = re.findall(r"More effective:\s*\**\s*<?\s*(First|Second)", text, re.I)
    if m:
        return m[-1].capitalize()
    return None


def parse_json(text: str) -> Any:
    m = re.search(r"[\[{].*[\]}]", text or "", re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except Exception:
        return None


# ----------------------------------------------------------------- conditions

async def run_baseline(item: dict, order: str, ledger, sem, *, with_ctx: bool) -> dict:
    idx = item["index"]
    a, b = ORDERS[order]
    cond = "baseline_ctx" if with_ctx else "baseline"
    prompt = PROMPT_ZS
    if with_ctx:
        prompt = f"Page: {context_line(item)}.\n\n" + PROMPT_ZS
    rec = await cached_call(ledger, sem, f"{cond}|{idx}|{order}|judge|0",
                            lambda: [prompt, img_part(idx, a), img_part(idx, b)],
                            temperature=0.2, json_mode=False, max_tokens=2048)
    pick = parse_first_second(rec["text"])
    return {"condition": cond, "index": idx, "order": order, "pick": pick, "votes": None}


async def plan_personas(item: dict, ledger, sem, n: int) -> list[dict]:
    idx = item["index"]
    prompt = PLANNER.format(page_type=item["page_type"], company=item["company"], industry=item["industry_domain"],
                            platform=("mobile app or mobile site" if item["web_mobile"] == "mobile" else "website"))
    rec = await cached_call(ledger, sem, f"usersim|{idx}|-|planner|0", lambda: [prompt],
                            temperature=0.3, json_mode=True, max_tokens=2048)
    data = parse_json(rec["text"]) or {}
    personas = [p for p in (data.get("personas") or []) if isinstance(p, dict) and p.get("name")]
    return personas[:n]


async def run_usersim(item: dict, order: str, personas: list[dict], ledger, sem) -> dict:
    idx = item["index"]
    a, b = ORDERS[order]
    platform = "mobile" if item["web_mobile"] == "mobile" else "website"

    async def one(k: int, p: dict) -> dict:
        prompt = PERSONA.format(name=p.get("name", ""), role=p.get("role", ""), bio=p.get("bio", ""),
                                goal=p.get("goal", "look around"), company=item["company"],
                                page_type=item["page_type"], platform=platform)
        rec = await cached_call(ledger, sem, f"usersim|{idx}|{order}|persona|{k}",
                                lambda: [prompt, img_part(idx, a), img_part(idx, b)],
                                temperature=0.4, json_mode=True, max_tokens=512)
        j = parse_json(rec["text"]) or {}
        ch = str(j.get("choice") or "").strip().capitalize()
        try:
            conf = float(j.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        return {"k": k, "persona": p.get("name"), "choice": ch if ch in ("First", "Second") else None,
                "confidence": conf, "reason": j.get("reason")}

    votes = await asyncio.gather(*(one(k, p) for k, p in enumerate(personas)))
    nf = sum(v["choice"] == "First" for v in votes)
    ns = sum(v["choice"] == "Second" for v in votes)
    if nf != ns:
        pick = "First" if nf > ns else "Second"
    else:
        cf = sum(v["confidence"] for v in votes if v["choice"] == "First")
        cs = sum(v["confidence"] for v in votes if v["choice"] == "Second")
        pick = "First" if cf > cs else "Second" if cs > cf else "tie"
    return {"condition": "usersim", "index": idx, "order": order, "pick": pick, "votes": votes,
            "n_first": nf, "n_second": ns, "tie_vote": nf == ns}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="", help="comma list or @file; default all usable pairs with images")
    ap.add_argument("--conditions", default="baseline,baseline_ctx,usersim")
    ap.add_argument("--personas", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--out", default=str(BENCH / "results" / "run1"))
    ap.add_argument("--max-cost", type=float, default=40.0, help="stop scheduling new pairs above this spend")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {x["index"]: x for x in json.load(open(DATA))}
    raw = args.indices
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    if raw.strip():
        idxs = [int(i) for i in raw.replace("\n", ",").split(",") if i.strip()]
    else:
        idxs = sorted(data)
    idxs = [i for i in idxs if (IMAGES / str(i) / "win.png").exists() and (IMAGES / str(i) / "lose.png").exists()]
    conds = [c.strip() for c in args.conditions.split(",") if c.strip()]
    ledger = Ledger(out / "calls.jsonl")
    sem = asyncio.Semaphore(args.concurrency)
    print(f"[wiserui] {len(idxs)} pairs x {conds} model={MODEL} prior_spend=${ledger.cost:.3f}", flush=True)

    rows: list[dict] = []
    done = 0

    async def pair(i: int) -> None:
        nonlocal done
        if ledger.cost > args.max_cost:
            return
        item = data[i]
        jobs = []
        for order in ORDERS:
            if "baseline" in conds:
                jobs.append(run_baseline(item, order, ledger, sem, with_ctx=False))
            if "baseline_ctx" in conds:
                jobs.append(run_baseline(item, order, ledger, sem, with_ctx=True))
        if "usersim" in conds:
            personas = await plan_personas(item, ledger, sem, args.personas)
            for order in ORDERS:
                jobs.append(run_usersim(item, order, personas, ledger, sem))
        res = await asyncio.gather(*jobs)
        for r in res:
            r["source"] = source_of(item)
            r["web_mobile"] = item["web_mobile"]
        rows.extend(res)
        done += 1
        if done % 10 == 0 or done == len(idxs):
            print(f"[wiserui] {done}/{len(idxs)} pairs  spend=${ledger.cost:.3f} (this run ${ledger.new_cost:.3f})", flush=True)

    # Bounded pair-level fan-out so partial results land early.
    psem = asyncio.Semaphore(max(2, args.concurrency // 2))

    async def guarded(i):
        async with psem:
            await pair(i)

    await asyncio.gather(*(guarded(i) for i in idxs))
    rows.sort(key=lambda r: (r["condition"], r["index"], r["order"]))
    with (out / "judgments.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    errs = sum(1 for r in ledger.cache.values() if r.get("error"))
    print(f"[wiserui] wrote {len(rows)} judgments; total spend ${ledger.cost:.3f}; call errors={errs}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
