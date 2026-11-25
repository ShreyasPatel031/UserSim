"""Turn a full device-session recording into a short client video: frozen stretches (waiting for the device, the agent
thinking, the app loading) are cut to 0.8 s each and the rest plays at 1.5x. Every screen change is kept.

    python -m mvp.device.fast_video full.mp4 out.mp4 [--speed 1.5] [--keep-freeze 0.8]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile


def duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def freezes(path: str, noise: float = 0.002, min_s: float = 3) -> list[tuple[float, float]]:
    err = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-vf", f"scale=320:-2,freezedetect=n={noise}:d={min_s}",
                          "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    out, start = [], None
    for k, v in re.findall(r"freeze_(start|end): ([0-9.]+)", err):
        if k == "start":
            start = float(v)
        elif start is not None:
            out.append((start, float(v))); start = None
    if start is not None:
        out.append((start, duration(path)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--speed", type=float, default=1.5); ap.add_argument("--keep-freeze", type=float, default=0.8)
    ap.add_argument("--start", type=float, default=0.0,
                    help="seconds of the source to skip: device setup, login and any setup retries are never shown")
    a = ap.parse_args()
    keep, t = [], a.start
    for s, e in freezes(a.src):
        if e <= a.start:
            continue
        s = max(s, a.start)
        keep.append((t, s + a.keep_freeze)); t = e
    keep.append((t, duration(a.src)))
    keep = [(s, e) for s, e in keep if e > s]
    # one small file per kept stretch, then a concat: memory stays flat however long the session is
    tmp = tempfile.mkdtemp()
    names = []
    for i, (s0, e0) in enumerate(keep):
        name = f"{tmp}/s{i:04d}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s0:.3f}", "-t", f"{e0 - s0:.3f}", "-i", a.src,
                        "-vf", f"setpts=PTS/{a.speed},fps=30,scale=-2:1280", "-an", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", name], check=True)
        names.append(name)
    with open(f"{tmp}/list.txt", "w") as f:
        f.writelines(f"file '{n}'\n" for n in names)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{tmp}/list.txt", "-c", "copy",
                    "-movflags", "+faststart", a.dst], check=True)
    print(f"{a.dst}: {duration(a.dst):.1f} s from {duration(a.src):.1f} s")


if __name__ == "__main__":
    main()
