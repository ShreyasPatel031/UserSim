#!/usr/bin/env python3
"""Fetch + clean WiserUI-Bench images using the benchmark repo's own functions.

- download: dataset/download_images.py::download_image (same headers/referers, VWO /tr: strip)
- marker removal: dataset/image_preprocess.py::process_image (purple GoodUI markers, inpainting)

Raw images -> $BENCH/images/{idx}/{win,lose}.png (same layout as the repo script)
Clean images -> $BENCH/images_clean/{idx}/{win,lose}.png (never overwrites raw)

Data stays under /workspace/bench/wiserui (CC BY-NC-SA, internal research only). Nothing here is committed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image

BENCH = Path("/workspace/bench/wiserui")
REPO = BENCH / "repo"
sys.path.insert(0, str(REPO / "dataset"))
sys.path.insert(0, str(BENCH / "pydeps"))  # opencv-python-headless lives here, not in the shared venv

from download_images import download_image  # noqa: E402
from image_preprocess import process_image  # noqa: E402


def usable(item: dict) -> bool:
    return bool(item.get("win_url") and item.get("lose_url") and item["win_url"] != item.get("source"))


def valid(p: Path) -> bool:
    if not p.exists():
        return False
    try:
        with Image.open(p) as im:
            im.load()
        return True
    except Exception:
        p.unlink(missing_ok=True)
        return False


def fetch_one(item: dict) -> tuple[int, bool]:
    idx = item["index"]
    sess = requests.Session()
    ok = True
    for label in ("win", "lose"):
        raw = BENCH / "images" / str(idx) / f"{label}.png"
        clean = BENCH / "images_clean" / str(idx) / f"{label}.png"
        if not valid(raw):
            for attempt in range(3):
                if download_image(item[f"{label}_url"], raw, sess):
                    break
                time.sleep(2 * (attempt + 1))
            time.sleep(0.5)
        if not valid(raw):
            ok = False
            continue
        if not valid(clean):
            clean.parent.mkdir(parents=True, exist_ok=True)
            ok = process_image(str(raw), str(clean)) and ok
    return idx, ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="", help="comma list; default all")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    data = json.load(open(REPO / "WiserUI_Bench.json"))
    want = {int(i) for i in args.indices.split(",") if i.strip()} if args.indices else None
    items = [x for x in data if usable(x) and (want is None or x["index"] in want)]
    bad = []
    with ThreadPoolExecutor(args.workers) as ex:
        for idx, ok in ex.map(fetch_one, items):
            if not ok:
                bad.append(idx)
    print(f"done: {len(items) - len(bad)}/{len(items)} pairs ready; failed={bad}")


if __name__ == "__main__":
    main()
