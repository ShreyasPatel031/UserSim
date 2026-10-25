"""Score a saved live prediction once PH's day has closed (after midnight PT).

Re-fetches the day (collect_ph.py) so ranks are final, then prints recall@3/5/10 of out/live_<day>.csv.

    python experiments/ph_predict/score_live.py 2026-10-25
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main(day: str) -> None:
    path = HERE / "cache" / "ph_days" / f"{day}.json"
    path.unlink(missing_ok=True)
    subprocess.run([sys.executable, str(HERE / "collect_ph.py"), day, day], check=True)
    actual = {e["node"]["id"]: e["node"]["dailyRank"] for e in json.loads(path.read_text())["edges"]}
    pred = pd.read_csv(HERE / "out" / f"live_{day}.csv", dtype={"id": str})
    pred["actual_rank"] = pred.id.map(actual)
    truth = pred.dropna(subset=["actual_rank"]).nsmallest(10, "actual_rank")
    for k in (3, 5, 10):
        hit = len(set(truth.id[:k]) & set(pred.id[:k])) / k
        print(f"recall@{k}: {hit:.2f}  (random {k / len(pred):.2f})")
    print(pred[["predicted_rank", "actual_rank", "name", "predicted_at"]].to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
