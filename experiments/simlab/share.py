"""Launch-level test of the person model as a CHOICE model: each person's day is shared out across that day's launches
(softmax of the person model's score), and shares are summed per launch. Person model = push.py frame features before
launch (no follows), trained on one month and applied to the other (Sep <-> Oct), so every day is out of sample.
Variants: with popularity in the person model, and without it (pure personal). Tested as a blend on the harness baseline.
Note: the people summed are those active that day (in the frame), which is launch-day knowledge; this is a feasibility
test before replacing them with the activity-weighted population.
usage: python -m simlab.share -> reports/share.json"""
import json, os
import numpy as np, pandas as pd
from . import harness as H
from .push import FRAME, fit, PRE, CAT

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    D = pd.read_parquet(FRAME)
    D["half"] = np.where(D.day < "2026-10-01", 0, 1)
    nopop = [c for c in PRE + CAT if c != "pop"]
    out = {}
    for name, cols in (("with popularity", PRE + CAT), ("personal only", nopop)):
        D[name] = np.nan
        for h in (0, 1):
            tr, te = D[D.half != h], D[D.half == h]
            D.loc[te.index, name] = fit(tr, te, cols)
        for T in (1.0, 0.3):
            z = np.log(D[name].clip(1e-6)) / T
            e = np.exp(z - z.groupby(D.g).transform("max"))
            out[f"{name} | T={T}"] = (e / e.groupby(D.g).transform("sum")).groupby(D.id).sum()
    S = pd.DataFrame(out).reset_index().rename(columns={"index": "id"})
    S.columns = ["id"] + [c.replace(" ", "_").replace("|", "").replace("=", "") for c in S.columns[1:]]
    rec = H.evaluate("person_choice_share", S, notes="Sep<->Oct cross-fitted person model; active people only (launch-day knowledge)")
    json.dump(rec, open(f"{HERE}/reports/share.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
