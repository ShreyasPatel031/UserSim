"""Smoke test of run_build.sh, compare_builds.py and promoted_margin.py on the synthetic dataset from test_build_v3.py.
Run: python -m pytest experiments/people_v2/test_run_build.py"""
import subprocess

import pandas as pd

from test_build_v3 import root  # noqa: F401  (pytest fixture)
from test_build_v3 import HERE


def _run(root, *args, env=None):
    import os
    return subprocess.run(["bash", str(HERE / "run_build.sh"), str(root), *args], capture_output=True, text=True,
                          env={**os.environ, "SKIP_TESTS": "1", **(env or {})})


def test_runner_builds_validates_compares_and_lists_promotions(root):  # noqa: F811
    first = _run(root, "b1")
    assert first.returncode == 0, first.stdout[-800:] + first.stderr[-800:]
    second = _run(root, "b2", str(root / "b1"))
    assert second.returncode == 0, second.stdout[-800:] + second.stderr[-800:]
    assert "rows.events: " in second.stdout and "handle rows that changed" in second.stdout  # identical inputs: the comparison runs and finds nothing changed
    assert "none" in second.stdout.split("handle rows that changed")[1].splitlines()[1] + second.stdout.split("handle rows that changed")[1].splitlines()[0]
    m = pd.read_csv(root / "b2" / "promoted_name_margin.csv")
    assert list(m.person_id) == ["ph:dana"] and float(m.sim.iloc[0]) >= 0.5  # the only qualifying dead-link person in the fixture
    assert (root / "b2" / "deltas.txt").read_text().startswith("rows.persons")


def test_runner_stops_with_exit_2_on_a_missing_input(root):  # noqa: F811
    (root / "x_lookup.json").unlink()
    r = _run(root, "b3")
    assert r.returncode == 2 and "MISSING INPUT: x_lookup.json" in r.stderr
