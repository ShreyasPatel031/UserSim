"""Trajectory-clustered bootstrap. Steps from the same task are not independent."""

from __future__ import annotations

import random
from collections import defaultdict


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def cluster_groups(rows: list[dict], key: str) -> dict[str, list[bool]]:
    groups: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        groups[row["annotation_id"]].append(bool(row[key]))
    return dict(groups)


def cluster_bootstrap_mean(
    rows: list[dict],
    key: str = "element_correct",
    n: int = 2000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Resample trajectories, then take all of their steps. Returns (mean, lo, hi)."""
    groups = cluster_groups(rows, key)
    ids = list(groups)
    point = mean([int(v) for g in groups.values() for v in g])
    if not ids:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sampled = [ids[rng.randrange(len(ids))] for _ in ids]
        vals = [int(v) for tid in sampled for v in groups[tid]]
        stats.append(mean(vals))
    stats.sort()
    lo = stats[int(0.025 * n)]
    hi = stats[min(len(stats) - 1, int(0.975 * n))]
    return point, lo, hi


def cluster_bootstrap_delta(
    rows_a: list[dict],
    rows_b: list[dict],
    key: str = "element_correct",
    n: int = 2000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Paired delta mean(A)-mean(B), resampling the same trajectories."""
    ga = cluster_groups(rows_a, key)
    gb = cluster_groups(rows_b, key)
    ids = sorted(set(ga) & set(gb))
    point = mean([int(v) for tid in ids for v in ga[tid]]) - mean(
        [int(v) for tid in ids for v in gb[tid]]
    )
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sampled = [ids[rng.randrange(len(ids))] for _ in ids]
        ma = mean([int(v) for tid in sampled for v in ga[tid]])
        mb = mean([int(v) for tid in sampled for v in gb[tid]])
        stats.append(ma - mb)
    stats.sort()
    lo = stats[int(0.025 * n)]
    hi = stats[min(len(stats) - 1, int(0.975 * n))]
    return point, lo, hi
