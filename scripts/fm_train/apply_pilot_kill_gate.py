#!/usr/bin/env python3
"""Apply the pre-registered GO/STOP kill gate for the 8B-Base SFT pilot.

Floor (Qwen3-8B-Base zero-shot):
  Beauty Contest win  4.8%
  Single-round game avg W  15.4
  Survey Acc ~27%  (collapse if worse than floor - 5pp)

GO if either:
  Beauty Contest win >= 15%
  OR single-round game avg W <= 11.0
AND survey Acc not worse than floor - 5pp.

STOP if both stay in STOP band:
  Beauty Contest win < 8%
  AND single-round game avg W > 14.0
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FLOOR = {
    "beauty_win": 0.048,
    "game_w": 15.4,
    "survey_acc": 0.27,
}
GO = {"beauty_win": 0.15, "game_w": 11.0}
STOP = {"beauty_win": 0.08, "game_w": 14.0}
SURVEY_COLLAPSE_PP = 0.05


def decide(beauty_win: float, game_w: float, survey_acc: float | None) -> dict:
    go_beauty = beauty_win >= GO["beauty_win"]
    go_w = game_w <= GO["game_w"]
    stop_beauty = beauty_win < STOP["beauty_win"]
    stop_w = game_w > STOP["game_w"]
    survey_ok = True
    if survey_acc is not None:
        survey_ok = survey_acc >= (FLOOR["survey_acc"] - SURVEY_COLLAPSE_PP)

    if (go_beauty or go_w) and survey_ok:
        verdict = "GO"
        reason = []
        if go_beauty:
            reason.append(f"beauty_win {beauty_win:.3f} >= {GO['beauty_win']}")
        if go_w:
            reason.append(f"game_w {game_w:.3f} <= {GO['game_w']}")
    elif stop_beauty and stop_w:
        verdict = "STOP"
        reason = [
            f"beauty_win {beauty_win:.3f} < {STOP['beauty_win']}",
            f"game_w {game_w:.3f} > {STOP['game_w']}",
        ]
    else:
        verdict = "BORDERLINE"
        reason = [
            "neither GO nor STOP band fully satisfied; inspect before scaling",
        ]
    if survey_acc is not None and not survey_ok:
        verdict = "STOP"
        reason.append(
            f"survey Acc collapsed: {survey_acc:.3f} < "
            f"{FLOOR['survey_acc'] - SURVEY_COLLAPSE_PP:.3f}"
        )

    return {
        "verdict": verdict,
        "reason": reason,
        "metrics": {
            "beauty_win": beauty_win,
            "game_w": game_w,
            "survey_acc": survey_acc,
        },
        "floor": FLOOR,
        "thresholds": {"GO": GO, "STOP": STOP},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_from_summary(path: Path) -> tuple[float, float, float | None]:
    data = json.loads(path.read_text())
    if "beauty_win" in data and "game_w" in data:
        beauty = float(data["beauty_win"])
        game_w = float(data["game_w"])
        survey = float(data["survey_acc"]) if data.get("survey_acc") is not None else None
        if beauty > 1.0:
            beauty /= 100.0
        return beauty, game_w, survey

    beauty = None
    game_ws: list[float] = []
    survey = None

    def walk(obj, path_keys: tuple[str, ...] = ()):
        nonlocal beauty, survey
        if isinstance(obj, dict):
            keys = {k.lower(): k for k in obj}
            for cand in ("win_rate", "beauty_win", "guessing_winrate", "winrate"):
                if cand in keys and beauty is None:
                    try:
                        beauty = float(obj[keys[cand]])
                    except (TypeError, ValueError):
                        pass
            for cand in ("wasserstein", "w", "w_avg", "avg_w"):
                if cand in keys:
                    try:
                        game_ws.append(float(obj[keys[cand]]))
                    except (TypeError, ValueError):
                        pass
            for cand in ("accuracy", "acc", "survey_acc"):
                if cand in keys and survey is None:
                    joined = "/".join(path_keys).lower()
                    if "surv" in joined or "survey" in joined or cand == "survey_acc":
                        try:
                            survey = float(obj[keys[cand]])
                        except (TypeError, ValueError):
                            pass
            for k, v in obj.items():
                walk(v, path_keys + (str(k),))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, path_keys + (str(i),))

    walk(data)
    if beauty is None or not game_ws:
        raise SystemExit(
            f"could not extract beauty_win / game_w from {path}; "
            "pass --beauty-win / --game-w explicitly"
        )
    if beauty > 1.0:
        beauty /= 100.0
    return beauty, sum(game_ws) / len(game_ws), survey


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot-summary", type=Path, default=None)
    ap.add_argument("--beauty-win", type=float, default=None)
    ap.add_argument("--game-w", type=float, default=None)
    ap.add_argument("--survey-acc", type=float, default=None)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "fm_train" / "pilot_kill_gate.json",
    )
    args = ap.parse_args()

    if args.pilot_summary:
        beauty, game_w, survey = extract_from_summary(args.pilot_summary)
        if args.beauty_win is not None:
            beauty = args.beauty_win
        if args.game_w is not None:
            game_w = args.game_w
        if args.survey_acc is not None:
            survey = args.survey_acc
    else:
        if args.beauty_win is None or args.game_w is None:
            raise SystemExit("need --pilot-summary or both --beauty-win and --game-w")
        beauty, game_w, survey = args.beauty_win, args.game_w, args.survey_acc

    result = decide(beauty, game_w, survey)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["verdict"] == "STOP":
        raise SystemExit(2)
    if result["verdict"] == "BORDERLINE":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
