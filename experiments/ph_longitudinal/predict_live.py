"""Live prediction for one launch day, written before the results exist.

Uses the day's featured launches already collected (collect_ph.py <day> <day>), their crawls and LLM scores, and
a model trained on every earlier day. Saves out/live_<day>.csv (ranked) with the time it was made, so it can be
scored once PH's day closes.

    python experiments/ph_longitudinal/predict_live.py 2026-10-25
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate as E  # noqa: E402
import features as F  # noqa: E402


def main(day: str) -> None:
    df, X, groups = F.build()
    cols = [c for cs in groups.values() for c in cs]
    train, test = ((df.day < day) & df.complete).to_numpy(), (df.day == day).to_numpy()
    pred, _ = E.fit_predict(X[cols], np.log1p(df.votes), train, test)
    out = df[test][["id", "name", "tagline", "topics"]].assign(score=pred).sort_values("score", ascending=False)
    out.insert(0, "predicted_rank", range(1, len(out) + 1))
    out["predicted_at"] = datetime.now(F.PT).isoformat(timespec="seconds")
    E.OUT.mkdir(exist_ok=True)
    out.to_csv(E.OUT / f"live_{day}.csv", index=False)
    print(out.head(10)[["predicted_rank", "name", "tagline"]].to_string(index=False))


if __name__ == "__main__":
    main(sys.argv[1])
