"""Small, dependency-free metrics, plus a day-clustered paired bootstrap."""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Sequence


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def topk_hits(ranked: Sequence[str], truth: str, k: int) -> float:
    return 1.0 if truth in list(ranked)[:k] else 0.0


def log_err(pred: float, truth: float) -> float:
    """|log10 pred - log10 truth| with both clipped at 1 s."""
    return abs(math.log10(max(pred, 1.0)) - math.log10(max(truth, 1.0)))


def brier(p: float, y: bool | int) -> float:
    return (p - float(y)) ** 2


def logloss(p: float, y: bool | int) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -math.log(p if y else 1 - p)


def auc(scores: Sequence[float], ys: Sequence[bool | int]) -> float:
    """Mann-Whitney AUC with tie handling; nan when one class is missing."""
    pairs = sorted(zip(scores, ys), key=lambda x: x[0])
    n_pos = sum(1 for _, y in pairs if y)
    n_neg = len(pairs) - n_pos
    if not n_pos or not n_neg:
        return float("nan")
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        rank_sum += r * sum(1 for k in range(i, j + 1) if pairs[k][1])
        i = j + 1
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def tv_distance(p: dict[str, float], q: dict[str, float]) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def median(xs: Sequence[float], default: float = float("nan")) -> float:
    return statistics.median(xs) if xs else default


def quantile(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def paired_bootstrap(
    loss_a: Sequence[float],
    loss_b: Sequence[float],
    groups: Sequence[str],
    *,
    n_boot: int = 1000,
    seed: int = 0,
) -> dict[str, float]:
    """Mean(loss_a - loss_b) with a 90% CI, resampling whole days (clusters).

    Negative = A has lower loss than B."""
    by: dict[str, list[float]] = defaultdict(list)
    for a, b, g in zip(loss_a, loss_b, groups):
        by[g].append(a - b)
    keys = sorted(by)
    if not keys:
        return {"diff": float("nan"), "lo": float("nan"), "hi": float("nan"), "p_better": float("nan")}
    rng = random.Random(seed)
    sums = {k: (sum(v), len(v)) for k, v in by.items()}
    diff = sum(s for s, _ in sums.values()) / sum(n for _, n in sums.values())
    boots = []
    for _ in range(n_boot):
        pick = [keys[rng.randrange(len(keys))] for _ in keys]
        s = sum(sums[k][0] for k in pick)
        n = sum(sums[k][1] for k in pick)
        boots.append(s / n)
    boots.sort()
    return {
        "diff": diff,
        "lo": quantile(boots, 0.05),
        "hi": quantile(boots, 0.95),
        "p_better": sum(1 for b in boots if b < 0) / len(boots),
    }
