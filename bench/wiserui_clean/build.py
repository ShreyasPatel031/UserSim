#!/usr/bin/env python3
"""Build the final clean WiserUI-Bench image set: all 300 pairs, nothing dropped.

The benchmark authors do not redistribute images (dataset/DATA_POLICY.md); they publish source URLs, a download
script, and an inpainting script for GoodUI markers, and leave composites / leftover annotations to the user. This
script does that last part reproducibly. Images stay outside git (CC BY-NC-SA, no redistribution).

Per pair, in order:
  1. URL_OVERRIDES: dataset URLs that are dead or point at the wrong image (see FIXES.md for the evidence).
  2. Download with the repo's dataset/download_images.py::download_image (same headers, VWO /tr: stripping).
  3. Source-specific cleaning:
       goodui.org   repo image_preprocess.process_image, then markers.remove_markers (numbered markers it misses)
       composites   (win_url == lose_url) crop the two panels with the boxes in composite_split.jsonl
                    (gemini-2.5-pro split + manual PAIR_HINTS from grokbot/pairwise-judge; deterministic here);
                    abtest.design composites first get their A/B badges painted out (markers.remove_ab_badges)
       vwo / abtest separate images: raw. process_image is NOT run on them: it repaints purple page content
                    (174 of these images changed, up to 6.6% of pixels) and they carry no GoodUI markers.
  4. EDITS (edits.py): hand-specified crops / inpaint boxes for the remaining publisher annotations.

    WISERUI_CLEAN=/path/to/workdir python bench/wiserui_clean/build.py
    -> $WISERUI_CLEAN/final/{index}/{win,lose}.png and bench/wiserui_clean/manifest.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from edits import EDITS, LABEL_NOTES, SOURCES, apply_edits  # noqa: E402
from markers import remove_ab_badges, remove_markers  # noqa: E402

ROOT = Path(os.environ.get("WISERUI_CLEAN", "/workspace/bench/wiserui_clean"))
REPO = ROOT / "repo"
REPO_URL = "https://github.com/jeochris/wiserui-bench"
REPO_COMMIT = "010a103"

W = "https://static.wingify.com/gcp/uploads/"
G = "https://goodui.org/site/assets/files/"
# index -> (win_url, lose_url). A composite override gives the same URL twice.
URL_OVERRIDES: dict[int, tuple[str, str]] = {
    # GoodUI moved these loser images to new folder ids; the dataset URLs (files/5006/...) 404.
    20: (G + "5006/leak047_cfull.jpg", G + "5009/leak047_ffull.jpg"),
    21: (G + "5006/leak047_cfull.jpg", G + "5097/leak047_hfull.jpg"),
    # VWO removed the test from the page; same composite still on the CDN (seen in the 2023-06-04 Wayback snapshot).
    103: (W + "2022/12/Human-Interest-2.png", W + "2022/12/Human-Interest-2.png"),
    # Dataset image is Etsy leak #109 (category links) under a Zalando URL; the Zalando button test is leak #27.
    62: (G + "4418/leak027_afull.jpg", G + "4419/leak027_bfull.jpg"),
    # Dataset gives one image for both sides; the source page shows each version as its own image.
    149: (W + "2019/01/10.jpg", W + "2019/01/8.jpg"),  # Tinkoff test 2: V2 green bar (+12.8%) vs V1 yellow (+6.9%)
    174: (W + "2018/08/teamleader-casestudy-12.png", W + "2018/08/teamleader-casestudy-11.png"),  # test 4: icons vs none
    228: (W + "2019/08/Readers-Product-Videos-VARIANT.png", W + "2019/08/Readers-Product-Videos-CONTROL.png"),
    269: (W + "2018/09/flos-casestudy-9.png", W + "2018/09/flos-casestudy-7.png"),  # V2 (winner) vs control
    270: (W + "2018/09/flos-casestudy-9.png", W + "2018/09/flos-casestudy-8.png"),  # V2 vs V1 (model options)
}


def ensure_repo() -> None:
    if not (REPO / "WiserUI_Bench.json").exists():
        subprocess.run(["git", "clone", "-q", REPO_URL, str(REPO)], check=True)
    sys.path.insert(0, str(REPO / "dataset"))


def crop_norm(im, box):
    H, W_ = im.shape[:2]
    y0, x0, y1, x1 = [float(v) for v in box]
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return im[int(max(0, y0 / 1000 * H)):int(round(min(H, y1 / 1000 * H))),
              int(max(0, x0 / 1000 * W_)):int(round(min(W_, x1 / 1000 * W_)))]


def fetch(url: str, dest: Path, sess) -> bool:
    from download_images import download_image

    if dest.exists() and cv2.imread(str(dest)) is not None:
        return True
    for attempt in range(3):
        if download_image(url, dest, sess) and cv2.imread(str(dest)) is not None:
            return True
        time.sleep(2 * (attempt + 1))
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--indices", default="", help="comma list (default all 300)")
    ap.add_argument("--no-edits", action="store_true", help="skip edits.EDITS (to diff what they change)")
    ap.add_argument("--out", default=str(ROOT / "final"))
    args = ap.parse_args()
    ensure_repo()
    from image_preprocess import process_image

    data = {x["index"]: x for x in json.load(open(REPO / "WiserUI_Bench.json"))}
    split = {}
    for line in open(HERE / "composite_split.jsonl"):
        r = json.loads(line)
        if r["ok"]:
            split[r["index"]] = r["raw"]
    want = [int(i) for i in args.indices.split(",") if i.strip()] or sorted(data)
    sess = requests.Session()
    raw_dir, out_dir, tmp = ROOT / "raw", Path(args.out), ROOT / "tmp"
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    failed = []
    for i in want:
        it = data[i]
        win_url, lose_url = URL_OVERRIDES.get(i, (it["win_url"], it["lose_url"]))
        host = it["source"].split("/")[2].replace("www.", "")
        composite = win_url == lose_url
        rec = {"index": i, "source_site": host, "win_url": win_url, "lose_url": lose_url,
               "url_override": i in URL_OVERRIDES, "steps": []}
        d = out_dir / str(i)
        d.mkdir(parents=True, exist_ok=True)
        if composite:
            if i not in split:
                failed.append(i)
                continue
            src = raw_dir / str(i) / "composite.png"
            if not fetch(win_url, src, sess):
                failed.append(i)
                continue
            comp = cv2.imread(str(src))
            if host == "abtest.design":
                comp, badges = remove_ab_badges(comp)
                rec["steps"].append(f"removed {len(badges)} A/B badge(s) from the composite (gray = control, blue = variant)")
            j = split[i]
            w = j["winner_panel"]
            imgs = {"win": crop_norm(comp, j["panels"][w]["box_2d"]),
                    "lose": crop_norm(comp, j["panels"][1 - w]["box_2d"])}
            rec["kind"] = "composite_crop"
            rec["steps"].append("crop panels (composite_split.jsonl)")
        else:
            imgs = {}
            for lab, url in (("win", win_url), ("lose", lose_url)):
                src = raw_dir / str(i) / f"{lab}.png"
                if not fetch(url, src, sess):
                    break
                if host == "goodui.org":
                    t = tmp / f"{i}_{lab}.png"
                    t.parent.mkdir(parents=True, exist_ok=True)
                    process_image(str(src), str(t))
                    im, boxes = remove_markers(cv2.imread(str(t)))
                    if boxes:
                        rec["steps"].append(f"{lab}: removed {len(boxes)} leftover GoodUI marker(s)")
                    imgs[lab] = im
                else:
                    imgs[lab] = cv2.imread(str(src))
            if len(imgs) < 2:
                failed.append(i)
                continue
            rec["kind"] = "separate"
            if host == "goodui.org":
                rec["steps"].insert(0, "repo process_image (GoodUI marker inpainting)")
        for lab, (raw_name, box) in SOURCES.get(i, {}).items():
            x0, y0, x1, y1 = box
            imgs[lab] = cv2.imread(str(raw_dir / str(i) / f"{raw_name}.png"))[y0:y1, x0:x1].copy()
            rec["steps"].append(f"{lab}: crop {box} from the {raw_name} image")
        if i in EDITS and not args.no_edits:
            imgs, notes = apply_edits(imgs, EDITS[i])
            rec["steps"] += notes
        for lab, im in imgs.items():
            cv2.imwrite(str(d / f"{lab}.png"), im)
            rec[f"{lab}_size"] = [int(im.shape[1]), int(im.shape[0])]
        if i in LABEL_NOTES:
            rec["label_note"] = LABEL_NOTES[i]
        old = manifest.get(str(i), {})
        rec.update({k: v for k, v in old.items() if k.startswith("audit") or k == "review"})
        manifest[str(i)] = rec
    shutil.rmtree(tmp, ignore_errors=True)
    if args.no_edits or Path(args.out) != ROOT / "final":
        print(f"built {len(want) - len(failed)}/{len(want)} into {out_dir} (manifest not written)")
        return
    manifest_path.write_text(json.dumps(dict(sorted(manifest.items(), key=lambda kv: int(kv[0]))), indent=1) + "\n")
    print(f"built {len(want) - len(failed)}/{len(want)} pairs into {out_dir}; failed={failed}")


if __name__ == "__main__":
    main()
