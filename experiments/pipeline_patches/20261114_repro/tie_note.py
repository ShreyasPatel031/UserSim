"""Tie note for the 00:05 why file (orchestrator 15:47Z Nov 14; undeployed). Counts only.
When the published model's scores at the cut pairs 3|4, 5|6 or 10|11 are within TIE log-votes, the order across that cut is close to a coin
flip. Measured on the 183-day backtest (days with >= 10 ranked): top 3 accuracy 51% on days with a 3|4 tie vs 59% on clear days.
Reads the forecast parquet the 00:05 run writes (VM: ~/w/experiments/ph_predict/results/forecast_<d>.parquet; score = pred_arm2 when
published, else pred)."""
import json, sys
import pandas as pd

TIE = 0.019; CUTS = (3, 5, 10)
MEASURED = "On past days with a tie at the 3rd/4th place, the top 3 was right 51% of the time vs 59% on clear days (183-day backtest)."


def tie_note(parquet):
    F = pd.read_parquet(parquet); col = "pred_arm2" if "pred_arm2" in F and F.pred_arm2.notna().all() else "pred"
    s = F.sort_values([col, "id"], ascending=[False, True])[col].tolist(); out = []
    for k in CUTS:
        if len(s) > k and s[k - 1] - s[k] < TIE:
            out.append({"between": [k, k + 1], "gap_log_votes": round(float(s[k - 1] - s[k]), 4)})
    return {"label": "Close calls", "model_scored": col, "threshold_log_votes": TIE, "ties": out,
            "text": ("Picks " + ", ".join(f"{a} and {b}" for a, b in (t["between"] for t in out)) + " are near-ties; their order could easily swap. " + MEASURED) if out else None}


if __name__ == "__main__":
    print(json.dumps(tie_note(sys.argv[1])))
