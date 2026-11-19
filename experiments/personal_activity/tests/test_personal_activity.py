"""End-to-end tests on the committed synthetic fixture (no real data, no network)."""

from __future__ import annotations

import asyncio
import gzip
import json
import re
from pathlib import Path

import pytest

from experiments.personal_activity import synth
from experiments.personal_activity.evaluate import run_all
from experiments.personal_activity.llm_sim import LLMSimulator, parse_day, parse_switch
from experiments.personal_activity.loader import Config, detect_calls, load_raw, list_inputs, load_timeline
from experiments.personal_activity.models import DayPred
from experiments.personal_activity.report import render
from experiments.personal_activity.run import main
from experiments.personal_activity.tasks import build_dataset

HERE = Path(__file__).resolve().parents[1]
FIXTURE = HERE / "fixtures" / "synthetic"
TZ = json.loads((FIXTURE / "fixture.json").read_text())["tz"]


@pytest.fixture(scope="module")
def ds():
    return build_dataset(load_timeline(str(FIXTURE), Config(tz=TZ)))


def test_fixture_schema_exact():
    keys = {
        "screen": {"kind", "ts", "app", "domain", "focused", "trigger"},
        "ui": {"kind", "ts", "event", "app", "domain", "button", "click_count", "text_len", "element_role"},
        "audio": {"kind", "ts", "source", "speech"},
    }
    files = list_inputs(str(FIXTURE))
    assert len(files) >= 3
    with gzip.open(files[0], "rt") as fh:
        for i, line in enumerate(fh):
            o = json.loads(line)
            assert set(o) == keys[o["kind"]]
            assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$", o["ts"])
            if i > 5000:
                break


def test_fixture_is_reproducible(tmp_path):
    meta = json.loads((FIXTURE / "fixture.json").read_text())
    from datetime import date

    synth.generate(tmp_path, start=date.fromisoformat(meta["start"]), weeks=meta["weeks"], tz=meta["tz"], seed=meta["seed"])
    for f in sorted(FIXTURE.glob("activity_*.jsonl.gz")):
        assert (tmp_path / f.name).read_bytes() == f.read_bytes(), f.name


def test_weekly_overlap_deduplicated():
    raw = load_raw(list_inputs(str(FIXTURE)))
    assert raw.n_duplicates > 0  # consecutive weekly files share a day
    keys = {(o["kind"], o["ts"], o.get("source"), o.get("event")) for o in raw.ui + raw.audio}
    assert len(keys) == len(raw.ui) + len(raw.audio)


def test_segments_and_calls(ds):
    tl = ds.timeline
    assert tl.stats["segments"] > 1000
    assert all(s.end > s.start for s in tl.segments)
    assert all(a.end <= b.start + 1e-6 for a, b in zip(tl.segments, tl.segments[1:]))
    # The fictional person has a 10:00 standup every weekday.
    weekdays = [d for d in ds.days.values() if not d.weekend]
    standup_slot = (10 - ds.cfg.day_start_hour) * 60 // ds.cfg.slot_min
    hit = sum(1 for d in weekdays if standup_slot in d.call_slots)
    assert hit >= 0.8 * len(weekdays)


def test_call_rule_needs_both_sides():
    cfg = Config()
    mic_only = [{"t": 1000.0 + 30 * i, "source": "mic", "speech": True} for i in range(10)]
    assert detect_calls(mic_only, cfg) == []
    both = mic_only + [{"t": 1001.0 + 30 * i, "source": "system", "speech": True} for i in range(10)]
    assert detect_calls(both, cfg)


def test_split_is_time_ordered(ds):
    assert max(ds.train_days) < min(ds.test_days)
    assert set(ds.val_days) <= set(ds.train_days)
    assert all(p.day in ds.test_days for p in ds.pts(ds.test_days))


def test_simulator_beats_naive_baselines(ds):
    res = run_all(ds, rollouts=20)
    m = res["metrics"]
    assert m["simulator"]["next_top3"] > m["most_frequent"]["next_top3"] + 0.1
    assert m["simulator"]["next_top3"] >= m["markov1"]["next_top3"]
    assert m["simulator"]["dwell_log_mae"] < m["most_frequent"]["dwell_log_mae"]
    assert m["simulator"]["call_auc"] > 0.6
    assert "next_top3" in res["simulator_vs_baselines"]


def _fake_caller(calls: list):
    async def call(prompt: str, system: str):
        calls.append(prompt)
        if "QUERIES" in prompt:
            labels = json.loads(re.search(r"ALLOWED CONTEXT LABELS: (\[.*?\])\n", prompt).group(1))
            qs = json.loads(prompt.split("QUERIES\n", 1)[1].split("\n", 1)[0])
            preds = [
                {"id": q["id"], "next": [l for l in labels if l != q["current"]][:3], "dwell_s": 90, "p_idle": 0.1}
                for q in qs
            ]
            js = {"predictions": preds}
        else:
            js = {"first_active": "08:45", "total_active_min": 420,
                  "shares": {"Cursor": 0.5, "Slack": 0.5}, "call_slots": {"10:00": 0.9}}
        return {"text": json.dumps(js), "json": js, "model": "fake",
                "usage": {"input_tokens": 1000, "output_tokens": 100, "cost_usd": 0.001}}

    return call


def test_llm_path_with_fake_caller(ds, tmp_path):
    calls: list = []
    llm = LLMSimulator(ds, mode="vertex", caller=_fake_caller(calls), max_points=40, batch=20, out_dir=tmp_path)
    res = run_all(ds, rollouts=10, llm=llm)
    assert res["llm"]["answered_points"] == 40
    assert res["llm"]["answered_days"] == len(ds.test_days)
    assert res["llm"]["calls"] == 2 + len(ds.test_days)
    assert "llm" in res["llm_subset"]["metrics"]
    assert "llm" in res["metrics"]
    md = render(res, {"data": ds.timeline.stats, "train_range": "a", "test_range": "b", "n_train": 1,
                      "n_val": 1, "n_test": 1, "n_vocab": 1, "tz": TZ})
    assert "simulator (LLM)" in md
    assert len(list((tmp_path / "llm_prompts").glob("*.txt"))) == len(calls)


def test_llm_budget_is_enforced(ds):
    calls: list = []
    llm = LLMSimulator(ds, mode="vertex", caller=_fake_caller(calls), budget_usd=0.0, max_points=40)
    res = run_all(ds, rollouts=5, llm=llm)
    assert calls == []
    assert res["llm"]["skipped_for_budget"] > 0


def test_parsers_reject_bad_output(ds):
    assert parse_switch({"predictions": [{"id": "x"}]}, ds.labels) == {}
    got = parse_switch({"predictions": [{"id": 3, "next": ["nope", ds.labels[0]], "dwell_s": "a", "p_idle": 7}]}, ds.labels)
    assert got[3] == {"next": [ds.labels[0]], "dwell_s": None, "p_idle": 1.0}
    fb = DayPred(500, 400, {"x": 1.0}, [0.01] * ds.n_slots)
    pred, ok = parse_day("not json", ds, fb)
    assert not ok and pred is fb
    pred, ok = parse_day({"first_active": "01:30", "total_active_min": 30}, ds, fb)
    assert ok and pred.first_min == 25 * 60 + 30  # after midnight belongs to the previous day


def test_cli_dry_run(tmp_path):
    out = main(["--input", str(FIXTURE), "--out", str(tmp_path), "--llm", "dry-run", "--rollouts", "5"])
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "results.json").is_file()
    assert out["results"]["llm"]["estimated_cost_usd"] < 1.0  # stays in the repo's ~$1 band
    assert list((tmp_path / "llm_prompts").glob("*_switch.txt"))
