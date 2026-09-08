#!/usr/bin/env python3
"""Unit gate on the Socrates metric: standardization, clipping, and the gate.

These cases encode the bug that made a full floor sweep unreadable: the scorer
computed W on the raw response scale, so its output was compared against a
paper number defined on a [0,1] scale, and an out-of-range generation could move
the mean without bound. Run before any eval run.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fm_baselines"))

import numpy as np  # noqa: E402
from socrates_metric import (  # noqa: E402
    is_bare_numeric,
    parse_numeric,
    score,
    wasserstein_1d,
)


def _cell(humans, preds, study="s1", cond="1", task="1"):
    return [
        {
            "study_id": study,
            "condition_num": cond,
            "task_num": task,
            "human": h,
            "pred": p,
            "pred_raw": str(p),
        }
        for h, p in zip(humans, preds)
    ]


def test_perfect_match_is_zero():
    rows = _cell([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert score(rows)["wasserstein_mean"] == 0.0


def test_scale_invariance():
    """The paper metric must not care whether a scale is 1-5 or 1-100."""
    small = score(_cell([1, 2, 3, 4, 5], [2, 3, 4, 5, 5]))["wasserstein_mean"]
    big = score(_cell([20, 40, 60, 80, 100], [40, 60, 80, 100, 100]))[
        "wasserstein_mean"
    ]
    assert abs(small - big) < 1e-12, (small, big)


def test_out_of_range_is_clipped_and_bounded():
    """A base model answering '1997' on a 1-7 scale must not blow up the mean.

    This is the exact failure that produced a ~1e30 floor: unclipped
    standardization let one absurd generation dominate every cell it touched.
    """
    rows = _cell([1, 2, 3, 4, 5, 6, 7], [1997, 1997, 1997, 1997, 1997, 1997, 1997])
    w = score(rows)["wasserstein_mean"]
    assert np.isfinite(w) and 0.0 <= w <= 1.0, w


def test_score_is_bounded_on_unit_scale():
    rng = np.random.default_rng(0)
    for _ in range(50):
        h = rng.integers(1, 8, size=25)
        p = rng.integers(-500, 500, size=25)
        w = score(_cell(h.tolist(), p.tolist()))["wasserstein_mean"]
        assert w is None or (np.isfinite(w) and 0.0 <= w <= 1.0), w


def test_uniform_control_is_reported_and_beatable():
    rng = np.random.default_rng(1)
    h = rng.normal(4, 1, size=400).clip(1, 7)
    good = score(_cell(h.tolist(), (h + rng.normal(0, 0.1, 400)).tolist()))
    assert good["wasserstein_mean"] < good["uniform_control"], good


def test_degenerate_human_range_is_skipped_not_scored():
    rows = _cell([3, 3, 3, 3], [3, 3, 3, 3])
    out = score(rows)
    assert out["n_cells"] == 0
    assert out["skipped"]["degenerate_human_range"] == 1


def test_studies_are_averaged_unweighted():
    """One huge study must not outvote a small one."""
    rows = _cell([1, 2, 3, 4], [1, 2, 3, 4], study="a")
    rows += _cell([1] * 2 + [5] * 2, [5, 5, 1, 1], study="b", cond="9")
    out = score(rows)
    assert out["n_studies"] == 2
    expected = float(np.mean(list(out["per_study"].values())))
    assert abs(out["wasserstein_mean"] - expected) < 1e-12


def test_parse_diagnostics_flag_prose():
    rows = _cell([1, 2, 3], [1, 2, 3])
    rows[0]["pred_raw"] = "I would say about 1, because the scale suggests..."
    rows[1]["pred_raw"] = "2"
    rows[2]["pred_raw"] = "3"
    p = score(rows)["parse"]
    assert p["parse_rate"] == 1.0
    assert abs(p["bare_numeric_rate"] - 2 / 3) < 1e-12


def test_unparsed_predictions_lower_parse_rate():
    rows = _cell([1, 2, 3, 4], [1, 2, None, 4])
    rows[2]["pred_raw"] = "I cannot answer that."
    p = score(rows)["parse"]
    assert p["unparsed"] == 1
    assert p["parse_rate"] == 0.75


def test_parse_numeric_handles_real_generations():
    assert parse_numeric("5") == 5.0
    assert parse_numeric("Answer: 5") == 5.0
    assert parse_numeric(" 4.5 ") == 4.5
    assert parse_numeric("1,200") == 1200.0
    assert parse_numeric("-3") == -3.0
    assert parse_numeric("no number here") is None
    assert parse_numeric("") is None
    assert parse_numeric(None) is None


def test_is_bare_numeric():
    assert is_bare_numeric("5")
    assert is_bare_numeric(" 4.5 ")
    assert not is_bare_numeric("Answer: 5")
    assert not is_bare_numeric("")


def test_wasserstein_handles_unequal_sample_sizes():
    w = wasserstein_1d(np.array([0.0, 1.0]), np.array([0.0, 0.5, 1.0]))
    assert np.isfinite(w)


def main() -> int:
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
