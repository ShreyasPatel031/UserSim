"""Read activity_*.jsonl.gz exports and turn them into a timeline.

Input schema (one JSON object per line, ``ts`` ISO-8601 UTC):

- screen: {kind, ts, app, domain, focused, trigger}
- ui:     {kind, ts, event, app, domain, button, click_count, text_len, element_role}
- audio:  {kind, ts, source: mic|system, speech}

Weekly files overlap by a day (local retention is 8 days), so identical lines
are de-duplicated. Nothing here needs window titles, URLs or text.

Timeline model:

- An *activity* event is any ui event, any screen event whose trigger is not
  ``idle``, or a mic chunk with speech (the person is talking, so present).
- A gap of more than ``idle_gap_s`` between activity events is an *idle* gap;
  it ends the current *session*.
- The focused *context* is ``app`` (+ ``domain`` for browsers). A focused
  screen event or a ui event that names a different app (or the same app with a
  different domain) starts a new *segment*.
- Segments shorter than ``min_dwell_s`` (alt-tab flicker) are absorbed.
- A *day* runs from ``day_start_hour`` local time to the same hour next day, so
  late-night work belongs to the evening it started in.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

FILE_GLOB = "activity_*.jsonl.gz"
UNKNOWN = "(unknown)"
OTHER = "other"


@dataclass(frozen=True)
class Config:
    tz: str = "UTC"
    idle_gap_s: float = 300.0  # >5 min without input = idle
    idle_tail_s: float = 15.0  # credit the last event with this much dwell
    min_dwell_s: float = 2.0
    day_start_hour: int = 4
    label_mode: str = "both"  # app | domain | both
    idle_horizon_min: float = 10.0  # "goes idle within N minutes" task
    slot_min: int = 30  # call slots
    call_window_s: int = 300
    max_labels: int = 30
    min_label_count: int = 5

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


# --------------------------------------------------------------------------- reading


def _open_lines_local(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        yield from fh


def _gcloud(*args: str) -> bytes:
    """Run gcloud with the caller's own credentials (never a repo secret)."""
    proc = subprocess.run(["gcloud", *args], capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gcloud {' '.join(args[:2])} failed: {proc.stderr.decode()[:400]}")
    return proc.stdout


def list_inputs(spec: str) -> list[str]:
    """Expand --input: a directory, a single file, or a gs:// prefix/object."""
    if spec.startswith("gs://"):
        if spec.endswith(".gz") or spec.endswith(".jsonl"):
            return [spec]
        prefix = spec.rstrip("/") + "/"
        out = _gcloud("storage", "ls", prefix + FILE_GLOB).decode().split()
        return sorted(u for u in out if u.startswith("gs://"))
    p = Path(spec).expanduser()
    if p.is_dir():
        return sorted(str(f) for f in p.glob(FILE_GLOB)) + sorted(
            str(f) for f in p.glob("activity_*.jsonl")
        )
    if p.is_file():
        return [str(p)]
    raise FileNotFoundError(spec)


def iter_lines(sources: Iterable[str]) -> Iterator[str]:
    for src in sources:
        if src.startswith("gs://"):
            raw = _gcloud("storage", "cat", src)
            if src.endswith(".gz"):
                raw = gzip.decompress(raw)
            yield from io.StringIO(raw.decode("utf-8"))
        else:
            yield from _open_lines_local(Path(src))


_FRAC = re.compile(r"(\.\d{6})\d+")


def parse_ts(s: str) -> float:
    s = s.strip().replace("Z", "+00:00")
    s = _FRAC.sub(r"\1", s)  # nanoseconds -> microseconds
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@dataclass
class RawData:
    screen: list[dict]
    ui: list[dict]
    audio: list[dict]
    n_lines: int
    n_duplicates: int
    n_bad: int


def load_raw(sources: Iterable[str]) -> RawData:
    seen: set[str] = set()
    screen: list[dict] = []
    ui: list[dict] = []
    audio: list[dict] = []
    n = dup = bad = 0
    for line in iter_lines(sources):
        line = line.strip()
        if not line:
            continue
        n += 1
        if line in seen:
            dup += 1
            continue
        seen.add(line)
        try:
            obj = json.loads(line)
            obj["t"] = parse_ts(obj["ts"])
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        kind = obj.get("kind")
        if kind == "screen":
            screen.append(obj)
        elif kind == "ui":
            ui.append(obj)
        elif kind == "audio":
            audio.append(obj)
        else:
            bad += 1
    for xs in (screen, ui, audio):
        xs.sort(key=lambda o: o["t"])
    return RawData(screen, ui, audio, n, dup, bad)


# --------------------------------------------------------------------------- timeline


def _norm_app(app) -> str | None:
    if not app or not isinstance(app, str):
        return None
    return app.strip() or None


def _norm_domain(domain) -> str | None:
    if not domain or not isinstance(domain, str):
        return None
    d = domain.strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d or None


def make_label(app: str | None, domain: str | None, mode: str) -> str:
    if mode == "app":
        return app or UNKNOWN
    if mode == "domain":
        return domain or app or UNKNOWN
    if app and domain:
        return f"{app} | {domain}"
    return app or domain or UNKNOWN


@dataclass
class Segment:
    start: float
    end: float
    label: str  # raw label
    app: str | None
    domain: str | None
    session: int = -1
    day: str = ""  # local "day" (YYYY-MM-DD), see Config.day_start_hour
    lab: str = ""  # label mapped to the train vocabulary

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Timeline:
    cfg: Config
    segments: list[Segment]
    idles: list[tuple[float, float]]
    audio: list[dict]
    call_windows: list[tuple[float, float]]
    days: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def local(self, t: float) -> datetime:
        return datetime.fromtimestamp(t, self.cfg.zone)

    def day_of(self, t: float) -> str:
        return day_key(t, self.cfg)

    def day_origin(self, day: str) -> float:
        """Epoch seconds of local midnight of ``day`` (the calendar date)."""
        d = date.fromisoformat(day)
        return datetime(d.year, d.month, d.day, tzinfo=self.cfg.zone).timestamp()


def day_key(t: float, cfg: Config) -> str:
    loc = datetime.fromtimestamp(t, cfg.zone) - timedelta(hours=cfg.day_start_hour)
    return loc.date().isoformat()


def _is_activity(e: dict) -> bool:
    k = e["kind"]
    if k == "ui":
        return True
    if k == "screen":
        return e.get("trigger") != "idle"
    if k == "audio":
        return e.get("source") == "mic" and bool(e.get("speech"))
    return False


def _context_of(e: dict) -> tuple[str, str | None] | None:
    k = e["kind"]
    if k == "screen" and e.get("focused") is False:
        return None
    if k in ("screen", "ui"):
        app = _norm_app(e.get("app"))
        if app:
            return app, _norm_domain(e.get("domain"))
    return None


def build_segments(raw: RawData, cfg: Config) -> tuple[list[Segment], list[tuple[float, float]]]:
    events = sorted(
        (e for e in [*raw.screen, *raw.ui, *raw.audio] if _is_activity(e)), key=lambda e: e["t"]
    )
    segs: list[Segment] = []
    idles: list[tuple[float, float]] = []
    cur_app: str | None = None
    cur_dom: str | None = None
    seg_start: float | None = None
    last: float | None = None
    session = 0

    def close(at: float) -> None:
        if seg_start is not None and at > seg_start:
            segs.append(
                Segment(seg_start, at, make_label(cur_app, cur_dom, cfg.label_mode), cur_app, cur_dom, session)
            )

    for e in events:
        t = e["t"]
        if last is not None and t - last > cfg.idle_gap_s:
            end = last + min(cfg.idle_tail_s, t - last)
            close(end)
            idles.append((end, t))
            session += 1
            seg_start = t
        elif last is not None and day_key(t, cfg) != day_key(last, cfg):
            close(t)
            session += 1
            seg_start = t
        if seg_start is None:
            seg_start = t
        ctx = _context_of(e)
        if ctx is not None:
            app, dom = ctx
            if app != cur_app:
                close(t)
                seg_start, cur_app, cur_dom = t, app, dom
            elif dom and dom != cur_dom:
                if cur_dom is None:
                    # Same app, domain just became known: label the open segment.
                    cur_dom = dom
                else:
                    close(t)
                    seg_start, cur_dom = t, dom
        last = t
    if last is not None:
        close(last + cfg.idle_tail_s)
    return _clean(segs, cfg), idles


def _merge_same(segs: list[Segment], key: str) -> list[Segment]:
    out: list[Segment] = []
    for s in segs:
        if (
            out
            and getattr(out[-1], key) == getattr(s, key)
            and out[-1].session == s.session
            and abs(out[-1].end - s.start) < 1e-6
        ):
            out[-1] = replace(out[-1], end=s.end)
        else:
            out.append(s)
    return out


def _clean(segs: list[Segment], cfg: Config) -> list[Segment]:
    """Absorb flicker segments into the one before them, then merge repeats."""
    out: list[Segment] = []
    for s in segs:
        if s.dur < cfg.min_dwell_s and out and out[-1].session == s.session:
            out[-1] = replace(out[-1], end=s.end)
            continue
        out.append(s)
    out = _merge_same(out, "label")
    for s in out:
        s.day = day_key(s.start, cfg)
    return out


def detect_calls(audio: list[dict], cfg: Config, min_chunks: int = 2) -> list[tuple[float, float]]:
    """A call window: at least ``min_chunks`` mic chunks with speech and as many
    system chunks with speech in one window (default 5 min = 10 chunks per
    source). Adjacent call windows (one gap window allowed) merge into one call."""
    w = cfg.call_window_s
    mic: Counter = Counter()
    sysc: Counter = Counter()
    for a in audio:
        if not a.get("speech"):
            continue
        b = int(a["t"] // w)
        if a.get("source") == "mic":
            mic[b] += 1
        elif a.get("source") == "system":
            sysc[b] += 1
    hits = sorted(b for b in mic if mic[b] >= min_chunks and sysc.get(b, 0) >= min_chunks)
    calls: list[tuple[float, float]] = []
    for b in hits:
        s, e = b * w, (b + 1) * w
        if calls and s - calls[-1][1] <= w:
            calls[-1] = (calls[-1][0], e)
        else:
            calls.append((s, e))
    return [(float(s), float(e)) for s, e in calls]


def build_timeline(raw: RawData, cfg: Config) -> Timeline:
    segs, idles = build_segments(raw, cfg)
    calls = detect_calls(raw.audio, cfg)
    days = sorted({s.day for s in segs})
    stats = {
        "lines": raw.n_lines,
        "duplicate_lines": raw.n_duplicates,
        "bad_lines": raw.n_bad,
        "screen_events": len(raw.screen),
        "ui_events": len(raw.ui),
        "audio_chunks": len(raw.audio),
        "segments": len(segs),
        "idle_gaps": len(idles),
        "days": len(days),
        "call_episodes": len(calls),
    }
    return Timeline(cfg, segs, idles, raw.audio, calls, days, stats)


def load_timeline(spec: str, cfg: Config) -> Timeline:
    return build_timeline(load_raw(list_inputs(spec)), cfg)


# --------------------------------------------------------------------------- vocabulary


def fit_vocab(segs: Iterable[Segment], cfg: Config) -> list[str]:
    c = Counter(s.label for s in segs)
    keep = [lab for lab, n in c.most_common() if n >= cfg.min_label_count and lab != UNKNOWN]
    return keep[: cfg.max_labels]


def apply_vocab(segs: list[Segment], vocab: list[str]) -> list[Segment]:
    """Map labels outside the vocabulary to ``other`` and merge what that joins."""
    vs = set(vocab)
    mapped = [replace(s, lab=s.label if s.label in vs else OTHER) for s in segs]
    return _merge_same(mapped, "lab")


def sessions_by_day(segs: list[Segment]) -> dict[str, list[list[Segment]]]:
    out: dict[str, list[list[Segment]]] = defaultdict(list)
    cur: list[Segment] = []
    for s in segs:
        if cur and (s.session != cur[-1].session or s.day != cur[-1].day):
            out[cur[0].day].append(cur)
            cur = []
        cur.append(s)
    if cur:
        out[cur[0].day].append(cur)
    return out
