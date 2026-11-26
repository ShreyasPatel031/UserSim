"""Watch a QA run in the private bucket and give every finding a correct screenshot with a pen mark, automatically.

    python -m mvp.client_qa.automark gs://.../client_qa/reframe/runs/4255 [--loop 60]

For each new finding (any shard's findings.jsonl):
  1. pick, from that shard's screenshots, the one that actually shows the problem (vision model on thumbnails);
  2. find the problem's region on it (box);
  3. verify on a second, independent call that the boxed region shows what the finding names;
only a verified finding gets a marked PNG (marked/auto/<key>.png). Anything else is listed as "needs screenshot",
never marked on a guess. Results: marked/auto/index.json, keyed by shard + finding text hash.
Nothing here types or reads credentials; screenshots stay in the private bucket and go only to Vertex in this project.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

from mvp.client_qa.annotate import annotate

MODEL = os.environ.get("AUTOMARK_MODEL", "gemini-2.5-flash")
USAGE = {"in": 0, "out": 0, "calls": 0}


def client():
    from google import genai
    return genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                        location=os.environ.get("VERTEX_LOCATION", "us-central1"))


def ask(cl, parts, schema_hint: str) -> dict:
    from google.genai import types
    r = cl.models.generate_content(model=MODEL, contents=parts + [schema_hint],
                                   config=types.GenerateContentConfig(response_mime_type="application/json",
                                                                      temperature=0))
    u = r.usage_metadata
    USAGE["calls"] += 1
    USAGE["in"] += u.prompt_token_count or 0
    USAGE["out"] += (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
    try:
        out = json.loads(r.text)
    except Exception:
        return {}
    if isinstance(out, list):  # the model sometimes returns the bare list
        out = {"boxes": out} if out and isinstance(out[0], dict) and "box_2d" in out[0] else (out[0] if out and isinstance(out[0], dict) else {})
    return out if isinstance(out, dict) else {}


def png_part(img: Image.Image, width: int):
    from google.genai import types
    im = img.convert("RGB")
    im = im.resize((width, int(im.height * width / im.width)))
    b = io.BytesIO(); im.save(b, "JPEG", quality=80)
    return types.Part.from_bytes(data=b.getvalue(), mime_type="image/jpeg")


def finding_text(f: dict) -> str:
    return f"{f.get('what', '')}" + (f" Expected: {f['expected']}" if f.get("expected") else "")


def locate(cl, shard_dir: Path, f: dict) -> dict:
    own = shard_dir / (f.get("shot") or "-")
    if own.is_file():  # try the screenshot the tester cited first; fall back to searching the shard
        r = locate_on(cl, own, f)
        if r["status"] == "marked":
            return r
    return locate_search(cl, shard_dir, f)


def locate_search(cl, shard_dir: Path, f: dict) -> dict:
    shots = sorted((shard_dir / "shots").glob("*.png"))
    if not shots:
        return {"status": "needs screenshot", "why": "no screenshots in shard"}
    # 1. choose the screenshot: thumbnails, numbered
    parts = []
    for i, s in enumerate(shots):
        parts += [f"Screenshot {i}:", png_part(Image.open(s), 260)]
    pick = ask(cl, parts, (
        f"A QA tester reported this problem in an iPhone app:\n\"{finding_text(f)}\"\n"
        "Which ONE screenshot above clearly shows the problem itself (the exact text, icon or screen the report names)? "
        "If none shows it, answer -1. Do not pick a screenshot that only shows a related or nearby screen.\n"
        'JSON: {"index": int, "reason": str}'))
    idx = pick.get("index", -1)
    if not isinstance(idx, int) or not 0 <= idx < len(shots):
        return {"status": "needs screenshot", "why": pick.get("reason", "not visible in any screenshot")}
    return locate_on(cl, shots[idx], f)


def locate_on(cl, shot: Path, f: dict) -> dict:
    img = Image.open(shot)
    # 2. box on the full-size image (Gemini box_2d: [ymin, xmin, ymax, xmax] on 0..1000)
    bx = ask(cl, [png_part(img, 900)], (
        f"This iPhone screenshot should show this reported problem:\n\"{finding_text(f)}\"\n"
        "Give 1 or 2 tight boxes around exactly the elements the problem is about (e.g. both inconsistent labels). "
        "If the problem is not visible here, return an empty list.\n"
        'JSON: {"boxes": [{"box_2d": [ymin, xmin, ymax, xmax], "label": str}]} with coordinates 0-1000.'))
    boxes = []
    for b in (bx.get("boxes") or [])[:2]:
        try:
            y1, x1, y2, x2 = [float(v) for v in b["box_2d"]]
        except Exception:
            continue
        W, H = img.size
        boxes.append((int(x1 / 1000 * W), int(y1 / 1000 * H), int(x2 / 1000 * W), int(y2 / 1000 * H)))
    if not boxes:
        return {"status": "needs screenshot", "why": "problem not visible on the chosen screenshot", "shot": shot.name}
    # 3. independent verification on the crops
    crops = []
    for b in boxes:
        pad = 40
        c = img.crop((max(0, b[0] - pad), max(0, b[1] - pad), min(img.width, b[2] + pad), min(img.height, b[3] + pad)))
        crops += [png_part(c, min(600, max(200, c.width)))]
    ok = ask(cl, crops, (
        f"These are crops of an app screen. A tester reported: \"{finding_text(f)}\"\n"
        "Do these crops show the specific thing the report is about (not just something nearby)? "
        'JSON: {"shows_it": true|false, "what_is_visible": str}'))
    if ok.get("shows_it") is not True:
        return {"status": "needs screenshot", "why": "verification failed: " + str(ok.get("what_is_visible", ""))[:200],
                "shot": shot.name}
    return {"status": "marked", "shot": shot.name, "boxes": boxes, "verified_as": ok.get("what_is_visible", "")}


HANG = ("froze", "freeze", "frozen", "hang", "hung", "spinner", "crash", "home screen", "was gone", "dropped", "loading")


def evidence_shot(shard: Path, f: dict, res: dict) -> Path | None:
    """For freezes, crashes and hangs there is no element to circle: the evidence is the screen at that moment.
    Use the tester's cited shot, else the chosen one. Static UI findings never fall back (they need the right screen)."""
    text = finding_text(f).lower()
    if not any(w in text for w in HANG):
        return None
    for name in (f.get("shot", "").replace("shots/", ""), res.get("shot") or ""):
        p = shard / "shots" / name
        if name and p.is_file():
            return p
    return None


def sh(*a):
    return subprocess.run(list(a), check=True, capture_output=True, text=True).stdout


def run_once(cl, root: str, work: Path) -> int:
    sh("gsutil", "-q", "-m", "rsync", "-r", "-x", r"marked/.*", root, str(work))
    idx_path = work / "marked" / "auto" / "index.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        idx = json.loads(sh("gsutil", "cat", f"{root}/marked/auto/index.json"))
    except Exception:
        idx = {}
    new = 0
    for fj in sorted(work.glob("*/findings.jsonl")):
        shard = fj.parent
        for line in fj.read_text().splitlines():
            if not line.strip():
                continue
            f = json.loads(line)
            if f.get("status") in ("blocked", "ok", "pass") or not f.get("what"):
                continue
            key = f"{shard.name}-" + hashlib.sha1(finding_text(f).encode()).hexdigest()[:10]
            if key in idx and idx[key].get("status") in ("marked", "screenshot"):
                continue
            if key in idx and idx[key].get("tries", 0) >= 3 and len(list((shard / "shots").glob("*.png"))) == idx[key].get("n_shots"):
                continue  # nothing new to look at
            res = locate(cl, shard, f)
            if res["status"] != "marked":
                ev = evidence_shot(shard, f, res)
                if ev:
                    res.update(status="screenshot", shot=ev.name, note="screen at the time; no single element to circle")
            res.update(shard=shard.name, finding=f.get("what"), item=f.get("item"),
                       tries=idx.get(key, {}).get("tries", 0) + 1, n_shots=len(list((shard / "shots").glob("*.png"))))
            if res["status"] in ("marked", "screenshot"):
                out = idx_path.parent / f"{key}.png"
                cap = finding_text(f) if res["status"] == "marked" else "[Screen at the time] " + finding_text(f)
                annotate(str(shard / "shots" / res["shot"]), str(out), res.get("boxes") or [], cap)
                res["png"] = f"marked/auto/{key}.png"
            idx[key] = res
            new += 1
    idx["_usage"] = {**USAGE, "model": MODEL, "updated": time.strftime("%H:%M:%SZ", time.gmtime())}
    idx_path.write_text(json.dumps(idx, indent=1))
    sh("gsutil", "-q", "-m", "rsync", "-r", str(idx_path.parent), f"{root}/marked/auto")
    return new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--loop", type=int, default=0)
    ap.add_argument("--work", default=tempfile.mkdtemp(prefix="automark_"))
    a = ap.parse_args()
    cl = client(); work = Path(a.work)
    while True:
        n = run_once(cl, a.root.rstrip("/"), work)
        print(time.strftime("%H:%M:%SZ", time.gmtime()), "processed", n, "usage", USAGE, flush=True)
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
