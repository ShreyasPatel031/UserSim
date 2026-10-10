#!/usr/bin/env python3
"""Answer-leak audit of the final WiserUI-Bench images (every pair, both images).

Same LEAK prompt and model settings as bench/wiserui/composites.py on grokbot/pairwise-judge (gemini-2.5-flash,
thinking 0, temperature 0, HIGH media resolution, one image per call), so results compare with its composite_leak.jsonl.
Calls are cached in $WISERUI_CLEAN/audit_calls.jsonl keyed by image hash, so an unchanged image is never re-checked.

    python bench/wiserui_clean/audit.py            # writes $WISERUI_CLEAN/audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

ROOT = Path(os.environ.get("WISERUI_CLEAN", "/workspace/bench/wiserui_clean"))
MODEL = "gemini-2.5-flash"
PRICE = (0.30, 2.50)  # $/M tokens in, out
LOCS = [os.environ.get("VERTEX_LOCATION", "us-central1"), "us-east4", "us-west1", "europe-west4", "global"]

LEAK = """You are auditing an image used in a benchmark where a model must guess which version of a web/app page won
an A/B test. This is ONE image that should show a single version of the page.

Does this image contain ANY cue that reveals or hints which version won or which is the control/original vs the
variation/new version? Cues include: labels like CONTROL, VARIATION, ORIGINAL, NEW, VERSION A/B, "A"/"B" badges,
"winner", check marks or trophies, crowns, lift or result percentages ("+25%", "increase"), text like "outperformed",
"won", "result", annotation arrows / circles / highlight boxes added by the test publisher to point at the change or the
winner, or captions describing the change. Ordinary UI content of the page itself (its own buttons, prices, product
discount badges) is NOT a cue.

Also say whether the image is a complete, usable screenshot of ONE page version (not cut off mid-way badly, not two
versions, not blank).

Return JSON only:
{"leak": true/false, "cues": [{"type": "label|ab_badge|trophy|lift_percent|result_text|arrow_or_highlight|caption|other", "text": "the text if any", "where": "short location"}],
  "single_full_ui": true/false, "ui_notes": "short"}"""

_clients: dict = {}


def client(loc: str):
    if loc not in _clients:
        from google import genai

        _clients[loc] = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=loc)
    return _clients[loc]


def png(path: Path, max_side: int = 3072) -> bytes:
    from PIL import Image

    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    b = BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def check(data: bytes) -> dict:
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.0, max_output_tokens=1024, response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH)
    parts = [types.Part.from_text(text=LEAK), types.Part.from_bytes(data=data, mime_type="image/png")]
    last = None
    for attempt in range(10):
        try:
            r = client(LOCS[attempt % len(LOCS)]).models.generate_content(model=MODEL, contents=parts, config=cfg)
            um = r.usage_metadata
            tin, tout = int(um.prompt_token_count or 0), int(um.candidates_token_count or 0)
            m = re.search(r"\{.*\}", r.text or "", re.S)
            return {"result": json.loads(m.group(0)), "tokens_in": tin, "tokens_out": tout,
                    "cost_usd": tin / 1e6 * PRICE[0] + tout / 1e6 * PRICE[1]}
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(20, 2 ** (attempt // len(LOCS))))
    return {"error": repr(last)[:300]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=str(ROOT / "final"))
    ap.add_argument("--workers", type=int, default=24)
    args = ap.parse_args()
    images = Path(args.images)
    ledger = ROOT / "audit_calls.jsonl"
    cache = {}
    if ledger.exists():
        for line in ledger.open():
            r = json.loads(line)
            if "result" in r:
                cache[r["key"]] = r
    jobs = []
    for d in sorted(images.iterdir(), key=lambda p: int(p.name)):
        for lab in ("win", "lose"):
            p = d / f"{lab}.png"
            data = png(p)
            jobs.append((int(d.name), lab, hashlib.sha256(data).hexdigest()[:20], data))

    def run(job):
        idx, lab, key, data = job
        if key in cache:
            return idx, lab, cache[key]
        r = {"key": key, **check(data)}
        if "result" in r:
            with ledger.open("a") as f:
                f.write(json.dumps(r) + "\n")
        return idx, lab, r

    out: dict = {}
    new_cost = 0.0
    with ThreadPoolExecutor(args.workers) as ex:
        for idx, lab, r in ex.map(run, jobs):
            out.setdefault(str(idx), {})[lab] = r.get("result") or {"error": r.get("error")}
            if r["key"] not in cache:
                new_cost += r.get("cost_usd", 0.0)
    (ROOT / "audit.json").write_text(json.dumps(out, indent=1))
    leaky = sorted(int(i) for i, v in out.items() if any((v[lab] or {}).get("leak") for lab in v))
    errs = sorted(int(i) for i, v in out.items() if any("error" in (v[lab] or {}) for lab in v))
    print(f"{len(out)} pairs, flagged {len(leaky)}: {leaky}\nerrors: {errs}\nnew spend ${new_cost:.3f}")


if __name__ == "__main__":
    main()
