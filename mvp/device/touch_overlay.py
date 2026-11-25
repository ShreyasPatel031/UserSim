"""Draw the taps and swipes of a device session onto its screen recording (iOS recordings do not show touches).

The touch is drawn the way iOS's own "show touches" looks in demo videos: a translucent dark dot with a white rim with a faint shadow
presses in, holds, and releases into a fading ripple. Swipes show the dot gliding along the path with a short fading
trail. The video is upscaled 2x first so the marks are drawn smoothly.

    python -m mvp.device.touch_overlay part.mp4 actions.jsonl out.mp4 [--points-width 393] [--offset -0.3]

actions.jsonl rows: {"t": seconds from the start of the clip, "action": {...}}; taps need x,y in points.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter

FPS = 30
SWIPE = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def probe(path: str, what: str) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", what, "-of", "csv=p=0",
                           path], capture_output=True, text=True, check=True).stdout.strip()


def ease_out(x: float) -> float:
    return 1 - (1 - x) ** 3


def dot(canvas: Image.Image, cx: float, cy: float, r: float, alpha: float) -> None:
    """Translucent dark dot with a white rim and a soft shadow: readable on light and dark screens."""
    if alpha <= 0 or r <= 0:
        return
    pad = int(r * 0.6) + 4
    size = int(2 * (r + pad))
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c = size / 2
    sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse((c - r, c - r + r * 0.08, c + r, c + r + r * 0.08), fill=(0, 0, 0, int(70 * alpha)))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(r * 0.25)))
    d = ImageDraw.Draw(layer)
    d.ellipse((c - r - 1, c - r - 1, c + r + 1, c + r + 1), outline=(0, 0, 0, int(60 * alpha)), width=1)
    d.ellipse((c - r, c - r, c + r, c + r), fill=(40, 40, 48, int(85 * alpha)),
              outline=(255, 255, 255, int(235 * alpha)), width=max(2, int(r * 0.09)))
    canvas.alpha_composite(layer, (int(cx - c), int(cy - c)))


def ripple(canvas: Image.Image, cx: float, cy: float, r: float, alpha: float) -> None:
    if alpha <= 0:
        return
    d = ImageDraw.Draw(canvas)
    w = max(2, int(r * 0.06))
    d.ellipse((cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1), outline=(255, 255, 255, int(160 * alpha)), width=w + 2)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(40, 40, 48, int(150 * alpha)), width=w)


def tap_frames(r: float) -> list[Image.Image]:
    """0.10 s press-in, 0.20 s hold, 0.35 s release with ripple."""
    size = int(r * 5)
    c = size / 2
    out = []
    n_in, n_hold, n_out = 3, 6, 11
    for i in range(n_in + n_hold + n_out):
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        if i < n_in:
            f = ease_out((i + 1) / n_in)
            dot(im, c, c, r * (1.25 - 0.25 * f), f)
        elif i < n_in + n_hold:
            dot(im, c, c, r, 1.0)
        else:
            f = (i - n_in - n_hold + 1) / n_out
            dot(im, c, c, r * (1 - 0.15 * f), 1 - ease_out(f))
            ripple(im, c, c, r * (1 + 1.1 * ease_out(f)), 1 - f)
        out.append(im)
    return out


def write_clip(frames: list[Image.Image], path: str, tmp: str) -> None:
    d = tempfile.mkdtemp(dir=tmp)
    for i, im in enumerate(frames):
        im.save(f"{d}/{i:03d}.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", f"{d}/%03d.png", "-c:v", "qtrle",
                    "-pix_fmt", "argb", path], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("actions"); ap.add_argument("dst")
    ap.add_argument("--points-width", type=float, default=393); ap.add_argument("--offset", type=float, default=-0.3)
    ap.add_argument("--upscale", type=int, default=2)
    a = ap.parse_args()
    w, h = map(int, probe(a.src, "stream=width,height").split(","))
    W, H = w * a.upscale, h * a.upscale
    W -= W % 2; H -= H % 2
    k = W / a.points_width
    r = 19 * k  # a fingertip-sized dot (about 38 pt across)
    tmp = tempfile.mkdtemp()
    tap_clip = f"{tmp}/tap.mov"
    frames = tap_frames(r)
    write_clip(frames, tap_clip, tmp)
    half = frames[0].size[0] / 2
    marks = []  # (start time, clip path, x, y)
    for i, line in enumerate(open(a.actions)):
        row = json.loads(line)
        act, t = row["action"], max(0.0, row["t"] + a.offset)
        if str(row.get("result", "ok")).startswith("error"):
            continue
        if act.get("action") in ("tap", "tap_label", "type_into") and "x" in act and "y" in act:
            marks.append((t, tap_clip, act["x"] * k - half, act["y"] * k - half))
        elif act.get("action") == "swipe":
            dx, dy = SWIPE.get(act.get("direction", "up"), (0, -1))
            x0 = act.get("x", a.points_width / 2) * k
            y0 = act.get("y", H / k / 2) * k - dy * H * 0.2
            length = (W * 0.35, H * 0.35)
            sf, size = [], int(r * 5)
            n = 16
            for j in range(n):
                im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                f = ease_out(min(1, j / (n - 5)))
                for tr in range(4):  # fading trail behind the dot
                    ft = max(0.0, f - tr * 0.06)
                    dot(im, x0 + dx * ft * length[0], y0 + dy * ft * length[1], r * (1 - tr * 0.15),
                        (1 - tr * 0.3) * (1 if j < n - 4 else (n - j) / 4))
                sf.append(im)
            clip = f"{tmp}/swipe{i}.mov"
            write_clip(sf, clip, tmp)
            marks.append((t, clip, 0, 0))
    if not marks:
        subprocess.run(["cp", a.src, a.dst], check=True)
        return
    args = ["ffmpeg", "-v", "error", "-y", "-i", a.src]
    for t, clip, _, _ in marks:
        args += ["-itsoffset", f"{t:.3f}", "-i", clip]
    chain = [f"[0:v]scale={W}:{H}:flags=lanczos,fps={FPS}[b0]"]
    for i, (_, _, x, y) in enumerate(marks):
        chain.append(f"[b{i}][{i + 1}:v]overlay=x={x:.0f}:y={y:.0f}:eof_action=pass:format=auto[b{i + 1}]")
    with open(f"{tmp}/fc.txt", "w") as f:
        f.write(";".join(chain))
    args += ["-filter_complex_script", f"{tmp}/fc.txt", "-map", f"[b{len(marks)}]", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", a.dst]
    subprocess.run(args, check=True)
    print(f"{a.dst}: {len(marks)} touch marks")


if __name__ == "__main__":
    main()
