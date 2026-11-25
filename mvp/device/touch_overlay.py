"""Draw the taps and swipes of a device session onto its screen recording (iOS recordings do not show touches).

    python -m mvp.device.touch_overlay full.mp4 actions.jsonl out.mp4 [--points-width 393] [--offset -0.3]

actions.jsonl rows: {"t": seconds since the session started, "action": {...}}. A tap needs x,y in points; tap_label rows
need "x","y" too (the drive server records the element centre). Swipes are drawn as an arrow-like trail.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile

from PIL import Image, ImageDraw


def ring(path: str, r: int) -> None:
    im = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 2 * r - 2, 2 * r - 2), fill=(255, 64, 64, 90), outline=(255, 40, 40, 255), width=max(4, r // 7))
    d.ellipse((r - r // 4, r - r // 4, r + r // 4, r + r // 4), fill=(255, 40, 40, 230))
    im.save(path)


def duration_of(path: str) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, check=True).stdout.strip())


SWIPE = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("actions"); ap.add_argument("dst")
    ap.add_argument("--points-width", type=float, default=393); ap.add_argument("--offset", type=float, default=-0.3)
    ap.add_argument("--show", type=float, default=0.9)
    a = ap.parse_args()
    w, h = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", a.src],
                                   capture_output=True, text=True, check=True).stdout.strip().split(","))
    k = w / a.points_width
    r = int(26 * k)
    tmp = tempfile.mkdtemp()
    ring(f"{tmp}/ring.png", r)
    marks = []  # (t0, t1, x_px, y_px)
    for line in open(a.actions):
        row = json.loads(line)
        act, t = row["action"], row["t"] + a.offset
        if str(row.get("result", "ok")).startswith("error"):
            continue
        if act.get("action") in ("tap", "tap_label") and "x" in act and "y" in act:
            marks.append((t, t + a.show, act["x"] * k, act["y"] * k))
        elif act.get("action") == "swipe":
            dx, dy = SWIPE.get(act.get("direction", "up"), (0, -1))
            # a swipe "up" moves the content up: the finger travels from lower to upper
            x0, y0 = w / 2, h / 2 - dy * h * 0.2
            for i in range(6):
                f = i / 5
                marks.append((t + f * 0.4, t + f * 0.4 + 0.35, x0 + dx * f * w * 0.35, y0 + dy * f * h * 0.4))
    if not marks:
        subprocess.run(["cp", a.src, a.dst], check=True)
        return
    chain, last = [], "[0:v]"
    for i, (t0, t1, x, y) in enumerate(marks):
        out = f"[o{i}]"
        chain.append(f"{last}[1:v]overlay=x={x - r:.0f}:y={y - r:.0f}:shortest=1:enable='between(t,{t0:.2f},{t1:.2f})'{out}")
        last = out
    fc = ";".join(chain)
    with open(f"{tmp}/fc.txt", "w") as f:
        f.write(fc)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-loop", "1", "-i", f"{tmp}/ring.png",
                    "-t", str(duration_of(a.src)), "-filter_complex_script", f"{tmp}/fc.txt", "-map", f"[o{len(marks) - 1}]", "-an", "-shortest",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", a.dst], check=True)
    print(f"{a.dst}: {len(marks)} touch marks")


if __name__ == "__main__":
    main()
