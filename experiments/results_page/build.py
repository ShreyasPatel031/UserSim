#!/usr/bin/env python3
"""Build the session page bundle from a plugin run folder plus an annotation file.

usage: build.py <run_dir> <annotations.json> <out_dir>
Writes <out_dir>/index.html (data inlined), <out_dir>/data.json and <out_dir>/shots/<run>.jpg (one vertical sprite per run).
"""
import io, json, sys, urllib.request
from pathlib import Path
from PIL import Image

W, H = 960, 600  # sprite frame size (16:10, matches the 1280x800 viewport)


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception:
        return None


def main(run_dir, ann_path, out_dir):
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    (out_dir / "shots").mkdir(parents=True, exist_ok=True)
    ann = json.loads(Path(ann_path).read_text())
    runs = {}
    for f in sorted((run_dir / "runs").glob("*.json")):
        r = json.loads(f.read_text())
        base = ((r.get("report") or {}).get("steps_screenshot_base") or "")
        steps = []
        for s in r.get("steps") or []:
            a = s.get("action")
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except Exception:
                    a = {"type": a}
            url = s.get("screenshot") or (base.replace("{n}", str(s.get("step"))) if base else "")
            steps.append({"step": s.get("step"), "action": a or {}, "thought": s.get("thought") or "", "url": s.get("url") or "", "shot": url})
        if (out_dir / 'shots' / f'{f.stem}.jpg').exists():
            steps=[{k:v for k,v in s.items()} for s in steps]
            frames=None
        else:
            frames = []
        blank = Image.new("RGB", (W, H), (230, 232, 236))
        last = blank
        for s in (steps if frames is not None else []):
            im = fetch(s["shot"]) if s["shot"] else None
            im = im.resize((W, int(im.height * W / im.width))).crop((0, 0, W, H)) if im else last
            frames.append(im)
            last = im
        if frames:
            sprite = Image.new("RGB", (W, H * len(frames)))
            for i, im in enumerate(frames):
                sprite.paste(im, (0, i * H))
            sprite.save(out_dir / "shots" / f"{f.stem}.jpg", quality=72, optimize=True)
        for s in steps:
            s.pop("shot", None)
            s.pop("url", None)
        rk = f.stem
        fr = ann.get("friction_steps", {}).get(rk, {})
        for s in steps:
            if str(s["step"]) in fr:
                s["friction"] = fr[str(s["step"])]
        runs[rk] = {"outcome": r.get("outcome") or "not_run", "notes": r.get("notes") or "", "steps": steps,
                    "sprite": f"shots/{rk}.jpg", "watch": r.get("watch_url") or ""}
    data = dict(ann)
    data.pop("friction_steps", None)
    data["runs"] = runs
    (out_dir / "data.json").write_text(json.dumps(data))
    page = Path(__file__).with_name("index.html").read_text()
    (out_dir / "index.html").write_text(page.replace("__SESSION_JSON__", json.dumps(data).replace("</", "<\\/")))
    print(out_dir / "index.html", sum(len(r["steps"]) for r in runs.values()), "steps")


if __name__ == "__main__":
    main(*sys.argv[1:4])
