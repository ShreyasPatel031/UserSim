"""python -m pytest experiments/pipeline/ph_upvotes/test_weekly_budget.py"""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("wb", pathlib.Path(__file__).with_name("weekly_budget.py"))
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)


def test_full_cap_when_nothing_spent():
    assert wb.remaining({}, "2026-11-10", cap=1.0) == 1.0


def test_sums_the_last_seven_days_including_today_and_ignores_older():
    s = {"2026-11-10": 0.1, "2026-11-04": 0.2, "2026-11-03": 5.0}  # 11-03 is 7 days back: outside the window
    assert wb.remaining(s, "2026-11-10", cap=1.0) == 0.7


def test_never_negative_when_overspent():
    assert wb.remaining({"2026-11-10": 3.0}, "2026-11-10", cap=1.0) == 0.0


def test_window_rolls_forward():
    s = {"2026-11-04": 0.9}
    assert wb.remaining(s, "2026-11-10", cap=1.0) == 0.1
    assert wb.remaining(s, "2026-11-11", cap=1.0) == 1.0
