#!/usr/bin/env python3
"""Remove answer-leaking publisher annotations from the 33 leaky WiserUI-Bench pairs with an image-edit model, then re-check.

Inputs: images_recovered/{i}/{win,lose}.png (never modified). Outputs: images_fixed/{i}/{win,lose}.png (+ _raw/, meta.json).

Stages (every model call cached in images_fixed/calls.jsonl with cost; resumable; fully parallel; 429 -> next region):
  locate  gemini-2.5-flash boxes each annotation listed in EDITS (hand-written from fullset/sets.json + review of every image).
  edit    gemini-2.5-flash-image ("Nano Banana", Vertex) edits the region around the boxes (padded, never stretched, to the
          nearest supported aspect ratio). The output is registered onto the original (ECC affine) and merged back three
          ways: m2 changed pixels inside the boxes only, m3 + strong-change blobs touching them, m4 the whole edited region.
          Pixels outside the edited areas stay identical to the original. Pairs whose flagged "cues" are the page's own UI (NATIVE)
          are not edited (removing them would change the UI under test); their images are copied unchanged.
  check   (a) the SAME gemini-2.5-flash leak check as composites.py (LEAK prompt, thinking 0, crop wording) on both images;
          (b) a targeted flash check: are the specific annotations listed in EDITS still visible?;
          (c) a flash damage check: original vs edited, "is the UI content the same apart from the removed markers?".
  retry   images whose best merge fails (a), (b) or (c) get one more edit attempt with the failure fed back; the best
          candidate (attempt x merge) is kept.
  sheet   contact sheets original vs fixed.

Pair verdict: damaged (any edited image changed real UI) > still_leaked (leak check (a) or targeted check (b) finds a cue
on either image) > fixed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1]), str(HERE.parents[1] / "src")]
from composites import LEAK, Ledger, img_bytes, parse, shrink  # noqa: E402  (same leak prompt / helpers)

BENCH = Path(os.environ.get("WISERUI_BENCH", "/workspace/bench/wiserui"))
SRC = BENCH / "images_recovered"
OUT = BENCH / "images_fixed"
EDIT_MODEL, FLASH = "gemini-2.5-flash-image", "gemini-2.5-flash"
# $/1M tokens (Vertex list): flash-image input 0.30, text out 2.50, image out 30 (1290 tok = $0.039 / image)
PRICE = {FLASH: (0.30, 2.50, 2.50), EDIT_MODEL: (0.30, 2.50, 30.0)}
LOCS = {EDIT_MODEL: ["global", "us-central1", "us-east4", "us-west1", "europe-west4"],
        FLASH: ["us-central1", "us-east4", "us-west1", "europe-west4", "global", "asia-northeast1"]}
BUDGET = float(os.environ.get("LEAKFIX_BUDGET_USD", "4.3"))  # hard stop for the ledger (task cap $5; ~$0.20 of probes are outside it)
# merge variants (also the cache-key tag of their checks): m2 changed pixels inside the located boxes; m3 + strong-change
# blobs touching them; m4 the whole aligned edit of the edited region (checked only when m2 and m3 both fail)
MERGES = ("m2", "m3", "m4")
KV = "v2"  # cache-key version of the edit pipeline (v1 = whole-image edit, unmasked; kept in the ledger)
RATIOS = {"1:1": 1, "2:3": 3 / 2, "3:2": 2 / 3, "3:4": 4 / 3, "4:3": 3 / 4, "4:5": 5 / 4, "5:4": 4 / 5,
          "9:16": 16 / 9, "16:9": 9 / 16, "21:9": 9 / 21}  # value = h / w

# The VWO watermark (109, 111, 243) is on both images of each pair, so it is left alone: the edit model also refuses
# watermark removal (returns no image).
BADGE = ("the partial circular letter badge (a quarter/half circle, {c}) cut off at the very top-left corner, which is an "
         "A/B label from the article that published the test, not part of the app")
FRAME = "the thin colored frame/border line ({c}) along the image edges that the publisher drew around the screenshot"
# (index, side) -> annotations to remove. Written from fullset/sets.json (Gemini + manual flags) and a look at every image.
EDITS: dict[int, dict[str, list[str]]] = {
    104: {"win": ["the magenta/pink rectangle outline drawn around the contact e-mail and 'Jessica Rayberg' signature text"]},
    106: {"win": ["the green 'VARIATION' label with a trophy icon at the top-left",
                  "the green result banner with a trophy and white text ('Variation ... in reve... averag...') at the bottom-right"],
          "lose": ["the dark purple 'CONTROL' label at the top-left"]},
    107: {"win": ["the green 'VARIATION' label with a trophy icon at the top-left",
                  "the green result banner with a trophy and white text ('Variatio... increas...') at the bottom-right"]},
    109: {"lose": ["the red rectangle outline drawn around the 'Date of birth' field"]},
    110: {"lose": ["the red rectangle outline drawn around the input fields in the right-hand form panel"]},
    111: {"lose": ["the red rectangle outline drawn around the 'Date of birth' field"]},
    119: {"lose": ["the green 'VARIATION' label with a trophy icon at the bottom-left", "the thin red/pink annotation line at the right edge"],
          "win": ["the magenta rectangle outline around the row of payment icons", "the thin magenta arrow line coming down from the top to that box"]},
    137: {"lose": ["the white caption text across the very top ('Arlington Plastics Machinery's original inventory page'), restoring the plain gray page background there"]},
    152: {"win": ["every magenta/pink annotation rectangle (around the thumbnails, the buttons and the description text)",
                  "the magenta arrows pointing at them from the right"]},
    164: {"win": ["the red rectangle outlines around the award badges, around the row of three check-mark benefits, and around '1 mins only' at the bottom-left",
                  "the red label tags 'Award', 'USP' and 'Steps Time' (keep the award badges and the benefit text themselves)"]},
    166: {"win": ["the magenta rectangle outline around the intro paragraph with the PayPal logo",
                  "the thin magenta arrow line coming down from the top to that box"]},
    168: {"win": ["the red rectangle outline around the search suggestions panel ('TOP SEARCHES' / 'TOP CATEGORIES')",
                  "the small red marker at the right edge of that rectangle"]},
    176: {"win": ["the red rectangle outline around the row of product images", "the red arrow at the left pointing at it"],
          "lose": ["every red rectangle outline (around the right-hand column block and around the product-image row near the bottom)"]},
    202: {"lose": ["the green result box with a trophy and text 'The variation won with increase in the lead conversion rate by 16%' at the bottom, filling that area with the plain background"]},
    212: {"win": ["the red rectangle outline around the 'GET YOUR WHITE CARD ONLINE $50 / START NOW' banner",
                  "the red rectangle outline around the row of three round icons"]},
    215: {"win": ["the magenta rectangle outline around the product header block", "the small magenta arrow at the top"],
          "lose": ["the green result banner with a trophy and text 'The variation won with an improvement of 13.4% in purchases', filling that area with the plain background"]},
    221: {"win": ["the orange 'VARIATION 1' label tab cut off at the top-left", FRAME.format(c="orange")],
          "lose": ["the blue 'CONTROL' label tab cut off at the top-left", FRAME.format(c="blue")]},
    226: {"win": ["the pink rectangle outline around the 'More Like This' product row", "the small pink arrow at its right"]},
    243: {"win": ["the red arrows and red lines drawn over the page (pointing at text and the price, and the diagonal lines at the bottom)",
                  ],
          "lose": ["the red arrows and red lines drawn over the page (pointing at text and the price, and the diagonal lines at the bottom)"]},
    254: {"win": ["the magenta arrow and the black annotation text 'Added this' at the right", "the orange 'VARIATION' label tab cut off at the top-left",
                  FRAME.format(c="orange")],
          "lose": ["the blue 'CONTROL' label tab cut off at the top-left", FRAME.format(c="blue"),
                   "the orange frame fragment of another panel at the far right edge"]},
    260: {"win": ["the red rectangle outline around the e-mail signup form"]},
    261: {"win": ["the red rectangle outline around the pricing table",
                  "the small 'VWO' / 'Campaign 2' preview widget at the bottom-right (keep the plan's own 'MOST POPULAR' ribbon)"]},
    273: {"win": [BADGE.format(c="blue")]},
    277: {"lose": ["the yellow arrows and yellow highlight boxes drawn on the canvas", "the '+32%' result text at the bottom-right"]},
    279: {"win": [BADGE.format(c="blue")]},
    282: {"win": [BADGE.format(c="blue")], "lose": [BADGE.format(c="gray")]},
    284: {"win": [BADGE.format(c="blue, letter 'B' partly visible")]},
    295: {"win": [BADGE.format(c="blue, letter 'C'")], "lose": [BADGE.format(c="gray, letter 'A'")]},
    297: {"win": [BADGE.format(c="blue")]},
}
# Flagged by the Gemini leak check, but the flagged cue is the page's own UI (pricing 'Best value' / 'Most popular'
# badges, Uber 'Cheaper' / 'New' tags, a '-50%' discount corner): the LEAK prompt itself says such content is not a cue.
NATIVE = {124: "'BEST VALUE' ribbon (VIP) / 'Best value' starburst (Extreme): Paltalk pricing UI",
          274: "'Cheaper' / 'New' ride tags: Uber app UI",
          278: "'MOST POPULAR' plan header / 'GitHub is now free for teams' banner: GitHub pricing UI",
          281: "'-50%' corner on the 12-month plan: Runtastic pricing UI"}

EDIT_PROMPT = """Edit this screenshot of a {platform} page. The screenshot was published in an article about an A/B test, and
the publisher drew annotations on top of it. Remove ONLY these publisher annotations:
{items}

Where an annotation covered the page, restore what the page shows underneath (continue the surrounding background,
text and UI naturally). Where it sits in an empty margin, fill with the surrounding background colour.
Keep EVERYTHING else exactly as it is: all text, numbers, prices, buttons, icons, images, colours, layout, element sizes
and positions, and the page's own badges and labels. Do not crop, zoom, shift, re-layout, sharpen, restyle or add anything.
The light border area around the screenshot is padding: keep it plain.{extra}"""

TARGET = """This screenshot of a web/app page was edited to remove annotations added by an A/B-test publisher. Before the edit it
contained these annotations:
{items}

Look carefully at the image now. For each annotation, is it still visible, fully or partly (including leftover
fragments, outlines, arrow pieces or ghost text)? Ignore the page's own UI elements.
Return JSON only: {{"remaining": ["short description of each annotation still visible"], "all_removed": true/false}}"""

DAMAGE = """This picture shows two screenshots separated by a magenta bar, each under a black caption. IMAGE 1 is the ORIGINAL
screenshot. IMAGE 2 is an EDITED copy in which only these publisher annotations were supposed
to be removed:
{items}

Compare them carefully. Apart from removing those annotations (and restoring the background behind them), is the UI
content the same: same text and numbers, prices, buttons, icons, product images, colours, layout and elements? Ignore
slight blur/compression and tiny pixel noise. Report any OTHER change (added, removed, moved, altered or garbled
element or text).
Return JSON only: {{"same_ui": true/false, "other_changes": ["short description"], "severity": "none|minor|major"}}"""


def _parts(contents):
    from google.genai import types

    return [types.Part.from_bytes(data=c, mime_type="image/png") if isinstance(c, bytes) else types.Part.from_text(text=c)
            for c in contents]


def _gen(model: str, contents: list, key: str, *, thinking=0, max_tokens=1024, aspect=None):
    """One call, 429/5xx -> next region (start region spread by key hash). Returns (text, image_bytes, tin, tout_txt, tout_img)."""
    from google.genai import types

    from mvp.e2e_ui_run import _gemini_client_at

    if model == EDIT_MODEL:
        cfg = types.GenerateContentConfig(response_modalities=["IMAGE"], temperature=0.0,
                                          image_config=types.ImageConfig(aspect_ratio=aspect))
    else:
        cfg = types.GenerateContentConfig(
            temperature=0.0, max_output_tokens=max_tokens, response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=thinking),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH)
    locs = LOCS[model]
    start = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(locs)
    last = None
    for attempt in range(15):
        loc = locs[(start + attempt) % len(locs)]
        try:
            r = _gemini_client_at(loc).models.generate_content(model=model, contents=_parts(contents), config=cfg)
            um = r.usage_metadata
            tin = int(um.prompt_token_count or 0)
            tout_img = sum(int(d.token_count or 0) for d in (um.candidates_tokens_details or [])
                           if "IMAGE" in str(d.modality))
            tout = int(um.candidates_token_count or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
            img, text = None, ""
            for c in (r.candidates or [])[:1]:
                for p in (c.content.parts if c.content else None) or []:
                    if p.inline_data and p.inline_data.data:
                        img = p.inline_data.data
                    elif p.text:
                        text += p.text
            if model == EDIT_MODEL and img is None:
                raise RuntimeError(f"no image returned ({(text or str(r.candidates[0].finish_reason if r.candidates else ''))[:120]})")
            return text.strip(), img, tin, tout - tout_img, tout_img, loc
        except Exception as exc:  # noqa: BLE001
            last = exc
            code = getattr(exc, "code", None)
            if isinstance(code, int) and 400 <= code < 500 and code not in (429, 404):
                break
            time.sleep(min(15, 0.5 * 2 ** (attempt // len(locs))))
    raise RuntimeError(f"{model} failed: {last!r}")


class Runner:
    def __init__(self, ledger: Ledger, conc: int):
        self.ledger, self.sem, self.reserved = ledger, asyncio.Semaphore(conc), 0.0
        self.spent = sum(json.loads(x).get("cost_usd", 0.0) for x in ledger.path.open()) if ledger.path.exists() else 0.0

    async def call(self, key, model, contents, **kw):
        hit = self.ledger.cache.get(key)
        if hit and not hit.get("error"):
            return hit
        est = 0.045 if model == EDIT_MODEL else 0.006
        async with self.sem:
            if self.spent + self.reserved + est > BUDGET:
                return {"key": key, "text": "", "error": f"budget stop (spent ${self.spent:.3f} + in flight)"}
            self.reserved += est
            t0 = time.time()
            try:
                text, img, tin, tt, ti, loc = await asyncio.to_thread(_gen, model, contents, key, **kw)
                err = None
            except Exception as exc:  # noqa: BLE001
                text, img, tin, tt, ti, loc, err = "", None, 0, 0, 0, None, repr(exc)[:300]
            self.reserved -= est
        pin, pt, pi = PRICE[model]
        rec = {"key": key, "model": model, "text": text, "tokens_in": tin, "tokens_out": tt, "tokens_img_out": ti,
               "cost_usd": tin / 1e6 * pin + tt / 1e6 * pt + ti / 1e6 * pi, "secs": round(time.time() - t0, 1),
               "loc": loc, "error": err}
        if img is not None:
            p = OUT / "_calls" / (hashlib.md5(key.encode()).hexdigest() + ".png")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(img)
            rec["image"] = str(p)
        self.spent += rec["cost_usd"]
        self.ledger.put(rec)
        return rec


def pad_to_ratio(im):
    """Pad (never stretch) to the nearest supported aspect ratio. Returns padded image, ratio name, paste box."""
    import numpy as np
    from PIL import Image

    w, h = im.size
    r = h / w
    name = min(RATIOS, key=lambda k: abs(np.log(RATIOS[k] / r)))
    R = RATIOS[name]
    W, H = (w, round(w * R)) if R >= r else (round(h / R), h)
    a = np.asarray(im)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = tuple(int(v) for v in np.median(border, axis=0))
    out = Image.new("RGB", (W, H), bg)
    x0, y0 = (W - w) // 2, (H - h) // 2
    out.paste(im, (x0, y0))
    return out, name, (x0, y0, x0 + w, y0 + h)


def merge(orig, raw_full, box, allow=None, grow=True, whole_region=False):
    """Scale the edit back, crop the screenshot area, paste only changed pixels onto the original (feathered)."""
    import numpy as np
    from PIL import Image, ImageFilter

    ed = raw_full.convert("RGB").crop(box).resize(orig.size, Image.LANCZOS)  # raw_full is already at padded size
    ed, warp = align(orig.convert("RGB"), ed)
    if whole_region:
        return ed, 1.0, True, warp
    s = 512 / max(orig.size)
    lo = (max(1, round(orig.width * s)), max(1, round(orig.height * s)))
    a = orig.convert("L").resize(lo, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2))
    b = ed.convert("L").resize(lo, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.2))
    ca = np.asarray(orig.convert("RGB").resize(lo, Image.BILINEAR), float)
    cb = np.asarray(ed.resize(lo, Image.BILINEAR), float)
    d = np.maximum(np.abs(np.asarray(a, float) - np.asarray(b, float)), np.abs(ca - cb).max(2))
    m = Image.fromarray(((d > 28) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(7))
    frac = float(np.asarray(m).mean() / 255)
    if allow is not None:  # only annotation areas may change; everything else stays pixel-identical
        # full-ish resolution colour diff (thin 1-2 px annotation lines vanish in a blurred low-res diff)
        s2 = min(1.0, 1400 / max(orig.size))
        hi = (max(1, round(orig.width * s2)), max(1, round(orig.height * s2)))
        dh = np.abs(np.asarray(orig.convert("RGB").resize(hi, Image.BILINEAR), np.int16)
                    - np.asarray(ed.resize(hi, Image.BILINEAR), np.int16)).max(2)
        mh = Image.fromarray(((dh > 20) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(9))
        # Flash boxes are loose: also take every STRONG-change blob (e.g. the rest of a removed outline) touching them
        import cv2

        strong = ((dh > 60) * 255).astype("uint8")
        strong = cv2.dilate(strong, np.ones((7, 7), np.uint8))
        al_hi = np.asarray(allow.resize(hi, Image.NEAREST)) > 0
        n, lab = cv2.connectedComponents(strong, connectivity=8)
        touch = np.unique(lab[(strong > 0) & al_hi])
        blobs = np.isin(lab, touch[touch > 0]) if grow else np.zeros_like(al_hi)
        mh = np.asarray(mh.resize(hi, Image.NEAREST)) > 0
        mk = ((mh & al_hi) | blobs).astype("uint8") * 255
        m = Image.fromarray(mk).resize(orig.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.5))
        return Image.composite(ed, orig.convert("RGB"), m), frac, False, warp
    if frac > 0.35:  # the model changed most of the image: take it whole
        return ed, frac, True, warp
    m = m.resize(orig.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(3))
    return Image.composite(ed, orig.convert("RGB"), m), frac, False, warp


def align(orig, ed):
    """The edit model re-renders the page with small shifts/scales: register it onto the original (ECC, affine)."""
    import cv2
    import numpy as np
    from PIL import Image

    s = min(1.0, 900 / max(orig.size))
    lo = (max(8, round(orig.width * s)), max(8, round(orig.height * s)))
    a = np.asarray(orig.convert("L").resize(lo, Image.BILINEAR), np.float32) / 255
    b = np.asarray(ed.convert("L").resize(lo, Image.BILINEAR), np.float32) / 255
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), None, 5)
    except cv2.error:
        return ed, None
    lin, t = warp[:, :2], warp[:, 2]
    if np.abs(lin - np.eye(2)).max() > 0.08 or np.abs(t).max() > 0.06 * max(lo):
        return ed, None
    full = warp.copy()
    full[:, 2] /= s
    out = cv2.warpAffine(np.asarray(ed), full, orig.size, flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(out), [round(float(x), 4) for x in full.ravel()]


def platform(i, data):
    return "mobile app" if data.get(i, {}).get("web_mobile") == "mobile" else "web"


def items_text(items):
    return "\n".join(f"- {x}" for x in items)


LOCATE = """This screenshot of a web/app page has annotations drawn on top of it by the publisher of an A/B-test article.
Find each of these annotations:
{items}

Give a tight box for every visible piece (if one annotation has several separate pieces, e.g. a rectangle outline and an
arrow, or two labels, give one entry per piece). kind = "outline" for a hollow rectangle/circle/frame drawn AROUND page
content (the content inside is the page itself), "solid" for everything else (labels, badges, banners, arrows, lines,
text, watermarks). Box format [ymin, xmin, ymax, xmax] normalised to 0-1000. Return JSON only:
{{"annotations": [{{"what": "short", "kind": "outline|solid", "box_2d": [ymin, xmin, ymax, xmax]}}]}}"""


def allowed_mask(size, anns):
    """Pixels the edit may change: solid pieces (+margin) and a band along each outline's border. None = anywhere."""
    from PIL import Image, ImageDraw

    if not anns:
        return None
    W, H = size
    m = Image.new("L", size, 0)
    dr = ImageDraw.Draw(m)
    mg = max(12, round(0.025 * max(W, H)))
    for a in anns:
        y0, x0, y1, x1 = a["box_2d"]
        x0, x1 = sorted((x0 / 1000 * W, x1 / 1000 * W))
        y0, y1 = sorted((y0 / 1000 * H, y1 / 1000 * H))
        if a.get("kind") == "outline":
            bw = max(14, round(0.025 * max(W, H)))
            dr.rectangle([x0 - bw, y0 - bw, x1 + bw, y1 + bw], fill=255)
            if x1 - x0 > 2 * bw and y1 - y0 > 2 * bw:
                dr.rectangle([x0 + bw, y0 + bw, x1 - bw, y1 - bw], fill=0)
        else:
            dr.rectangle([x0 - mg, y0 - mg, x1 + mg, y1 + mg], fill=255)
    return m


async def locate(run, i, side, items):
    from PIL import Image

    im = shrink(Image.open(SRC / str(i) / f"{side}.png"))
    rec = await run.call(f"{i}|locate|{side}", FLASH, [LOCATE.format(items=items_text(items)), img_bytes(im)],
                         thinking=512, max_tokens=3000)
    j = parse(rec.get("text", "")) or {}
    out = []
    for a in (j.get("annotations") if isinstance(j, dict) else j) or []:
        bx = a.get("box_2d") if isinstance(a, dict) else None
        if isinstance(bx, list) and len(bx) == 4 and all(isinstance(v, (int, float)) for v in bx):
            out.append({"what": a.get("what"), "kind": a.get("kind", "solid"), "box_2d": [float(v) for v in bx]})
    return out


async def edit_one(run: Runner, i, side, items, data, attempt, extra="", anns=None):
    import numpy as np
    from PIL import Image

    orig = Image.open(SRC / str(i) / f"{side}.png").convert("RGB")
    allow = allowed_mask(orig.size, anns)
    # edit only the region around the annotations when it is small enough (higher effective resolution, less re-rendering)
    region = (0, 0, orig.width, orig.height)
    if allow is not None and allow.getbbox():
        x0, y0, x1, y1 = allow.getbbox()
        mx, my = max(64, round(0.12 * orig.width)), max(64, round(0.12 * orig.height))
        r = (max(0, x0 - mx), max(0, y0 - my), min(orig.width, x1 + mx), min(orig.height, y1 + my))
        if (r[2] - r[0]) * (r[3] - r[1]) < 0.6 * orig.width * orig.height:
            region = r
    sub = orig.crop(region)
    padded, ratio, box = pad_to_ratio(sub)
    send = padded.copy()
    send.thumbnail((2048, 2048))
    what = "a cropped part of a screenshot" if region != (0, 0, orig.width, orig.height) else "a screenshot"
    prompt = EDIT_PROMPT.format(platform=platform(i, data), items=items_text(items), extra=extra).replace(
        "Edit this screenshot", f"Edit this image ({what})")
    rec = await run.call(f"{i}|edit|{side}|a{attempt}|{KV}", EDIT_MODEL, [img_bytes(send), prompt], aspect=ratio)
    if rec.get("error") or not rec.get("image"):
        return {"attempt": attempt, "error": rec.get("error") or "no image"}
    raw = Image.open(rec["image"])
    sub_allow = allow.crop(region) if allow is not None else None
    d = OUT / str(i) / "_raw"
    d.mkdir(parents=True, exist_ok=True)
    raw.save(d / f"{side}.a{attempt}.png")
    paths = {}
    for mode in MERGES:
        fixed_sub, frac, whole, warp = merge_padded(sub, raw, padded.size, box, sub_allow, grow=(mode == "m3"),
                                                    whole_region=(mode == "m4"))
        fixed = orig.copy()
        fixed.paste(fixed_sub, region[:2])
        paths[mode] = str(d / f"{side}.a{attempt}.{mode}.png")
        fixed.save(paths[mode])
    return {"attempt": attempt, "region": region, "ratio": ratio, "raw_size": raw.size, "changed_frac": round(frac, 4),
            "whole": whole, "warp": warp, "n_boxes": len(anns or []), "paths": paths, "prompt_extra": extra}


def merge_padded(orig, raw, padded_size, box, allow=None, grow=True, whole_region=False):
    from PIL import Image

    full = raw.convert("RGB").resize(padded_size, Image.LANCZOS)
    return merge(orig, full, box, allow, grow, whole_region)


async def check_image(run: Runner, i, side, path, tag, items, cv=None):
    """(a) same leak check, (b) targeted, (c) damage. items=None for unedited images (only (a))."""
    from PIL import Image

    im = shrink(Image.open(path))
    what = "This is ONE cropped panel that should show a single version of the page."
    CV = cv or MERGES[-1]
    jobs = [run.call(f"{i}|leak|{side}|{tag}|{CV}", FLASH, [LEAK.format(what=what), img_bytes(im)], thinking=0, max_tokens=1024)]
    if items:
        jobs.append(run.call(f"{i}|target|{side}|{tag}|{CV}", FLASH, [TARGET.format(items=items_text(items)), img_bytes(im)],
                             thinking=0, max_tokens=512))
        both = shrink(stitch(Image.open(SRC / str(i) / f"{side}.png"), Image.open(path)))
        jobs.append(run.call(f"{i}|damage|{side}|{tag}|{CV}", FLASH, [DAMAGE.format(items=items_text(items)), img_bytes(both)],
                             thinking=1024, max_tokens=2048))
    recs = await asyncio.gather(*jobs)
    r = {"leak": parse(recs[0]["text"]) or {"error": recs[0].get("error") or recs[0]["text"][:200]}}
    if items:
        r["target"] = parse(recs[1]["text"]) or {"error": recs[1].get("error") or recs[1]["text"][:200]}
        r["damage"] = parse(recs[2]["text"]) or {"error": recs[2].get("error") or recs[2]["text"][:200]}
    return r


def stitch(a, b):
    """Original and edited side by side (or stacked for wide images), labelled, as ONE image."""
    from PIL import Image, ImageDraw

    a, b = a.convert("RGB"), b.convert("RGB").resize(a.size)
    w, h = a.size
    side = h >= w
    gap, lab = 24, 40
    W, H = (2 * w + gap, h + lab) if side else (w, 2 * (h + lab) + gap)
    out = Image.new("RGB", (W, H), (255, 0, 255))
    dr = ImageDraw.Draw(out)
    for k, (im, t) in enumerate(((a, "IMAGE 1: ORIGINAL"), (b, "IMAGE 2: EDITED"))):
        x, y = (k * (w + gap), 0) if side else (0, k * (h + lab + gap))
        dr.rectangle([x, y, x + w, y + lab], fill="black")
        dr.text((x + 8, y + 8), t, fill="white", font_size=24)
        out.paste(im, (x, y + lab))
    return out


def img_verdict(c):
    lk = bool(c["leak"].get("leak")) if "error" not in c["leak"] else None
    tg = c.get("target")
    tleft = None if tg is None else (not tg.get("all_removed", False) or bool(tg.get("remaining")))
    dm = c.get("damage")
    dmg = None if dm is None else (True if "error" in dm else (dm.get("same_ui") is False and dm.get("severity") != "none"))
    return {"leak_check": lk, "target_left": tleft, "damaged": dmg}


def score(v):  # lower is better
    return (2 if v["damaged"] else 0) + (1 if v["leak_check"] or v["target_left"] else 0)


async def process_pair(run: Runner, i, data, max_attempts):
    d = OUT / str(i)
    d.mkdir(parents=True, exist_ok=True)
    meta = {"index": i, "sides": {}}
    edits = EDITS.get(i, {})
    if i in NATIVE:
        meta["native_note"] = NATIVE[i]

    async def side_job(side):
        src = SRC / str(i) / f"{side}.png"
        items = edits.get(side)
        if not items:
            shutil.copyfile(src, d / f"{side}.png")
            c = await check_image(run, i, side, src, "orig", None)
            return side, {"edited": False, "check": c, "verdict": img_verdict(c)}
        tries = []
        extra = ""
        anns = await locate(run, i, side, items)
        for a in range(1, max_attempts + 1):
            e = await edit_one(run, i, side, items, data, a, extra, anns)
            if e.get("error"):
                tries.append(e)
                continue
            cands = []
            for mode, pth in e["paths"].items():
                if mode == "m4" and min(score(t["verdict"]) for t in cands) == 0:
                    continue
                c = await check_image(run, i, side, pth, f"a{a}", items, cv=mode)
                cands.append({"mode": mode, "path": pth, "check": c, "verdict": img_verdict(c)})
            bc = min(cands, key=lambda t: score(t["verdict"]))  # ties: m2 (fewer changed pixels) first
            c, v = bc["check"], bc["verdict"]
            tries.append({**e, "cands": cands, "mode": bc["mode"], "path": bc["path"], "check": c, "verdict": v})
            if score(v) == 0:
                break
            fb = []
            if v["target_left"]:
                fb.append("Your previous attempt left these annotations (or fragments) visible, remove them completely: "
                          + "; ".join(map(str, c["target"].get("remaining") or ["see list"])))
            if v["leak_check"]:
                fb.append("A reviewer still saw these cues: " + "; ".join(
                    f"{x.get('type')} '{x.get('text') or ''}' @ {x.get('where')}" for x in c["leak"].get("cues", [])
                    if isinstance(x, dict)) + " (remove them only if they are publisher annotations, not page UI)")
            if v["damaged"]:
                fb.append("Your previous attempt also changed the page itself, do NOT do this again: "
                          + "; ".join(map(str, c["damage"].get("other_changes") or [])))
            extra = "\n\n" + "\n".join(fb)
        ok = [t for t in tries if "verdict" in t]
        if not ok:
            shutil.copyfile(src, d / f"{side}.png")
            return side, {"edited": False, "edit_failed": True, "tries": tries, "verdict": {"leak_check": None, "target_left": True, "damaged": None}}
        best = min(ok, key=lambda t: (score(t["verdict"]), t["attempt"]))
        shutil.copyfile(best["path"], d / f"{side}.png")
        return side, {"edited": True, "items": items, "boxes": anns, "best_attempt": best["attempt"], "best_merge": best["mode"], "tries": tries,
                      "verdict": best["verdict"], "first_verdict": ok[0]["verdict"] if ok[0]["attempt"] == 1 else None}

    for side, r in await asyncio.gather(*(side_job(s) for s in ("win", "lose"))):
        meta["sides"][side] = r

    def pair_class(key):
        vs = [meta["sides"][s].get(key) for s in ("win", "lose")]
        vs = [v if v is not None else meta["sides"][s]["verdict"] for v, s in zip(vs, ("win", "lose"))]
        if any(v.get("damaged") for v in vs):
            return "damaged"
        if any(v.get("leak_check") or v.get("target_left") for v in vs):
            return "still_leaked"
        return "fixed"

    meta["class"] = pair_class("verdict")
    meta["class_first_attempt"] = pair_class("first_verdict")
    meta["class_same_check_only"] = ("damaged" if any(meta["sides"][s]["verdict"].get("damaged") for s in ("win", "lose"))
                                     else "still_leaked" if any(meta["sides"][s]["verdict"].get("leak_check") for s in ("win", "lose"))
                                     else "fixed")
    (d / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    return meta


EXAMPLES = [106, 202, 215, 273, 104, 243]  # contact_examples.png: four fixed pairs, one still leaked, one damaged


def sheets(idxs, results, per=4, name=None):
    from PIL import Image, ImageDraw

    W, H = 420, 470
    for s in range(0, len(idxs), per):
        ch = idxs[s:s + per]
        sheet = Image.new("RGB", (W * 4, H * len(ch)), "white")
        dr = ImageDraw.Draw(sheet)
        for k, i in enumerate(ch):
            m = results[i]
            for j, (side, kind) in enumerate([("win", "orig"), ("win", "fixed"), ("lose", "orig"), ("lose", "fixed")]):
                p = (SRC if kind == "orig" else OUT) / str(i) / f"{side}.png"
                im = Image.open(p).convert("RGB")
                im.thumbnail((W - 10, H - 34))
                x, y = j * W, k * H
                sheet.paste(im, (x + 5, y + 30))
                dr.rectangle([x, y, x + W - 1, y + H - 1], outline="gray")
                ed = m["sides"][side].get("edited")
                lab = f"{i} {side} {kind}" + ("" if kind == "orig" else (" EDITED" if ed else " (unchanged)"))
                if kind == "fixed":
                    lab += f"  pair: {m['class']}"
                dr.text((x + 5, y + 4), lab, fill="red" if side == "win" else "blue")
                if kind == "fixed" and ed:
                    v = m["sides"][side]["verdict"]
                    dr.text((x + 5, y + 16), f"leak={v['leak_check']} left={v['target_left']} dmg={v['damaged']}", fill="black")
        sheet.save(OUT / (name or f"contact_{s // per}.png"))


async def main():
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(128))
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--sheets-only", action="store_true", help="redraw contact sheets from results.jsonl (no model calls)")
    args = ap.parse_args()
    if args.sheets_only:
        results = {m["index"]: m for m in map(json.loads, (OUT / "results.jsonl").open())}
        sheets(sorted(results), results)
        sheets([i for i in EXAMPLES if i in results], results, per=len(EXAMPLES), name="contact_examples.png")
        return
    sets = json.load(open(HERE / "fullset" / "sets.json"))
    allidx = sorted({int(k) for k in sets["gemini_leaky"]} | {int(k) for k in sets["manual_leak"]})
    idxs = [int(x) for x in args.indices.split(",") if x.strip()] or allidx
    assert set(EDITS) | set(NATIVE) == set(allidx), sorted(set(allidx) ^ (set(EDITS) | set(NATIVE)))
    data = {x["index"]: x for x in json.load(open(BENCH / "repo" / "WiserUI_Bench.json"))}
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(OUT / "calls.jsonl")
    run = Runner(ledger, args.concurrency)
    t0 = time.time()
    res = await asyncio.gather(*(process_pair(run, i, data, args.attempts) for i in idxs))
    results = {m["index"]: m for m in res}
    with (OUT / "results.jsonl").open("w") as f:
        for i in sorted(results):
            f.write(json.dumps(results[i], default=str) + "\n")
    from collections import Counter

    for k in ("class", "class_first_attempt", "class_same_check_only"):
        print(k, dict(Counter(m[k] for m in res)))
    n_edit = sum(len(t) for m in res for s in m["sides"].values() for t in [s.get("tries", [])])
    print(f"edit attempts {n_edit}  total spend (all ledger lines) ${run.spent:.3f}  {time.time() - t0:.0f}s", flush=True)
    if not args.no_sheets:
        sheets(sorted(results), results)
        sheets([i for i in EXAMPLES if i in results], results, per=len(EXAMPLES), name="contact_examples.png")


if __name__ == "__main__":
    asyncio.run(main())
