#!/usr/bin/env python3
"""Recover WiserUI-Bench composite pairs (win_url == lose_url: one image holding both variants).

Stages (each model call cached in $OUT/calls.jsonl with cost; resumable; fully parallel):
  split  gemini-2.5-pro (thinking) sees the composite + dataset metadata (ui_change, rationale) + the source page text,
         returns tight boxes for the two variant panels of THIS pair and which one won (with evidence + confidence).
         Panels are cropped to images_recovered/{i}/{win,lose}.png. No masking / inpainting.
  leak   gemini-2.5-flash checks the original composite and each cropped panel for answer leakage (CONTROL/VARIATION,
         A/B, winner/trophy, lift %, "outperformed", arrows/highlights marking the winner). JSON per image.
  sheet  contact sheets of the crops for visual review.

The dataset rationale / source text are used ONLY to assign winner/loser (labels), never shown to the judged model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
DATA = BENCH / "repo" / "WiserUI_Bench.json"
RAW = BENCH / "images"
REC = BENCH / "images_recovered"
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-pro": (1.25, 10.0)}
LOCS = [None, "us-east4", "us-west1", "europe-west4", "asia-northeast1", "global"]


def img_bytes(im, fmt="PNG") -> bytes:
    b = BytesIO()
    im.save(b, fmt)
    return b.getvalue()


def shrink(im, max_side=3072):
    im = im.convert("RGB")
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side))
    return im


class Ledger:
    def __init__(self, path: Path):
        self.path, self.cache, self.cost = path, {}, 0.0
        if path.exists():
            for line in path.open():
                try:
                    r = json.loads(line)
                    self.cache[r["key"]] = r
                except Exception:  # noqa: BLE001
                    pass
        self.cost = sum(r.get("cost_usd", 0.0) for r in self.cache.values())

    def put(self, r: dict) -> None:
        self.cache[r["key"]] = r
        self.cost += r.get("cost_usd", 0.0)
        with self.path.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _gen(model: str, contents: list, thinking: int, max_tokens: int, high: bool):
    from google.genai import types

    from mvp.e2e_ui_run import _gemini_client_at

    parts = [types.Part.from_bytes(data=c, mime_type="image/png") if isinstance(c, bytes) else types.Part.from_text(text=c)
             for c in contents]
    cfg = types.GenerateContentConfig(
        temperature=0.0, max_output_tokens=max_tokens, response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_budget=thinking),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH if high else None)
    last = None
    for attempt in range(12):
        loc = LOCS[attempt % len(LOCS)] if attempt else None
        try:
            r = _gemini_client_at(loc).models.generate_content(model=model, contents=parts, config=cfg)
            um = r.usage_metadata
            tin = int(um.prompt_token_count or 0)
            tout = int(um.candidates_token_count or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
            return (r.text or "").strip(), tin, tout
        except Exception as exc:  # noqa: BLE001
            last = exc
            code = getattr(exc, "code", None)
            if isinstance(code, int) and 400 <= code < 500 and code != 429:
                break
            time.sleep(min(20, 1.0 * 2 ** (attempt // len(LOCS))))
    raise RuntimeError(f"gemini failed: {last!r}")


async def call(ledger: Ledger, sem, key: str, model: str, contents: list, *, thinking=0, max_tokens=2048, high=True):
    hit = ledger.cache.get(key)
    if hit and not hit.get("error"):
        return hit["text"]
    async with sem:
        t0 = time.time()
        try:
            text, tin, tout = await asyncio.to_thread(_gen, model, contents, thinking, max_tokens, high)
            err = None
        except Exception as exc:  # noqa: BLE001
            text, tin, tout, err = "", 0, 0, repr(exc)[:300]
    pin, pout = PRICE[model]
    ledger.put({"key": key, "model": model, "text": text, "tokens_in": tin, "tokens_out": tout,
                "cost_usd": tin / 1e6 * pin + tout / 1e6 * pout, "secs": round(time.time() - t0, 1), "error": err})
    return text


def parse(text: str):
    m = re.search(r"[\[{].*[\]}]", text or "", re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except Exception:  # noqa: BLE001
        return None


SPLIT = """This image is a composite published with an A/B test result. It shows two or more versions (variants) of a
{platform} page from {company} ({page_type}) side by side, stacked, or in a grid, often with labels such as
CONTROL / VARIATION / A / B, captions, trophies, arrows or result text.

This dataset item is ONE winner-vs-loser pair from that test. What changed between the versions (dataset "ui_change"): {ui_change}
The dataset's explanation of WHY THE WINNER WON (it describes the winning version):
{rationale}

Text of the source page that published the test (may mention which version won and by how much):
<<<
{source_text}
>>>

Tasks:
1. Find the panels: each panel is ONE version's screenshot (the UI itself). Give a TIGHT box around the screenshot pixels
   only, EXCLUDING labels, badges, captions, result banners, trophies and annotation arrows that sit outside the
   screenshot. If a label overlaps the screenshot, still box the whole screenshot.
2. If the image has more than two versions, pick the two that form THIS pair (use ui_change and rationale).
3. Decide which of the two panels is the WINNER of this pair, using the rationale (which describes the winner) and the
   source text / labels. Say how sure you are: "high" (rationale or source clearly identifies it), "medium", or "low".
4. If the image does not actually contain two separate version screenshots (e.g. only one version, or a chart), say so.

Box format: [ymin, xmin, ymax, xmax] normalized to 0-1000.
Return JSON only:
{{"layout": "side_by_side|stacked|grid|single|other", "n_versions_in_image": int,
  "panels": [{{"box_2d": [ymin, xmin, ymax, xmax], "label_in_image": "text of its label or null", "role": "control|variation|unknown"}}, ...exactly two for this pair],
  "winner_panel": 0 or 1, "confidence": "high|medium|low", "winner_evidence": "one or two sentences",
  "two_real_versions": true/false, "notes": "anything odd"}}"""

LEAK = """You are auditing an image used in a benchmark where a model must guess which version of a web/app page won
an A/B test. {what}

Does this image contain ANY cue that reveals or hints which version won or which is the control/original vs the
variation/new version? Cues include: labels like CONTROL, VARIATION, ORIGINAL, NEW, VERSION A/B, "A"/"B" badges,
"winner", check marks or trophies, crowns, lift or result percentages ("+25%", "increase"), text like "outperformed",
"won", "result", annotation arrows / circles / highlight boxes added by the test publisher to point at the change or the
winner, or captions describing the change. Ordinary UI content of the page itself (its own buttons, prices, product
discount badges) is NOT a cue.

Also say whether the image is a complete, usable screenshot of ONE page version (not cut off mid-way badly, not two
versions, not blank).

Return JSON only:
{{"leak": true/false, "cues": [{{"type": "label|ab_badge|trophy|lift_percent|result_text|arrow_or_highlight|caption|other", "text": "the text if any", "where": "short location"}}],
  "single_full_ui": true/false, "ui_notes": "short"}}"""


# Multi-variant composites shared by several dataset items: which two versions form each item, decided by manual
# review of the item's rationale/ui_change against the image and source text (the model otherwise picks the headline
# winner-vs-control pair for every item, duplicating it).
PAIR_HINTS = {
    158: "This item is VARIATION 2 (winner; adds the 'Call us on <phone>' line) vs VARIATION 1 (loser; no phone number).",
    159: "This item is VARIATION 2 (winner; phone number in orange) vs VARIATION 3 (loser; phone number/email in dark text with icons).",
    293: "This item is version C (winner; bordered 'See all free classes' button at bottom center) vs version B (loser; 'See all' link at top right). Source: C 13k clicks > A 9k > B 7k.",
    294: "This item is version A (winner; 'See all free classes' at bottom center, no border) vs version B (loser; 'See all' at top right). Source: C 13k clicks > A 9k > B 7k.",
}


def src_text(url: str) -> str:
    m = json.load(open(BENCH / "composite" / "src_map.json"))
    p = m.get(url)
    t = ""
    if p:
        f = BENCH / "composite" / p
        if f.exists():
            t = f.read_text()
    return t[:12000]


def crop(im, box, pad=0.0):
    W, H = im.size
    y0, x0, y1, x1 = [float(v) for v in box]
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    x0, x1 = max(0, x0 / 1000 * W), min(W, x1 / 1000 * W)
    y0, y1 = max(0, y0 / 1000 * H), min(H, y1 / 1000 * H)
    return im.crop((int(x0), int(y0), int(round(x1)), int(round(y1))))


async def stage_split(idxs, data, ledger, sem, out):
    from PIL import Image

    res = {}

    async def one(i):
        it = data[i]
        comp = Image.open(RAW / str(i) / "win.png").convert("RGB")
        prompt = SPLIT.format(platform="mobile" if it["web_mobile"] == "mobile" else "web", company=it["company"],
                              page_type=it["page_type"], ui_change=json.dumps(it["ui_change"]),
                              rationale="\n".join(f"- {r['reason']}" for r in it["rationale"]),
                              source_text=src_text(it["source"]))
        if i in PAIR_HINTS:
            prompt += f"\n\nPAIR (from manual review of this item's rationale): {PAIR_HINTS[i]}"
        text = await call(ledger, sem, f"{i}|split" + ("_hint" if i in PAIR_HINTS else ""), "gemini-2.5-pro",
                          [prompt, img_bytes(shrink(comp))], thinking=4096, max_tokens=8192)
        j = parse(text) or {}

        def out_of_range(j):
            return isinstance(j, dict) and any(isinstance(v, (int, float)) and not 0 <= v <= 1000
                                               for p in (j.get("panels") or []) if isinstance(p, dict)
                                               for v in (p.get("box_2d") or []))
        if out_of_range(j):  # box outside 0-1000 (the model sometimes answers in pixels): ask once more
            text = await call(ledger, sem, f"{i}|split2", "gemini-2.5-pro", [
                prompt + "\n\nIMPORTANT: every box coordinate MUST be normalized to 0-1000 (not pixels).",
                img_bytes(shrink(comp))], thinking=4096, max_tokens=8192)
            j = parse(text) or {}
        if i == 280 and out_of_range(j):  # retried answer still on a ~0-1920 x scale (symmetric 42 margins): rescale
            for p in j["panels"]:
                p["box_2d"] = [p["box_2d"][0], p["box_2d"][1] / 1.92, p["box_2d"][2], p["box_2d"][3] / 1.92]
        ok = (isinstance(j, dict) and len(j.get("panels") or []) == 2 and j.get("winner_panel") in (0, 1)
              and all(isinstance(p, dict) and isinstance(p.get("box_2d"), list) and len(p["box_2d"]) == 4
                      and all(isinstance(v, (int, float)) for v in p["box_2d"]) for p in j["panels"]))
        rec = {"index": i, "raw": j, "ok": ok, "size": comp.size}
        if ok:
            w = j["winner_panel"]
            try:
                crops = {lab: crop(comp, j["panels"][k]["box_2d"]) for lab, k in (("win", w), ("lose", 1 - w))}
                if min(min(c.size) for c in crops.values()) < 40:
                    raise ValueError(f"tiny crop {[c.size for c in crops.values()]}")
            except Exception as exc:  # noqa: BLE001
                ok, rec["ok"], rec["error"] = False, False, f"bad box: {exc}"
            if ok:
                d = REC / str(i)
                d.mkdir(parents=True, exist_ok=True)
                for lab, c in crops.items():
                    c.save(d / f"{lab}.png")
                    rec[f"{lab}_size"] = c.size
        res[i] = rec

    await asyncio.gather(*(one(i) for i in idxs))
    with (out / "split.jsonl").open("w") as f:
        for i in sorted(res):
            f.write(json.dumps(res[i]) + "\n")
    return res


async def stage_leak(idxs, data, ledger, sem, out):
    from PIL import Image

    res = {}

    async def one(i):
        r = {"index": i}
        jobs = [("composite", RAW / str(i) / "win.png",
                 "This is the ORIGINAL composite image as published (it may show several versions).")]
        for lab in ("win", "lose"):
            p = REC / str(i) / f"{lab}.png"
            if p.exists():
                jobs.append((lab, p, "This is ONE cropped panel that should show a single version of the page."))

        async def chk(name, p, what):
            im = shrink(Image.open(p))
            text = await call(ledger, sem, f"{i}|leak|{name}", "gemini-2.5-flash", [LEAK.format(what=what), img_bytes(im)],
                              thinking=0, max_tokens=1024)
            r[name] = parse(text) or {"parse_error": text[:200]}

        await asyncio.gather(*(chk(*j) for j in jobs))
        res[i] = r

    await asyncio.gather(*(one(i) for i in idxs))
    with (out / "leak.jsonl").open("w") as f:
        for i in sorted(res):
            f.write(json.dumps(res[i]) + "\n")
    return res


def stage_sheet(idxs, out):
    from PIL import Image, ImageDraw

    idxs = [i for i in idxs if (REC / str(i) / "win.png").exists() and (REC / str(i) / "lose.png").exists()]
    per, W, H = 8, 520, 460
    for s in range(0, len(idxs), per):
        ch = idxs[s:s + per]
        sheet = Image.new("RGB", (W * 4, H * ((len(ch) + 1) // 2)), "white")
        dr = ImageDraw.Draw(sheet)
        for k, i in enumerate(ch):
            for m, lab in enumerate(("win", "lose")):
                im = Image.open(REC / str(i) / f"{lab}.png").convert("RGB")
                sz = im.size
                im.thumbnail((W - 10, H - 30))
                x, y = ((k % 2) * 2 + m) * W, (k // 2) * H
                sheet.paste(im, (x + 5, y + 25))
                dr.rectangle([x, y, x + W - 1, y + H - 1], outline="gray")
                dr.text((x + 5, y + 5), f"{i} {lab} {sz}", fill="red" if lab == "win" else "blue")
        sheet.save(out / f"crops_{s // per}.png")


async def main():
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(96))
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["split", "leak", "sheet", "all"])
    ap.add_argument("--indices", default=f"@{BENCH / 'composite_indices.txt'}")
    ap.add_argument("--out", default=str(BENCH / "composite"))
    ap.add_argument("--concurrency", type=int, default=32)
    args = ap.parse_args()
    raw = Path(args.indices[1:]).read_text() if args.indices.startswith("@") else args.indices
    idxs = [int(x) for x in raw.replace("\n", ",").split(",") if x.strip()]
    idxs = [i for i in idxs if (RAW / str(i) / "win.png").exists()]
    data = {x["index"]: x for x in json.load(open(DATA))}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out / "calls.jsonl")
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.time()
    if args.stage in ("split", "all"):
        r = await stage_split(idxs, data, ledger, sem, out)
        print(f"[split] {sum(x['ok'] for x in r.values())}/{len(r)} ok  spend ${ledger.cost:.3f}  {time.time() - t0:.0f}s", flush=True)
    if args.stage in ("leak", "all"):
        r = await stage_leak(idxs, data, ledger, sem, out)
        print(f"[leak] {len(r)} pairs  spend ${ledger.cost:.3f}  {time.time() - t0:.0f}s", flush=True)
    if args.stage in ("sheet", "all"):
        stage_sheet(idxs, out)


if __name__ == "__main__":
    asyncio.run(main())
