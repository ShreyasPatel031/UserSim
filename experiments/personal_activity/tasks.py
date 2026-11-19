"""Prediction tasks built from a Timeline, and the time-ordered split.

Switch-level tasks (one point per focused segment):
  - next context after the current one, within the same session (top-1/top-3)
  - time until the next switch = the segment's dwell (MAE, log-MAE)
  - goes idle within ``idle_horizon_min`` of the segment starting (Brier, AUC)

Day-level tasks (one point per observed day, day-ahead):
  - first-active time, total active time, share of time per context
  - when calls happen: P(call) per ``slot_min`` slot of the day
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from .loader import OTHER, Config, Segment, Timeline, apply_vocab, fit_vocab, sessions_by_day

HOUR_BUCKET = 3  # hours per time-of-day bucket
N_BUCKETS = 24 // HOUR_BUCKET


def hour_bucket(hour: float, weekday: int) -> int:
    return int(hour) % 24 // HOUR_BUCKET + (N_BUCKETS if weekday >= 5 else 0)


def bucket_name(hb: int) -> str:
    h = (hb % N_BUCKETS) * HOUR_BUCKET
    return f"{'weekend' if hb >= N_BUCKETS else 'weekday'} {h:02d}:00-{h + HOUR_BUCKET:02d}:00"


@dataclass
class SwitchPoint:
    id: int
    day: str
    t: float
    hour: float  # local clock hour, fractional
    weekday: int  # 0 = Monday
    cur: str
    prev: str | None  # previous context in the same session
    prev_dur: float | None
    recent: list[tuple[str, float, float]]  # (lab, start, dur) earlier today, oldest first (max 8)
    time_in_session: float
    first_in_session: bool
    dur: float  # target: dwell / time until next switch
    next: str | None  # target: next context in the session (None = session ends)
    idle_soon: bool  # target: session ends within horizon

    @property
    def hb(self) -> int:
        """Time-of-day bucket, separate for weekdays and weekends."""
        return hour_bucket(self.hour, self.weekday)

    @property
    def weekend(self) -> bool:
        return self.weekday >= 5


@dataclass
class DayStats:
    day: str
    weekday: int
    first_min: float  # minutes after local midnight of ``day``
    last_min: float
    active_min: float
    shares: dict[str, float]
    call_slots: set[int]  # slot index from day start (see slot_clock)
    n_sessions: int
    sessions: list[tuple[float, float]] = field(default_factory=list)  # (start_min, end_min)
    segments: list[Segment] = field(default_factory=list, repr=False)
    idles: list[tuple[float, float]] = field(default_factory=list, repr=False)  # (start_min, dur_s)

    @property
    def weekend(self) -> bool:
        return self.weekday >= 5


@dataclass
class Dataset:
    cfg: Config
    timeline: Timeline
    vocab: list[str]
    labels: list[str]  # vocab + [other]
    train_days: list[str]
    val_days: list[str]  # tail of train, used only to tune blend weights
    test_days: list[str]
    segments: list[Segment]  # labels mapped to the train vocabulary
    points: list[SwitchPoint]
    days: dict[str, DayStats]

    def pts(self, days: list[str] | set[str]) -> list[SwitchPoint]:
        ds = set(days)
        return [p for p in self.points if p.day in ds]

    def segs(self, days: list[str] | set[str]) -> list[Segment]:
        ds = set(days)
        return [s for s in self.segments if s.day in ds]

    @property
    def n_slots(self) -> int:
        return 24 * 60 // self.cfg.slot_min


def split_days(days: list[str], test_frac: float = 0.3, min_test: int = 2) -> tuple[list[str], list[str], list[str]]:
    days = sorted(days)
    if len(days) < 4:
        raise ValueError(f"need at least 4 observed days for a time split, got {len(days)}")
    n_test = max(min_test, round(len(days) * test_frac))
    n_test = min(n_test, len(days) - 3)
    train, test = days[:-n_test], days[-n_test:]
    n_val = max(1, round(len(train) * 0.2))
    return train, train[-n_val:], test


def slot_clock(slot: int, cfg: Config) -> str:
    m = cfg.day_start_hour * 60 + slot * cfg.slot_min
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def _local_hour(tl: Timeline, t: float) -> tuple[float, int]:
    loc = tl.local(t)
    return loc.hour + loc.minute / 60 + loc.second / 3600, loc.weekday()


def build_points(tl: Timeline, segs: list[Segment]) -> list[SwitchPoint]:
    cfg = tl.cfg
    horizon = cfg.idle_horizon_min * 60
    pts: list[SwitchPoint] = []
    for day, sessions in sessions_by_day(segs).items():
        today: list[tuple[str, float, float]] = []
        for sess in sessions:
            s_start, s_end = sess[0].start, sess[-1].end
            for i, s in enumerate(sess):
                hour, wd = _local_hour(tl, s.start)
                pts.append(
                    SwitchPoint(
                        id=len(pts),
                        day=day,
                        t=s.start,
                        hour=hour,
                        weekday=wd,
                        cur=s.lab,
                        prev=sess[i - 1].lab if i else None,
                        prev_dur=sess[i - 1].dur if i else None,
                        recent=today[-8:],
                        time_in_session=s.start - s_start,
                        first_in_session=i == 0,
                        dur=s.dur,
                        next=sess[i + 1].lab if i + 1 < len(sess) else None,
                        idle_soon=(s_end - s.start) <= horizon,
                    )
                )
                today = today + [(s.lab, s.start, s.dur)]
    pts.sort(key=lambda p: p.t)
    for i, p in enumerate(pts):
        p.id = i
    return pts


def build_day_stats(tl: Timeline, segs: list[Segment]) -> dict[str, DayStats]:
    cfg = tl.cfg
    slot_s = cfg.slot_min * 60
    by_day: dict[str, list[Segment]] = defaultdict(list)
    for s in segs:
        by_day[s.day].append(s)
    calls_by_day: dict[str, set[int]] = defaultdict(set)
    for a, b in tl.call_windows:
        t = a
        while t < b:
            d = tl.day_of(t)
            off = t - tl.day_origin(d) - cfg.day_start_hour * 3600
            calls_by_day[d].add(int(off // slot_s))
            t += 60
    idles_by_day: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for a, b in tl.idles:
        d = tl.day_of(a)
        if tl.day_of(b) == d:
            idles_by_day[d].append(((a - tl.day_origin(d)) / 60, b - a))
    out: dict[str, DayStats] = {}
    for d, ss in by_day.items():
        origin = tl.day_origin(d)
        tot = sum(s.dur for s in ss) or 1.0
        sh: Counter = Counter()
        for s in ss:
            sh[s.lab] += s.dur / tot
        out[d] = DayStats(
            day=d,
            weekday=date.fromisoformat(d).weekday(),
            first_min=(ss[0].start - origin) / 60,
            last_min=(ss[-1].end - origin) / 60,
            active_min=sum(s.dur for s in ss) / 60,
            shares=dict(sh),
            call_slots=calls_by_day.get(d, set()),
            n_sessions=len({s.session for s in ss}),
            sessions=_session_spans(ss, origin),
            segments=ss,
            idles=idles_by_day.get(d, []),
        )
    return out


def _session_spans(ss: list[Segment], origin: float) -> list[tuple[float, float]]:
    spans: dict[int, list[float]] = {}
    for s in ss:
        a = spans.setdefault(s.session, [s.start, s.end])
        a[0], a[1] = min(a[0], s.start), max(a[1], s.end)
    return sorted(((a - origin) / 60, (b - origin) / 60) for a, b in spans.values())


def build_dataset(tl: Timeline, test_frac: float = 0.3) -> Dataset:
    train, val, test = split_days(tl.days, test_frac)
    tr = set(train)
    vocab = fit_vocab((s for s in tl.segments if s.day in tr), tl.cfg)
    segs = apply_vocab(tl.segments, vocab)
    ds = Dataset(
        cfg=tl.cfg,
        timeline=tl,
        vocab=vocab,
        labels=vocab + [OTHER],
        train_days=train,
        val_days=val,
        test_days=test,
        segments=segs,
        points=build_points(tl, segs),
        days=build_day_stats(tl, segs),
    )
    return ds
