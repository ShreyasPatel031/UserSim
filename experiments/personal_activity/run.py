"""Run the personal activity experiment end to end.

Real data (run locally, with your own gcloud login):

    python -m experiments.personal_activity.run --input gs://<bucket>/ --tz America/Los_Angeles
    python -m experiments.personal_activity.run --input ~/screenpipe-exports/

Synthetic fixture (CI / cloud, no real data):

    python -m experiments.personal_activity.run --input experiments/personal_activity/fixtures/synthetic

Writes report.md + results.json to --out (default experiments/personal_activity/out/<timestamp>/,
which is git-ignored). With a gcloud login, the LLM simulator calls Gemini on Vertex in your
gcloud project (context labels + times only, capped by --llm-budget-usd); --llm off disables it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .evaluate import run_all
from .llm_sim import GcloudVertex, LLMSimulator
from .loader import Config, load_timeline
from .report import render
from .tasks import build_dataset

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"


def _local_tz() -> str:
    try:
        tz = datetime.now().astimezone().tzinfo
        key = getattr(tz, "key", None)
        if key:
            return key
        link = Path("/etc/localtime").resolve()
        if "zoneinfo/" in str(link):
            return str(link).split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def _fixture_meta(spec: str) -> dict:
    p = Path(spec).expanduser()
    f = (p if p.is_dir() else p.parent) / "fixture.json"
    if not spec.startswith("gs://") and f.is_file():
        return json.loads(f.read_text())
    return {}


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="directory, activity_*.jsonl.gz file, or gs:// prefix")
    ap.add_argument("--out", default=None, help="output folder (default: out/<timestamp>, git-ignored)")
    ap.add_argument("--tz", default=None, help="IANA timezone for days and clock times (default: this machine's)")
    ap.add_argument("--label-mode", choices=["both", "app", "domain"], default="both")
    ap.add_argument("--idle-gap-min", type=float, default=5.0)
    ap.add_argument("--idle-horizon-min", type=float, default=10.0)
    ap.add_argument("--day-start-hour", type=int, default=4)
    ap.add_argument("--test-frac", type=float, default=0.3)
    ap.add_argument("--rollouts", type=int, default=100)
    ap.add_argument("--llm", choices=["auto", "off", "dry-run", "vertex"], default="auto",
                    help="auto (default): vertex if gcloud is logged in with a project, else dry-run | "
                         "off | dry-run: write prompts + cost estimate | vertex: call Gemini")
    ap.add_argument("--llm-project", default=None, help="GCP project for Vertex (default: gcloud config)")
    ap.add_argument("--llm-location", default="us-central1")
    ap.add_argument("--llm-model", default="gemini-2.5-flash")
    ap.add_argument("--llm-budget-usd", type=float, default=1.0)
    ap.add_argument("--llm-points", type=int, default=200, help="test switches sampled for the LLM")
    ap.add_argument("--llm-batch", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    meta_fx = _fixture_meta(a.input)
    tz = a.tz or meta_fx.get("tz") or _local_tz()
    cfg = Config(
        tz=tz,
        idle_gap_s=a.idle_gap_min * 60,
        idle_horizon_min=a.idle_horizon_min,
        day_start_hour=a.day_start_hour,
        label_mode=a.label_mode,
    )
    out = Path(a.out) if a.out else DEFAULT_OUT / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    print(f"[load] {a.input} (tz={tz})", flush=True)
    tl = load_timeline(a.input, cfg)
    print(f"[load] {tl.stats}", flush=True)
    ds = build_dataset(tl, a.test_frac)
    llm = None
    mode = a.llm
    caller = None
    if mode in ("auto", "vertex"):
        ok, why = GcloudVertex.available(a.llm_project)
        if ok:
            caller = GcloudVertex(a.llm_project, a.llm_location, a.llm_model)
            mode = "vertex"
            print(f"[llm] Vertex {a.llm_model} in project {caller.project} as {caller.account or '?'}; "
                  f"budget ${a.llm_budget_usd:.2f}. Sends context labels + times (no raw events).", flush=True)
        elif mode == "vertex":
            sys.exit(f"[llm] --llm vertex but {why}")
        else:
            mode = "dry-run"
            print(f"[llm] {why}; LLM runs as dry-run (prompts + cost estimate only)", flush=True)
    if mode != "off":
        llm = LLMSimulator(ds, mode=mode, caller=caller, budget_usd=a.llm_budget_usd, max_points=a.llm_points,
                           batch=a.llm_batch, out_dir=out, seed=a.seed)
    print(f"[eval] train {len(ds.train_days)} days, test {len(ds.test_days)} days, llm={mode}", flush=True)
    res = run_all(ds, rollouts=a.rollouts, llm=llm, seed=a.seed)

    meta = {
        "title": "synthetic fixture" if meta_fx.get("synthetic") else "local run",
        "synthetic": bool(meta_fx.get("synthetic")),
        "tz": tz,
        "data": tl.stats,
        "n_train": len(ds.train_days),
        "n_val": len(ds.val_days),
        "n_test": len(ds.test_days),
        "train_range": f"{ds.train_days[0]} – {ds.train_days[-1]}",
        "test_range": f"{ds.test_days[0]} – {ds.test_days[-1]}",
        "n_vocab": len(ds.vocab),
        "config": cfg.__dict__,
        "args": vars(a),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (out / "results.json").write_text(json.dumps({"meta": meta, "results": res}, indent=2, default=str))
    (out / "report.md").write_text(render(res, meta))
    print(f"[done] {out / 'report.md'} ({meta['seconds']}s)", flush=True)
    if "llm" in res:
        print(f"[llm] {res['llm']}", flush=True)
    return {"meta": meta, "results": res, "out": str(out)}


if __name__ == "__main__":
    main(sys.argv[1:])
