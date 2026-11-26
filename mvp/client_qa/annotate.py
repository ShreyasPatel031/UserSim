"""Pen-style markup for QA findings, like the team's Slack screenshots: a hand-drawn magenta loop around the problem
and the finding written above the phone screenshot on a dark Slack-like strip.

    python -m mvp.client_qa.annotate shot.png out.png --box x1,y1,x2,y2 [--box ...] --text "what is wrong"

Boxes are in the screenshot's own pixels (the element frame x 3 on a 3x iPhone).
"""
from __future__ import annotations

import argparse
import math
import random
import textwrap

from PIL import Image, ImageDraw, ImageFont

PEN = (226, 36, 214)


def _font(size: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def loop(draw: ImageDraw.ImageDraw, box, width: int, seed: int = 0) -> None:
    """A slightly uneven ellipse drawn about 1.15 times round, like a quick pen stroke."""
    rnd = random.Random(seed)
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    rx, ry = (x2 - x1) / 2 + width * 2.5, (y2 - y1) / 2 + width * 2.5
    start = rnd.uniform(0, 2 * math.pi)
    pts = []
    n = 160
    for i in range(int(n * 1.15)):
        a = start + 2 * math.pi * i / n
        wob = 1 + 0.04 * math.sin(3 * a + rnd.uniform(0, 0.3)) + 0.03 * (i / n)
        pts.append((cx + rx * wob * math.cos(a), cy + ry * wob * math.sin(a)))
    draw.line(pts, fill=PEN, width=width, joint="curve")
    for p in (pts[0], pts[-1]):
        draw.ellipse([p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2], fill=PEN)


def annotate(shot: str, out: str, boxes: list[tuple[int, int, int, int]], text: str, phone_w: int = 520) -> None:
    im = Image.open(shot).convert("RGB")
    d = ImageDraw.Draw(im)
    w = max(10, im.width // 90)
    for i, b in enumerate(boxes):
        loop(d, b, w, seed=i)
    scale = phone_w / im.width
    phone = im.resize((phone_w, int(im.height * scale)), Image.LANCZOS)
    # rounded phone card
    mask = Image.new("L", phone.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *phone.size], radius=28, fill=255)
    f = _font(30)
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, 46) or [""]
    pad = 32
    head = pad + len(lines) * 40 + 20
    W, H = phone_w + 2 * pad + 260, head + phone.height + pad
    canvas = Image.new("RGB", (W, H), (26, 29, 33))
    cd = ImageDraw.Draw(canvas)
    for i, ln in enumerate(lines):
        cd.text((pad, pad + i * 40), ln, font=f, fill=(222, 224, 227))
    canvas.paste(phone, (pad, head), mask)
    canvas.save(out, optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shot"); ap.add_argument("out")
    ap.add_argument("--box", action="append", required=True, help="x1,y1,x2,y2 in screenshot pixels")
    ap.add_argument("--text", required=True)
    a = ap.parse_args()
    annotate(a.shot, a.out, [tuple(int(v) for v in b.split(",")) for b in a.box], a.text)


if __name__ == "__main__":
    main()
