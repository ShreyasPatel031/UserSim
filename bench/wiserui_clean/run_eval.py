#!/usr/bin/env python3
"""Run WiserUI-Bench task 1 (which version won) on the clean image set, both presentation orders.

Arms (prompts verbatim from the paper / grokbot/pairwise-judge mvp/pairwise.py):
  zero_shot  inference/prompts_task1/zero_shot.txt, the two screenshots after the prompt, temperature 0.2
  gfocus     G-FOCUS (arXiv 2505.05026v1 Appendix E): goal -> goal-conditioned key UI differences -> reasons assuming
             First wins / Second wins -> Evaluator. One neutral judge, per order (strict), temperature 0 (the
             repeatable setting, NOISE_REPORT.md on grokbot/pairwise-judge). Evaluator re-asked up to 2x on a bad format.

Models: gemini-2.5-flash on Vertex (thinking off), or a Claude model on Vertex (``--model claude-haiku-4-5@20251001``,
AnthropicVertex, no extended thinking, regions from CLAUDE_VERTEX_LOCATIONS; images downscaled to Claude's native
1568 px long edge). Same prompts, temperatures and parsing for every model. Every call is cached in $WISERUI_CLEAN/eval/calls.jsonl with its
token usage, so a rerun is free and costs are measured, not estimated.

    python bench/wiserui_clean/run_eval.py --arms zero_shot,gfocus [--indices 0,1,2] [--max-cost 10]
    -> $WISERUI_CLEAN/eval/{model}_{arm}.jsonl, summary printed and written to bench/wiserui_clean/results_<model>.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import time
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("WISERUI_CLEAN", "/workspace/bench/wiserui_clean"))
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "claude-haiku-4-5@20251001": (1.00, 5.00)}
CLAUDE_LOCS = os.environ.get("CLAUDE_VERTEX_LOCATIONS", "global,us-east5,europe-west1").split(",")
LOCS = [os.environ.get("VERTEX_LOCATION", "us-central1"), "us-east4", "us-west1", "europe-west4", "us-east1", "global"]

ZERO_SHOT = """You are an expert in designing UI/UX for web/apps.

The two screenshots show two different versions of the same page.
Identify the key UI differences between the two versions, and then evaluate which variant is more effective UI/UX design that leads to better user experience and conversion.

You should end your answer with following the format (No bold, etc):
More effective: <First/Second>"""

HEAD = """The two screenshots show two different versions of the same page.
FYI, the page is from the company called '{company}' whose industry domain is {industry}.
The page type is {page_type} on {web_mobile} environment."""

GOAL = """Your task is to think about the goal of the site operator for the given UIs.

{head}

Based on the two UIs and the industry and page type, what is the main goal of the site operator for this page?

Answer strictly in the following format:
[Goal]
<goal of the site operator considering industry and page type>"""

DIFFS = """You are an expert in designing UI/UX for web/apps.

{head}

Your task is to find the crucial and major UI differences between the two versions.

To do that,
(1) Reflect what would be the fundamental and crucial design priorities on the current page, if the goal of the site operator on the current page is as follows:
{goal}
(2) "See" the provided screenshots of the page, focusing on the key UI areas related to what you have reflected as your prioritized design principles.
(3) For each key UI area, localize it by imagining patches and highlight main UI differences within the patches of the versions.

Be aware:
- Mention key differences in terms of the given goal and design priorities.
- Do not mention differences in an abstract nor subjective way.
(example to avoid: "First UI has more prominent visual clutter." -> "more prominent": subjective expression, "visual clutter": abstract expression)
- Avoid mentioning differences which can be placeholders that can differ by example cases.
(example to avoid: "First UI has product image of apple, Second UI has banana." -> product images can be just placeholders)
- Prefer to infer comprehensive differences that can be inferred by combining multiple UI components from the images and given information.

You must give the answer and give the answer strictly in the following format:
[Design priorities]
1. <Key priority>
2. <Key priority>
...
[UI areas to focus]
1. <Key UI area>
2. <Key UI area>
...
[Key UI differences]
First UI <Key UI difference>, Second UI <Key UI difference>.
First UI <Key UI difference>, Second UI <Key UI difference>.
..."""

USER = "Assume that a user is currently engaging with the page shown in the screenshot."

REASON = """You are an expert in designing UI/UX for web/apps.

{head}

{user}
Inferred main goal of the site operator is as follows:
{goal}

Already found key UI differences between the two versions are as follows:
{ui_diff}

Then, assuming {which} version was more visually persuasive in terms of achieving the inferred goal, you should make reasonable reasons for such result.

Your reply should strictly follow the format.:
[Evaluation]
1. <Rationale of the evaluation in sentences>
2. <Rationale of the evaluation in sentences>
..."""

EVAL = """You are an expert in designing UI/UX for web/apps.

{head}

{user}
Inferred main goal of the site operator is as follows:
{goal}

Already found key UI differences between the two versions are as follows:
{ui_diff}

Then, we have made possible reasons of why first version would have been more visually persuasive in terms of achieving the inferred goal:
{first_reason}

We also made possible reasons of why second version would have been more visually persuasive in terms of achieving the inferred goal:
{second_reason}

Considering all these possible reasons, your task is to conclude which version would be visually persuasive in terms of achieving the inferred goal.
Reasons' decisions of first/second version are all different, so you should think carefully reminding:
(1) Reasons may contradict each other, then you should decide which is more reasonable.
(2) Then make your own rankings between the evaluations based on importance for making a final decision.
(3) Based on the rankings, conclude which version would be visually persuasive in terms of achieving the inferred goal with a precise overall rationale that only contains key points that you think are crucial.

Here, such precise overall rationale should be consisted of key points mentioning:
(1) which UI difference was key to the winning version's success and
(2) how each UI difference affected the winning version positively

Your reply should strictly follow the format:
[Importance Ranking]
1. <First/Second + Reason # (e.g. First 2)> - <Why you think this reason is the most important>
2. <First/Second + Reason # (e.g. Second 3)> - <Why you think this reason is the second important>
...
[Conclusion]
Better version: <First/Second>
Key Rationale:
* <UI Difference>: <Positive effects>
* ... (if multiple)"""


def section(text: str, head: str) -> str:
    t = (text or "").replace("**", "")
    m = re.search(r"\[\s*" + re.escape(head) + r"\s*\]\s*:?", t, re.I)
    if not m:
        return t.strip()
    rest = t[m.end():]
    n = re.search(r"\n\s*\[[A-Z][^\]\n]{2,40}\]", rest)
    return (rest[: n.start()] if n else rest).strip()


def parse_pick(text: str, label: str) -> str | None:
    t = (text or "").replace("**", "").replace("*", " ")
    m = re.findall(label + r"\s*:?\s*<?\s*(First|Second)\b", t, re.I)
    return m[-1].capitalize() if m else None


class Ledger:
    def __init__(self, path: Path):
        self.path, self.cache = path, {}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            for line in path.open():
                r = json.loads(line)
                if not r.get("error"):
                    self.cache[r["key"]] = r
        self.new_cost = 0.0

    def put(self, r: dict) -> None:
        self.cache[r["key"]] = r
        self.new_cost += r.get("cost_usd", 0.0)
        with self.path.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


_clients: dict = {}
_claude: dict = {}


def claude_client(loc: str):
    if loc not in _claude:
        from anthropic import AnthropicVertex

        _claude[loc] = AnthropicVertex(project_id=os.environ["GOOGLE_CLOUD_PROJECT"], region=loc, max_retries=0)
    return _claude[loc]


def gen_claude(model: str, parts: list, temperature: float, max_tokens: int, seed_key: str):
    import base64

    import anthropic

    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.standard_b64encode(p).decode()}}
               if isinstance(p, bytes) else {"type": "text", "text": p} for p in parts]
    start = int(hashlib.md5(seed_key.encode()).hexdigest(), 16) % len(CLAUDE_LOCS)
    last = None
    for attempt in range(14):
        loc = CLAUDE_LOCS[(start + attempt) % len(CLAUDE_LOCS)]
        try:
            r = claude_client(loc).messages.create(
                model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": content}],
                extra_body={"temperature": temperature})  # SDK 1.x has no typed temperature; Haiku 4.5 accepts it
            text = "".join(b.text for b in r.content if b.type == "text")
            return text, int(r.usage.input_tokens), int(r.usage.output_tokens)
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            last = exc
        except anthropic.APIStatusError as exc:
            last = exc
            if exc.status_code < 500 and exc.status_code not in (408, 409, 429):
                break
        time.sleep(min(30, 1.5 * 2 ** (attempt // len(CLAUDE_LOCS))) + random.random())
    raise RuntimeError(repr(last)[:300])


def client(loc: str):
    if loc not in _clients:
        from google import genai

        _clients[loc] = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=loc)
    return _clients[loc]


def gen(model: str, parts: list, temperature: float, max_tokens: int, seed_key: str):
    if model.startswith("claude"):
        return gen_claude(model, parts, temperature, max_tokens, seed_key)
    from google.genai import types

    contents = [types.Part.from_bytes(data=p, mime_type="image/jpeg") if isinstance(p, bytes)
                else types.Part.from_text(text=p) for p in parts]
    cfg = types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens,
                                      thinking_config=types.ThinkingConfig(thinking_budget=0))
    start = int(hashlib.md5(seed_key.encode()).hexdigest(), 16) % len(LOCS)
    last = None
    for attempt in range(14):
        loc = LOCS[(start + attempt) % len(LOCS)]
        try:
            r = client(loc).models.generate_content(model=model, contents=contents, config=cfg)
            um = r.usage_metadata
            return (r.text or ""), int(um.prompt_token_count or 0), int(um.candidates_token_count or 0)
        except Exception as exc:  # noqa: BLE001
            last = exc
            code = getattr(exc, "code", None)
            if isinstance(code, int) and 400 <= code < 500 and code != 429:
                break
            time.sleep(min(30, 1.5 * 2 ** (attempt // len(LOCS))) + random.random())
    raise RuntimeError(repr(last)[:300])


class Runner:
    def __init__(self, model: str, ledger: Ledger, sem: asyncio.Semaphore, max_cost: float):
        self.model, self.ledger, self.sem, self.max_cost = model, ledger, sem, max_cost

    async def call(self, key: str, parts: list, temperature: float, max_tokens: int) -> str:
        key = f"{self.model}|{key}"
        hit = self.ledger.cache.get(key)
        if hit:
            return hit["text"]
        if self.ledger.new_cost > self.max_cost:
            raise RuntimeError("max cost reached")
        async with self.sem:
            t0 = time.time()
            try:
                text, tin, tout = await asyncio.to_thread(gen, self.model, parts, temperature, max_tokens, key)
                err = None
            except Exception as exc:  # noqa: BLE001
                text, tin, tout, err = "", 0, 0, repr(exc)[:300]
        pin, pout = PRICE[self.model]
        self.ledger.put({"key": key, "text": text, "tokens_in": tin, "tokens_out": tout, "error": err,
                         "cost_usd": tin / 1e6 * pin + tout / 1e6 * pout, "secs": round(time.time() - t0, 1)})
        if err:
            raise RuntimeError(err)
        return text


def load_image(path: Path, max_side: int = 3072) -> bytes:
    from PIL import Image

    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    b = BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue()


async def zero_shot(r: Runner, i: int, order: str, first: bytes, second: bytes, it: dict) -> dict:
    pick, text = None, ""
    for attempt in range(3):
        text = await r.call(f"{i}|zs|{order}" + (f"|r{attempt}" if attempt else ""),
                            [ZERO_SHOT, first, second], 0.2, 2048)
        pick = parse_pick(text, "More effective")
        if pick:
            break
    return {"pick": pick, "text": text[-600:]}


async def gfocus(r: Runner, i: int, order: str, first: bytes, second: bytes, it: dict) -> dict:
    T = 0.0
    head = HEAD.format(company=it["company"], industry=it["industry_domain"], page_type=it["page_type"],
                       web_mobile=it["web_mobile"])
    imgs = [first, second]
    g = await r.call(f"{i}|gf|{order}|goal", [GOAL.format(head=head), *imgs], T, 600)
    goal = " ".join(section(g, "Goal").split())[:600]
    d = await r.call(f"{i}|gf|{order}|diffs", [DIFFS.format(head=head, goal=goal), *imgs], T, 2048)
    ui_diff = section(d, "Key UI differences")[:4000]

    async def reason(which: str) -> str:
        t = await r.call(f"{i}|gf|{order}|reason_{which}",
                         [REASON.format(head=head, user=USER, goal=goal, ui_diff=ui_diff, which=which), *imgs], T, 1500)
        return section(t, "Evaluation")[:4000]

    r1, r2 = await asyncio.gather(reason("first"), reason("second"))
    prompt = EVAL.format(head=head, user=USER, goal=goal, ui_diff=ui_diff, first_reason=r1, second_reason=r2)
    pick, text = None, ""
    for attempt in range(3):
        text = await r.call(f"{i}|gf|{order}|eval" + (f"|r{attempt}" if attempt else ""), [prompt, *imgs], T, 2048)
        pick = parse_pick(text, "Better version")
        if pick:
            break
    return {"pick": pick, "goal": goal, "text": section(text, "Conclusion")[:600]}


ARMS = {"zero_shot": zero_shot, "gfocus": gfocus}


def metrics(rows: list[dict]) -> dict:
    """Paper task-1 metrics. Order "ab" shows the winner first. CA = right in both orders (chance 25%)."""
    by = {}
    for x in rows:
        by.setdefault(x["index"], {})[x["order"]] = x["pick"]
    n = len(by)
    fa = sum(v.get("ab") == "First" for v in by.values()) / n
    sa = sum(v.get("ba") == "Second" for v in by.values()) / n
    ca = sum(v.get("ab") == "First" and v.get("ba") == "Second" for v in by.values()) / n
    picks = [p for v in by.values() for p in v.values()]
    return {"n_pairs": n, "CA": round(100 * ca, 1), "AA": round(50 * (fa + sa), 1), "FA": round(100 * fa, 1),
            "SA": round(100 * sa, 1), "pick_first_pct": round(100 * sum(p == "First" for p in picks) / len(picks), 1),
            "unparsed": sum(p is None for p in picks)}


def bootstrap_ca(rows: list[dict], reps: int = 10000) -> list[float]:
    by = {}
    for x in rows:
        by.setdefault(x["index"], {})[x["order"]] = x["pick"]
    hits = [int(v.get("ab") == "First" and v.get("ba") == "Second") for v in by.values()]
    rng = random.Random(0)
    s = sorted(sum(rng.choice(hits) for _ in hits) / len(hits) for _ in range(reps))
    return [round(100 * s[int(0.025 * reps)], 1), round(100 * s[int(0.975 * reps)], 1)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="zero_shot,gfocus")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--indices", default="")
    ap.add_argument("--concurrency", type=int, default=48)
    ap.add_argument("--max-cost", type=float, default=10.0, help="stop making new calls past this new spend (USD)")
    args = ap.parse_args()
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(args.concurrency + 8))
    data = {x["index"]: x for x in json.load(open(ROOT / "repo" / "WiserUI_Bench.json"))}
    idxs = [int(i) for i in args.indices.split(",") if i.strip()] or sorted(data)
    out = ROOT / "eval"
    ledger = Ledger(out / "calls.jsonl")
    r = Runner(args.model, ledger, asyncio.Semaphore(args.concurrency), args.max_cost)
    side = 1568 if args.model.startswith("claude") else 3072
    imgs = {i: {lab: load_image(ROOT / "final" / str(i) / f"{lab}.png", side) for lab in ("win", "lose")} for i in idxs}
    summary = {"model": args.model, "image_set": "bench/wiserui_clean (300 pairs)", "arms": {}}
    t0 = time.time()
    for arm in args.arms.split(","):
        fn = ARMS[arm]

        async def one(i: int, order: str) -> dict:
            first, second = ((imgs[i]["win"], imgs[i]["lose"]) if order == "ab" else (imgs[i]["lose"], imgs[i]["win"]))
            try:
                res = await fn(r, i, order, first, second, data[i])
            except Exception as exc:  # noqa: BLE001
                res = {"pick": None, "error": str(exc)[:200]}
            return {"index": i, "order": order, "source": data[i]["source"].split("/")[2].replace("www.", ""),
                    "web_mobile": data[i]["web_mobile"], **res}

        rows = await asyncio.gather(*(one(i, o) for i in idxs for o in ("ab", "ba")))
        with (out / f"{args.model.split('@')[0]}_{arm}.jsonl").open("w") as f:
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        m = metrics(rows)
        m["CA_95ci"] = bootstrap_ca(rows)
        m["errors"] = sum(1 for x in rows if x.get("error"))
        m["by_source"] = {s: metrics([x for x in rows if x["source"] == s])
                          for s in sorted({x["source"] for x in rows})}
        keys = [k for k in ledger.cache if k.startswith(args.model + "|")
                and f"|{'zs' if arm == 'zero_shot' else 'gf'}|" in k and int(k.split("|")[1]) in set(idxs)]
        m["cost_usd"] = round(sum(ledger.cache[k]["cost_usd"] for k in keys), 3)
        m["calls"] = len(keys)
        summary["arms"][arm] = m
        print(arm, json.dumps({k: v for k, v in m.items() if k != "by_source"}), f"{time.time() - t0:.0f}s", flush=True)
    summary["new_spend_usd"] = round(ledger.new_cost, 3)
    if len(idxs) == len(data):
        (HERE / f"results_{args.model.split('@')[0]}.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
