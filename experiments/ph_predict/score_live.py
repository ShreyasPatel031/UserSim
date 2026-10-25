"""Score a saved live prediction once PH's day has closed (after midnight PT).

Re-fetches the day (collect_ph.py) if it was fetched before the day closed, so ranks are final, then prints
recall@3/5/10 of out/live_<day><suffix>.csv.

    python experiments/ph_predict/score_live.py 2026-10-25 [_v2]
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features as F  # noqa: E402

HERE = Path(__file__).resolve().parent


def main(day: str, suffix: str = "") -> None:
    path = HERE / "cache" / "ph_days" / f"{day}.json"
    closed = datetime.fromisoformat(day).replace(tzinfo=F.PT) + timedelta(days=1)
    if path.exists() and datetime.fromisoformat(json.loads(path.read_text())["fetched_at"]) < closed:
        path.unlink()  # fetched mid-day: ranks not final
    if not path.exists():
        subprocess.run([sys.executable, str(HERE / "collect_ph.py"), day, day], check=True)
    actual = {e["node"]["id"]: e["node"]["dailyRank"] for e in json.loads(path.read_text())["edges"]}
    pred = pd.read_csv(HERE / "out" / f"live_{day}{suffix}.csv", dtype={"id": str})
    pred["actual_rank"] = pred.id.map(actual)
    truth = pred.dropna(subset=["actual_rank"]).nsmallest(10, "actual_rank")
    for k in (3, 5, 10):
        hit = len(set(truth.id[:k]) & set(pred.id[:k])) / k
        print(f"recall@{k}: {hit:.2f}  (random {k / len(pred):.2f})")
    print(pred[["predicted_rank", "actual_rank", "name", "predicted_at"]].to_string(index=False))


if __name__ == "__main__":
    main(*sys.argv[1:3])
