"""Baselines and the classical personal simulator.

Switch-level models are fit on train days only and see, at prediction time,
just what happened earlier that day (current context, previous context, recent
history, clock time). Day-level models are day-ahead: for test day d they may
use every observed day before d.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from .metrics import median, quantile
from .tasks import Dataset, DayStats, SwitchPoint, hour_bucket

Dist = dict[str, float]

# --------------------------------------------------------------------------- helpers


def _norm(c: Counter | Dist, labels: Sequence[str], exclude: str | None = None) -> Dist:
    tot = sum(v for k, v in c.items() if k != exclude)
    if tot <= 0:
        return {}
    return {k: v / tot for k, v in c.items() if k != exclude and v > 0}


def _smooth(c: Counter, prior: Dist, alpha: float, exclude: str | None) -> Dist:
    """Dirichlet smoothing toward ``prior``; ``exclude`` (the current context)
    gets zero mass because the next context is by definition different."""
    n = sum(v for k, v in c.items() if k != exclude)
    pr = {k: v for k, v in prior.items() if k != exclude}
    z = sum(pr.values()) or 1.0
    out = {k: alpha * v / z for k, v in pr.items()}
    for k, v in c.items():
        if k != exclude:
            out[k] = out.get(k, 0.0) + v
    tot = n + alpha
    return {k: v / tot for k, v in out.items()}


def rank(d: Dist, fill: Sequence[str] = (), exclude: str | None = None) -> list[str]:
    out = [k for k, _ in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])) if k != exclude]
    seen = set(out)
    out += [k for k in fill if k not in seen and k != exclude]
    return out


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


class Logistic:
    """Plain L2 logistic regression (batch gradient descent, standardized X)."""

    def __init__(self, l2: float = 1e-2, iters: int = 400, lr: float = 0.5):
        self.l2, self.iters, self.lr = l2, iters, lr
        self.w: list[float] = []
        self.mu: list[float] = []
        self.sd: list[float] = []
        self.const: float | None = None

    def fit(self, X: list[list[float]], y: list[int]) -> "Logistic":
        if not X or len(set(y)) < 2:
            self.const = (sum(y) + 1) / (len(y) + 2) if y else 0.5
            return self
        d = len(X[0])
        self.mu = [sum(r[j] for r in X) / len(X) for j in range(d)]
        self.sd = [
            math.sqrt(sum((r[j] - self.mu[j]) ** 2 for r in X) / len(X)) or 1.0 for j in range(d)
        ]
        Z = [[(r[j] - self.mu[j]) / self.sd[j] for j in range(d)] + [1.0] for r in X]
        w = [0.0] * (d + 1)
        n = len(Z)
        for _ in range(self.iters):
            g = [0.0] * (d + 1)
            for z, t in zip(Z, y):
                p = _sigmoid(sum(a * b for a, b in zip(w, z)))
                e = p - t
                for j in range(d + 1):
                    g[j] += e * z[j]
            for j in range(d + 1):
                reg = self.l2 * w[j] if j < d else 0.0
                w[j] -= self.lr * (g[j] / n + reg)
        self.w = w
        return self

    def predict(self, x: list[float]) -> float:
        if self.const is not None:
            return self.const
        z = [(x[j] - self.mu[j]) / self.sd[j] for j in range(len(x))] + [1.0]
        return _sigmoid(sum(a * b for a, b in zip(self.w, z)))


def _ols(X: list[list[float]], y: list[float], ridge: float = 1e-3) -> list[float]:
    """Least squares with an intercept column appended; tiny ridge for stability."""
    A = [r + [1.0] for r in X]
    d = len(A[0])
    M = [[sum(a[i] * a[j] for a in A) + (ridge if i == j and i < d - 1 else 0.0) for j in range(d)] for i in range(d)]
    v = [sum(a[i] * t for a, t in zip(A, y)) for i in range(d)]
    # Gaussian elimination
    for c in range(d):
        piv = max(range(c, d), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        v[c], v[piv] = v[piv], v[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(d):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, d):
                    M[r][k] -= f * M[c][k]
                v[r] -= f * v[c]
    return [v[i] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(d)]


# --------------------------------------------------------------------------- switch-level stats


@dataclass
class SwitchStats:
    """Counts from a set of switch points (one per segment)."""

    glob: Counter
    m1: dict[str, Counter]
    m2: dict[tuple[str, str], Counter]
    hour: dict[int, Counter]
    hour_cur: dict[tuple[int, str], Counter]
    dwell_all: list[float]
    dwell_lab: dict[str, list[float]]
    dwell_lab_hb: dict[tuple[str, int], list[float]]
    dwell_hb: dict[int, list[float]]
    idle_all: list[int]
    idle_lab: dict[str, list[int]]
    idle_hb: dict[int, list[int]]
    idle_lab_hb: dict[tuple[str, int], list[int]]
    first_lab_hb: dict[int, Counter]

    @classmethod
    def fit(cls, pts: Iterable[SwitchPoint]) -> "SwitchStats":
        st = cls(Counter(), defaultdict(Counter), defaultdict(Counter), defaultdict(Counter),
                 defaultdict(Counter), [], defaultdict(list), defaultdict(list), defaultdict(list),
                 [], defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(Counter))
        for p in pts:
            st.dwell_all.append(p.dur)
            st.dwell_lab[p.cur].append(p.dur)
            st.dwell_lab_hb[(p.cur, p.hb)].append(p.dur)
            st.dwell_hb[p.hb].append(p.dur)
            y = int(p.idle_soon)
            st.idle_all.append(y)
            st.idle_lab[p.cur].append(y)
            st.idle_hb[p.hb].append(y)
            st.idle_lab_hb[(p.cur, p.hb)].append(y)
            if p.first_in_session:
                st.first_lab_hb[p.hb][p.cur] += 1
            if p.next is None:
                continue
            st.glob[p.next] += 1
            st.m1[p.cur][p.next] += 1
            st.m2[(p.prev or "<s>", p.cur)][p.next] += 1
            st.hour[p.hb][p.next] += 1
            st.hour_cur[(p.hb, p.cur)][p.next] += 1
        return st

    def rate(self, ys: list[int], prior: float, k: float = 5.0) -> float:
        return (sum(ys) + k * prior) / (len(ys) + k)

    @property
    def base_idle(self) -> float:
        return (sum(self.idle_all) + 1) / (len(self.idle_all) + 2)

    @property
    def med_dwell(self) -> float:
        return median(self.dwell_all, 60.0)


# --------------------------------------------------------------------------- baselines (switch)


class SwitchBaselines:
    """most-frequent, last-value, first-order Markov, time-of-day prior."""

    NAMES = ("most_frequent", "last_value", "markov1", "time_of_day")

    def __init__(self, ds: Dataset, train_pts: list[SwitchPoint]):
        self.st = SwitchStats.fit(train_pts)
        self.fill = rank(_norm(self.st.glob, ds.labels)) + [l for l in ds.labels]

    # next context ----------------------------------------------------------
    def next_rank(self, name: str, p: SwitchPoint) -> list[str]:
        st = self.st
        if name == "most_frequent":
            return rank({}, self.fill, p.cur)
        if name == "last_value":  # repeat: go back to where you came from
            return rank({p.prev: 1.0} if p.prev else {}, self.fill, p.cur)
        if name == "markov1":
            return rank(_norm(st.m1.get(p.cur, Counter()), []), self.fill, p.cur)
        if name == "time_of_day":
            return rank(_norm(st.hour.get(p.hb, Counter()), []), self.fill, p.cur)
        raise KeyError(name)

    # dwell -----------------------------------------------------------------
    def dwell(self, name: str, p: SwitchPoint) -> float:
        st = self.st
        g = st.med_dwell
        if name == "most_frequent":
            return g
        if name == "last_value":
            return p.prev_dur if p.prev_dur else g
        if name == "markov1":  # per-context median
            return median(st.dwell_lab.get(p.cur, []), g)
        if name == "time_of_day":
            return median(st.dwell_hb.get(p.hb, []), g)
        raise KeyError(name)

    # idle ------------------------------------------------------------------
    def p_idle(self, name: str, p: SwitchPoint) -> float | None:
        st = self.st
        b = st.base_idle
        if name == "most_frequent":
            return b
        if name == "last_value":
            return None  # no sensible "repeat" for this target
        if name == "markov1":
            return st.rate(st.idle_lab.get(p.cur, []), b)
        if name == "time_of_day":
            return st.rate(st.idle_hb.get(p.hb, []), b)
        raise KeyError(name)


# --------------------------------------------------------------------------- simulator


COMPONENTS = ("glob", "m1", "m2", "hour", "hour_cur", "recent")


class PersonalSimulator:
    """A fitted generative model of one person's switching behaviour.

    next context: mixture of global, first-order, second-order, time-of-day,
      time-of-day x current and a recency kernel (contexts used earlier today);
      mixture weights tuned on the validation tail of the train days.
    dwell: log-linear model on context median, context x time-of-day median and
      the previous dwell.
    idle: logistic model on smoothed idle rates (context, time of day, both),
      time in session and dwell priors.
    day rollout: Monte-Carlo simulation of a whole day from the same parts.
    """

    def __init__(self, ds: Dataset, alpha: float = 2.0, recency_s: float = 1200.0):
        self.ds = ds
        self.labels = ds.labels
        self.alpha = alpha
        self.recency_s = recency_s
        self.lam: dict[str, float] = {c: 1 / len(COMPONENTS) for c in COMPONENTS}
        self.st: SwitchStats | None = None
        self.dwell_w: list[float] = [1.0, 0.0, 0.0, 0.0]
        self.idle_lr: Logistic | None = None

    # ----------------------------------------------------------------- fitting
    def fit(self, train_pts: list[SwitchPoint], val_days: Sequence[str] = ()) -> "PersonalSimulator":
        vd = set(val_days)
        if vd:
            fit_pts = [p for p in train_pts if p.day not in vd]
            val_pts = [p for p in train_pts if p.day in vd]
            if fit_pts and val_pts:
                self.st = SwitchStats.fit(fit_pts)
                self._tune_lambda([p for p in val_pts if p.next])
        self.st = SwitchStats.fit(train_pts)
        self._fit_dwell(train_pts)
        # In-sample rates as features; they are smoothed, and a 3-5 day
        # validation tail is too small to fit the logistic on its own.
        self._fit_idle(train_pts)
        return self

    def components(self, p: SwitchPoint, recent=None) -> dict[str, Dist]:
        st = self.st
        a = self.alpha
        glob = _smooth(st.glob, {l: 1.0 for l in self.labels}, 1.0, p.cur)
        out = {
            "glob": glob,
            "m1": _smooth(st.m1.get(p.cur, Counter()), glob, a, p.cur),
            "m2": _smooth(st.m2.get((p.prev or "<s>", p.cur), Counter()), glob, a, p.cur),
            "hour": _smooth(st.hour.get(p.hb, Counter()), glob, a, p.cur),
            "hour_cur": _smooth(st.hour_cur.get((p.hb, p.cur), Counter()), glob, a, p.cur),
        }
        rec: Counter = Counter()
        for lab, t0, _d in (recent if recent is not None else p.recent):
            age = max(0.0, p.t - t0)
            rec[lab] += math.exp(-age / self.recency_s)
        out["recent"] = _smooth(rec, glob, 0.5, p.cur)
        return out

    def next_dist(self, p: SwitchPoint, recent=None) -> Dist:
        comps = self.components(p, recent)
        out: Dist = defaultdict(float)
        for c, w in self.lam.items():
            if w <= 0:
                continue
            for k, v in comps[c].items():
                out[k] += w * v
        return dict(out)

    def next_rank(self, p: SwitchPoint) -> list[str]:
        return rank(self.next_dist(p), self.labels, p.cur)

    def _tune_lambda(self, val_pts: list[SwitchPoint], step: float = 0.2) -> None:
        if not val_pts:
            return
        comps = [self.components(p) for p in val_pts]
        truth = [p.next for p in val_pts]
        k = len(COMPONENTS)
        n = round(1 / step)
        best, best_ll = None, -1e18
        for combo in itertools.product(range(n + 1), repeat=k - 1):
            if sum(combo) > n:
                continue
            ws = [c * step for c in combo] + [1 - sum(combo) * step]
            ll = 0.0
            for cp, y in zip(comps, truth):
                pr = sum(w * cp[c].get(y, 0.0) for w, c in zip(ws, COMPONENTS))
                ll += math.log(max(pr, 1e-6))
            if ll > best_ll:
                best, best_ll = ws, ll
        self.lam = dict(zip(COMPONENTS, best))

    # ----------------------------------------------------------------- dwell
    def _dwell_x(self, p: SwitchPoint) -> list[float]:
        st = self.st
        g = st.med_dwell
        lab = median(st.dwell_lab.get(p.cur, []), g)
        lh = st.dwell_lab_hb.get((p.cur, p.hb), [])
        lab_hb = median(lh, lab) if len(lh) >= 8 else lab
        prev = p.prev_dur if p.prev_dur else g
        return [math.log(max(lab, 1)), math.log(max(lab_hb, 1)), math.log(max(prev, 1))]

    def _fit_dwell(self, pts: list[SwitchPoint]) -> None:
        X = [self._dwell_x(p) for p in pts]
        y = [math.log(max(p.dur, 1)) for p in pts]
        self.dwell_w = _ols(X, y) if len(pts) > 10 else [1.0, 0.0, 0.0, 0.0]

    def dwell(self, p: SwitchPoint) -> float:
        x = self._dwell_x(p) + [1.0]
        return math.exp(sum(a * b for a, b in zip(self.dwell_w, x)))

    # ----------------------------------------------------------------- idle
    def _idle_x(self, p: SwitchPoint) -> list[float]:
        st = self.st
        b = st.base_idle
        lab = st.rate(st.idle_lab.get(p.cur, []), b)
        hb = st.rate(st.idle_hb.get(p.hb, []), b)
        both = st.rate(st.idle_lab_hb.get((p.cur, p.hb), []), hb)
        return [
            _logit(lab),
            _logit(hb),
            _logit(both),
            math.log1p(p.time_in_session / 60),
            math.log(max(median(st.dwell_lab.get(p.cur, []), st.med_dwell), 1)),
            1.0 if p.first_in_session else 0.0,
        ]

    def _fit_idle(self, pts: list[SwitchPoint]) -> None:
        X = [self._idle_x(p) for p in pts]
        self.idle_lr = Logistic().fit(X, [int(p.idle_soon) for p in pts])

    def p_idle(self, p: SwitchPoint) -> float:
        return self.idle_lr.predict(self._idle_x(p))


# --------------------------------------------------------------------------- day-level


def _day_type_pool(hist: list[DayStats], weekend: bool) -> list[DayStats]:
    same = [d for d in hist if d.weekend == weekend]
    return same if len(same) >= 2 else hist


def _mean_shares(days: list[DayStats]) -> Dist:
    c: Counter = Counter()
    for d in days:
        for k, v in d.shares.items():
            c[k] += v / len(days)
    return dict(c)


@dataclass
class DayPred:
    first_min: float
    active_min: float
    shares: Dist
    call_p: list[float]  # per slot
    first_iv: tuple[float, float] | None = None  # 80% interval (simulator only)
    active_iv: tuple[float, float] | None = None


def slot_rate(hist: list[DayStats], slot: int, prior: float, k: float = 2.0) -> float:
    n = len(hist)
    hits = sum(1 for d in hist if slot in d.call_slots)
    return (hits + k * prior) / (n + k)


def base_call_rate(hist: list[DayStats], n_slots: int) -> float:
    if not hist:
        return 0.02
    return (sum(len(d.call_slots) for d in hist) + 1) / (len(hist) * n_slots + 2)


class DayBaselines:
    NAMES = ("most_frequent", "last_value", "time_of_day")

    def __init__(self, n_slots: int):
        self.n_slots = n_slots

    def predict(self, name: str, hist: list[DayStats], weekday: int) -> DayPred:
        base = base_call_rate(hist, self.n_slots)
        if name == "most_frequent":  # pooled median day, flat call rate
            return DayPred(
                median([d.first_min for d in hist]),
                median([d.active_min for d in hist]),
                _mean_shares(hist),
                [base] * self.n_slots,
            )
        if name == "last_value":  # yesterday (last observed day) again
            y = hist[-1]
            return DayPred(y.first_min, y.active_min, dict(y.shares),
                           [1.0 if s in y.call_slots else 0.0 for s in range(self.n_slots)])
        if name == "time_of_day":  # same day type (weekday/weekend), per-slot call rate
            pool = _day_type_pool(hist, weekday >= 5)
            return DayPred(
                median([d.first_min for d in pool]),
                median([d.active_min for d in pool]),
                _mean_shares(pool),
                [slot_rate(pool, s, base_call_rate(pool, self.n_slots)) for s in range(self.n_slots)],
            )
        raise KeyError(name)


class CallModel:
    """Logistic model for P(call in slot) from day-ahead features."""

    def __init__(self, n_slots: int):
        self.n_slots = n_slots
        self.lr = Logistic(l2=0.05)

    def features(self, hist: list[DayStats], weekday: int, slot: int) -> list[float]:
        pool = _day_type_pool(hist, weekday >= 5)
        base = base_call_rate(pool, self.n_slots)
        same_wd = [d for d in hist if d.weekday == weekday]
        r_type = slot_rate(pool, slot, base)
        r_wd = slot_rate(same_wd, slot, r_type, k=1.0)
        r_nb = 0.5 * (slot_rate(pool, slot - 1, base) + slot_rate(pool, slot + 1, base))
        last = 1.0 if hist and slot in hist[-1].call_slots else 0.0
        recent = hist[-5:]
        r_recent = slot_rate(recent, slot, r_type)
        return [_logit(r_type), _logit(r_wd), _logit(r_nb), last, _logit(r_recent), _logit(base)]

    def fit(self, days: list[DayStats], min_hist: int = 3) -> "CallModel":
        X, y = [], []
        for i in range(min_hist, len(days)):
            hist, d = days[:i], days[i]
            for s in range(self.n_slots):
                X.append(self.features(hist, d.weekday, s))
                y.append(int(s in d.call_slots))
        self.lr.fit(X, y)
        return self

    def predict(self, hist: list[DayStats], weekday: int) -> list[float]:
        return [self.lr.predict(self.features(hist, weekday, s)) for s in range(self.n_slots)]


class DayRollout:
    """Monte-Carlo day simulation.

    Each rollout picks a past day of the same type (weekday/weekend) for the
    session schedule (when the person is at the computer), then fills every
    session with contexts and dwell times sampled from the fitted switching
    model. Medians over rollouts are the point prediction; 10-90% quantiles
    give an 80% interval."""

    def __init__(self, sim: PersonalSimulator, n: int = 100, seed: int = 0):
        self.sim = sim
        self.n = n
        self.seed = seed

    def _dwell(self, rng: random.Random, cur: str, hb: int) -> float:
        st = self.sim.st
        durs = st.dwell_lab_hb.get((cur, hb))
        if not durs or len(durs) < 8:
            durs = st.dwell_lab.get(cur) or st.dwell_all or [60.0]
        return rng.choice(durs)

    def predict(self, hist: list[DayStats], weekday: int, day_origin: float, call_p: list[float]) -> DayPred:
        rng = random.Random(self.seed * 1009 + weekday)
        pool = _day_type_pool(hist, weekday >= 5)
        st = self.sim.st
        firsts, actives, shares = [], [], []
        for _ in range(self.n):
            proto = rng.choice(pool)
            sh: Counter = Counter()
            recent: list[tuple[str, float, float]] = []
            for s_min, e_min in proto.sessions:
                t, end = day_origin + s_min * 60, day_origin + e_min * 60
                hour = (s_min / 60) % 24
                fc = st.first_lab_hb.get(hour_bucket(hour, weekday)) or st.glob
                cur = rng.choices(list(fc), weights=list(fc.values()))[0]
                prev, prev_dur, t_sess = None, None, t
                while t < end:
                    hour = ((t - day_origin) / 3600) % 24
                    hb = hour_bucket(hour, weekday)
                    d = min(self._dwell(rng, cur, hb), end - t)
                    sh[cur] += d
                    p = SwitchPoint(0, "", t, hour, weekday, cur, prev, prev_dur, recent[-8:],
                                    t - t_sess, t == t_sess, 0.0, None, False)
                    recent.append((cur, t, d))
                    t += d
                    if t >= end:
                        break
                    dist = self.sim.next_dist(p, recent[-8:])
                    prev, prev_dur = cur, d
                    cur = rng.choices(list(dist), weights=list(dist.values()))[0]
            firsts.append(proto.first_min)
            actives.append(proto.active_min)
            tot = sum(sh.values()) or 1.0
            shares.append({k: v / tot for k, v in sh.items()})
        mean_sh: Counter = Counter()
        for s in shares:
            for k, v in s.items():
                mean_sh[k] += v / len(shares)
        return DayPred(
            median(firsts),
            median(actives),
            dict(mean_sh),
            call_p,
            (quantile(firsts, 0.1), quantile(firsts, 0.9)),
            (quantile(actives, 0.1), quantile(actives, 0.9)),
        )
