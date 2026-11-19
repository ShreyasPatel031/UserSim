"""Synthetic screenpipe activity export in the exact production schema.

A fictional knowledge worker with a routine: comms in the morning, coding
blocks, a daily standup, two weekly 1:1s, ad-hoc calls, lunch, short breaks,
optional evening session, light weekends. Context switching is an
hour-dependent Markov chain with a "return to where I was" habit, so
first-order, second-order and time-of-day models each have something to find.

Output mimics the weekly upload: one ``activity_YYYY-MM-DD.jsonl.gz`` per
Sunday covering the 8 days up to Sunday 20:00 local (consecutive files overlap
by a day, as local retention is 8 days).

    python -m experiments.personal_activity.synth --out experiments/personal_activity/fixtures/synthetic
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CHROME = "Google Chrome"

# context -> (app, domain, group, median dwell seconds)
CONTEXTS: dict[str, tuple[str, str | None, str, float]] = {
    "slack": ("Slack", None, "comms", 50),
    "mail": (CHROME, "mail.google.com", "comms", 80),
    "calendar": (CHROME, "calendar.google.com", "comms", 25),
    "messages": ("Messages", None, "personal", 35),
    "cursor": ("Cursor", None, "code", 240),
    "terminal": ("iTerm2", None, "code", 70),
    "github": (CHROME, "github.com", "code", 110),
    "claude": (CHROME, "claude.ai", "code", 130),
    "stackoverflow": (CHROME, "stackoverflow.com", "code", 70),
    "docs": (CHROME, "docs.google.com", "write", 300),
    "notion": ("Notion", None, "write", 200),
    "youtube": (CHROME, "youtube.com", "leisure", 420),
    "hn": (CHROME, "news.ycombinator.com", "leisure", 150),
    "x": (CHROME, "x.com", "leisure", 120),
    "spotify": ("Spotify", None, "personal", 12),
    "finder": ("Finder", None, "personal", 15),
    "rare_tool": ("Preview", None, "personal", 30),
    "rare_site": (CHROME, "wikipedia.org", "leisure", 90),
}

# Pairwise affinity (symmetric-ish); missing pairs get a small floor.
AFFINITY = {
    ("cursor", "terminal"): 8, ("cursor", "github"): 4, ("cursor", "claude"): 5,
    ("cursor", "stackoverflow"): 2, ("terminal", "github"): 3, ("github", "claude"): 1.5,
    ("slack", "mail"): 3, ("slack", "calendar"): 2, ("mail", "calendar"): 3,
    ("slack", "cursor"): 3, ("slack", "github"): 2, ("slack", "docs"): 2,
    ("docs", "notion"): 2, ("docs", "mail"): 1.5, ("notion", "slack"): 1.5,
    ("youtube", "x"): 2, ("x", "hn"): 2, ("hn", "youtube"): 1.5, ("messages", "x"): 1.5,
    ("spotify", "cursor"): 1.5, ("finder", "cursor"): 1, ("finder", "docs"): 1,
    ("messages", "slack"): 1.5, ("rare_tool", "finder"): 1, ("rare_site", "hn"): 1,
}

# Mode -> group weights.
MODES = {
    "morning": {"comms": 4.0, "code": 1.0, "write": 1.0, "leisure": 0.6, "personal": 1.0},
    "deep": {"comms": 0.7, "code": 4.0, "write": 1.2, "leisure": 0.2, "personal": 0.6},
    "afternoon": {"comms": 1.4, "code": 2.0, "write": 2.0, "leisure": 0.5, "personal": 0.8},
    "evening": {"comms": 0.4, "code": 0.8, "write": 0.3, "leisure": 4.0, "personal": 2.0},
    "weekend": {"comms": 0.3, "code": 0.7, "write": 0.3, "leisure": 4.0, "personal": 2.5},
}
DWELL_SCALE = {"morning": 0.8, "deep": 1.4, "afternoon": 1.0, "evening": 1.2, "weekend": 1.1}

NAMES = list(CONTEXTS)


def _aff(a: str, b: str) -> float:
    return AFFINITY.get((a, b)) or AFFINITY.get((b, a)) or 0.3


def _mode(hour: float, weekend: bool) -> str:
    if weekend:
        return "weekend"
    if hour < 10.5:
        return "morning"
    if hour < 12.5 or 14 <= hour < 16.5:
        return "deep"
    if hour < 18.5:
        return "afternoon"
    return "evening"


class Person:
    def __init__(self, rng: random.Random, tz: ZoneInfo):
        self.rng = rng
        self.tz = tz

    # ----------------------------------------------------------------- behaviour
    def next_context(self, cur: str, prev: str | None, hour: float, weekend: bool) -> str:
        if prev and prev != cur and self.rng.random() < 0.30:
            return prev  # "back to what I was doing"
        mode = MODES[_mode(hour, weekend)]
        names = [n for n in NAMES if n != cur]
        w = []
        for n in names:
            g = CONTEXTS[n][2]
            base = _aff(cur, n) * mode[g]
            if n.startswith("rare"):
                base *= 0.15
            w.append(base)
        return self.rng.choices(names, weights=w)[0]

    def dwell(self, ctx: str, hour: float, weekend: bool) -> float:
        med = CONTEXTS[ctx][3] * DWELL_SCALE[_mode(hour, weekend)]
        return max(3.0, med * math.exp(self.rng.gauss(0, 0.85)))

    def first_context(self, hour: float, weekend: bool) -> str:
        if weekend or hour >= 19:
            return self.rng.choice(["youtube", "x", "messages", "hn"])
        return self.rng.choices(["slack", "mail", "calendar", "cursor"], [4, 4, 1, 1])[0]


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _screen(t, app, domain, focused, trigger):
    return {"kind": "screen", "ts": _iso(t), "app": app, "domain": domain, "focused": focused, "trigger": trigger}


def _ui(t, event, app, domain, button=None, click_count=None, text_len=None, role=None):
    return {
        "kind": "ui", "ts": _iso(t), "event": event, "app": app, "domain": domain,
        "button": button, "click_count": click_count, "text_len": text_len, "element_role": role,
    }


def _audio(t, source, speech):
    return {"kind": "audio", "ts": _iso(t), "source": source, "speech": speech}


def simulate_day(p: Person, day: date) -> list[dict]:
    rng = p.rng
    weekend = day.weekday() >= 5
    if weekend and rng.random() < 0.3:
        return []  # away from the computer

    def at(hh: float) -> float:
        base = datetime(day.year, day.month, day.day, tzinfo=p.tz)
        return (base + timedelta(hours=hh)).timestamp()

    def hour_of(t: float) -> float:
        loc = datetime.fromtimestamp(t, p.tz)
        return loc.hour + loc.minute / 60

    # Active windows (local hours) and calls.
    windows: list[tuple[float, float]] = []
    calls: list[tuple[float, float, str]] = []  # start_h, end_h, context
    if not weekend:
        start = rng.gauss(8.75, 0.4)
        lunch = rng.gauss(12.6, 0.25)
        windows.append((start, lunch))
        windows.append((lunch + rng.uniform(0.5, 0.9), rng.gauss(18.3, 0.6)))
        if rng.random() < 0.5:
            s = rng.gauss(21.0, 0.5)
            windows.append((s, s + rng.uniform(0.7, 2.0)))
        calls.append((10.0, 10.0 + rng.uniform(0.2, 0.3), "meet"))  # standup
        if day.weekday() in (1, 3):
            calls.append((14.0, 14.5, "zoom"))
        if rng.random() < 0.45:
            s = rng.choice([11.0, 11.5, 15.0, 15.5, 16.0, 16.5, 17.0])
            calls.append((s, s + rng.uniform(0.3, 0.7), rng.choice(["zoom", "meet"])))
    else:
        s = rng.gauss(10.5, 1.0)
        windows.append((s, s + rng.uniform(1.0, 3.0)))
        if rng.random() < 0.6:
            s = rng.gauss(20.5, 1.0)
            windows.append((s, s + rng.uniform(0.7, 2.5)))

    call_apps = {"zoom": ("zoom.us", None), "meet": (CHROME, "meet.google.com")}
    call_spans = [(at(a), at(b), call_apps[c]) for a, b, c in calls]

    def in_call(t: float):
        for a, b, ctx in call_spans:
            if a <= t < b:
                return a, b, ctx
        return None

    events: list[dict] = []
    present: list[tuple[float, float]] = []  # at-the-computer spans (for audio)
    videos: list[tuple[float, float]] = []  # system audio has speech, mic does not
    for ws, we in windows:
        t, end = at(ws), at(we)
        prev: str | None = None
        cur = p.first_context(ws, weekend)
        seg_open = True
        while t < end:
            c = in_call(t)
            if c:
                a, b, (app, dom) = c
                present.append((t, b))
                events.append(_ui(t, "app_switch", app, dom))
                events.append(_screen(t + 0.4, app, dom, True, "window_focus"))
                tt = t + rng.uniform(20, 60)
                while tt < b:
                    if rng.random() < 0.2:  # glance at slack/notes during the call
                        side = rng.choice(["slack", "notion", "docs"])
                        sa, sd = CONTEXTS[side][:2]
                        events.append(_ui(tt, "app_switch", sa, sd))
                        events.append(_screen(tt + 0.3, sa, sd, True, "window_focus"))
                        tt += rng.uniform(15, 60)
                        events.append(_ui(tt, "app_switch", app, dom))
                    else:
                        events.append(_screen(tt, app, dom, True, "visual_change"))
                    tt += rng.uniform(40, 120)
                t, prev, cur = b + rng.uniform(5, 30), None, rng.choice(["slack", "cursor", "calendar"])
                continue
            hour = hour_of(t)
            app, dom = CONTEXTS[cur][:2]
            d = p.dwell(cur, hour, weekend)
            seg_end = min(t + d, end)
            nxt_call = min((a for a, _, _ in call_spans if a > t), default=None)
            if nxt_call is not None and nxt_call < seg_end:
                seg_end = nxt_call
            present.append((t, seg_end))
            events.append(_ui(t, "app_switch", app, dom))
            events.append(_screen(t + rng.uniform(0.2, 1.0), app, dom, True, "window_focus"))
            if rng.random() < 0.05:  # unfocused window on the other screen
                o = CONTEXTS[rng.choice(NAMES)]
                events.append(_screen(t + 1.2, o[0], o[1], False, "visual_change"))
            tt = t + rng.expovariate(1 / 25)
            group = CONTEXTS[cur][2]
            while tt < seg_end:
                r = rng.random()
                if group in ("code", "write") and r < 0.45:
                    events.append(_ui(tt, "key", app, dom, text_len=rng.randint(3, 80), role="AXTextArea"))
                    if rng.random() < 0.3:
                        events.append(_screen(tt + 0.5, app, dom, True, "key_press"))
                elif r < 0.7:
                    events.append(_ui(tt, "click", app, dom, button=0, click_count=1 + (rng.random() < 0.1), role=rng.choice(["AXButton", "AXLink", "AXStaticText"])))
                    if rng.random() < 0.4:
                        events.append(_screen(tt + 0.3, app, dom, True, "click"))
                else:
                    events.append(_ui(tt, "scroll", app, dom))
                    if rng.random() < 0.4:
                        events.append(_screen(tt + 0.6, app, dom, True, "scroll_stop"))
                # Videos: long gaps between inputs but still watching.
                tt += rng.expovariate(1 / (110 if cur == "youtube" else 30))
            if cur == "youtube":
                videos.append((t, seg_end))
                v = t + 200
                while v < seg_end:
                    events.append(_screen(v, app, dom, True, "visual_change"))
                    v += 200
            t = seg_end
            if t >= end:
                break
            # short break?
            br = 0.035 if not weekend else 0.05
            if rng.random() < br:
                gap = 60 * math.exp(rng.gauss(math.log(11), 0.5))
                events.append(_screen(t + 60, app, dom, True, "idle"))
                t += gap
                prev, cur = None, cur if rng.random() < 0.6 else p.next_context(cur, None, hour, weekend)
                continue
            prev, cur = cur, p.next_context(cur, prev, hour_of(t), weekend)

    # Audio: one chunk per source per 30 s from first to last activity of the day.
    if events:
        events.sort(key=lambda e: e["ts"])
        t0 = math.floor(min(s for s, _ in present) / 30) * 30
        t1 = max(e for _, e in present) + 300
        t = t0
        while t < t1:
            c = in_call(t)
            if c:
                mic, sysv = rng.random() < 0.55, rng.random() < 0.7
            elif any(a <= t < b for a, b in videos):
                mic, sysv = rng.random() < 0.015, rng.random() < 0.6
            else:
                mic, sysv = rng.random() < 0.015, rng.random() < 0.03
            events.append(_audio(t, "mic", mic))
            events.append(_audio(t + 0.05, "system", sysv))
            t += 30
    events.sort(key=lambda e: e["ts"])
    return events


def generate(out: Path, *, start: date, weeks: int, tz: str, seed: int) -> list[Path]:
    """Write ``weeks`` weekly files; ``start`` should be a Monday."""
    zone = ZoneInfo(tz)
    rng = random.Random(seed)
    p = Person(rng, zone)
    first = start - timedelta(days=1)  # Sunday before, so file 1 has 8 days too
    n_days = weeks * 7 + 1
    all_events: list[dict] = []
    for i in range(n_days):
        all_events.extend(simulate_day(p, first + timedelta(days=i)))
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for w in range(weeks):
        sunday = start + timedelta(days=7 * w + 6)
        hi = datetime(sunday.year, sunday.month, sunday.day, 20, tzinfo=zone).timestamp()
        lo = hi - 8 * 86400
        rows = [e for e in all_events if lo <= _epoch(e["ts"]) < hi]
        path = out / f"activity_{sunday.isoformat()}.jsonl.gz"
        # mtime=0 keeps the gzip bytes reproducible.
        with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            for e in rows:
                gz.write((json.dumps(e, separators=(",", ":")) + "\n").encode())
        paths.append(path)
    meta = {"synthetic": True, "tz": tz, "seed": seed, "start": start.isoformat(), "weeks": weeks}
    (out / "fixture.json").write_text(json.dumps(meta, indent=2) + "\n")
    return paths


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(Path(__file__).parent / "fixtures" / "synthetic"))
    ap.add_argument("--start", default="2026-01-05", help="a Monday")
    ap.add_argument("--weeks", type=int, default=4)
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    paths = generate(Path(a.out), start=date.fromisoformat(a.start), weeks=a.weeks, tz=a.tz, seed=a.seed)
    for pth in paths:
        print(pth, pth.stat().st_size)


if __name__ == "__main__":
    main()
