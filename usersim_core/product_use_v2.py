"""Drop-in replacement scorer for live `product_use` nightly pipeline (`usersim_core.product_use_v2`).

Fixes the 4 critical bugs identified in the Nov 25 audit of `experiments/simlab/product_use/{runner,score}.py`:
  1. Preserves frozen `arm3` structural score (`final = score_arm3 + clip(eta * z_sim, -max_shift, +max_shift)`)
     instead of sorting 100% by `-sim_score` and throwing away `arm3` (`-27` to `-40` pt regression).
  2. Assigns `0.0` residual shift (neutral) when a launch or its competitors hit harness access errors
     (`signup_wall`, `captcha`, `block`, `js_only`, `timeout`, `engine`, `no_url`) instead of median-imputing
     or halving `sim_score` by `0.5x` when competitors fail to load.
  3. Retains competitor comparison reasons and product-intrinsic traits (`instant_demo`, `free_tier`,
     `waitlist_only`, `card_required`) separately from harness access failures.
  4. Debiases slot presentation order (`Product A/B/C`) across cohort users.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from usersim_core.schema import ACCESS_FAILURES


def score_live_product_use_lineup(
    arm3_launches: list[dict],
    cua_debriefs: dict[str, list[dict]],
    eta: float = 0.28,
    max_shift: float = 0.40,
) -> pd.DataFrame:
    """Combine frozen `arm3` 00:05 PT lineup scores with live CUA session debriefs safely.

    Parameters
    ----------
    arm3_launches : list of dicts with `id`, `name`, `structural_score`, `structural_rank`
    cua_debriefs  : mapping `launch_id -> list of per-user debrief dicts` from CUA sessions
    eta           : shrinkage weight applied to within-day z-scored clean CUA utility signal
    max_shift     : hard cap on log-vote score adjustment so single noisy traces cannot invert top locks
    """
    rows = []
    for l in arm3_launches:
        lid = str(l["id"])
        s_score = float(l["structural_score"])
        s_rank = int(l["structural_rank"])
        debriefs = cua_debriefs.get(lid, [])

        # Keep only sessions where the TARGET launch itself had clean access (never penalize competitor failures!)
        clean_sessions = [
            d for d in debriefs
            if str(d.get("target_artefact") or d.get("access_status") or "none") in ("none", "clean")
        ]
        if len(clean_sessions) == 0:
            rows.append({
                "item_id": lid,
                "name": str(l.get("name") or ""),
                "structural_score": s_score,
                "structural_rank": s_rank,
                "clean_cua_n": 0,
                "raw_cua_utility": np.nan,
                "access_clean": False,
            })
            continue

        vals = []
        for d in clean_sessions:
            comp = float(d.get("completion", 0.5))
            wu = float(d.get("would_use", 0.5))
            # Competitor win bonus ONLY when at least 1 competitor also loaded cleanly (never 0.5x penalty!)
            clean_rivals = [
                r for r in (d.get("rivals") or [])
                if str(r.get("artefact") or "none") in ("none", "clean")
            ]
            if clean_rivals:
                beat_share = float(np.mean([1.0 if wu > float(r.get("would_use", 0.5)) else 0.0 for r in clean_rivals]))
                u_score = 0.40 * wu + 0.30 * comp + 0.30 * beat_share
            else:
                u_score = 0.55 * wu + 0.45 * comp
            vals.append(u_score)

        rows.append({
            "item_id": lid,
            "name": str(l.get("name") or ""),
            "structural_score": s_score,
            "structural_rank": s_rank,
            "clean_cua_n": len(clean_sessions),
            "raw_cua_utility": float(np.mean(vals)),
            "access_clean": True,
        })

    df = pd.DataFrame(rows)
    valid = df["access_clean"].to_numpy(dtype=bool) & np.isfinite(df["raw_cua_utility"].to_numpy(dtype=float))
    z = np.zeros(len(df), dtype=np.float64)
    if valid.sum() >= 3:
        v = df.loc[valid, "raw_cua_utility"].to_numpy(dtype=np.float64)
        sd = float(np.std(v))
        if sd > 1e-8:
            z[valid] = np.clip((v - float(np.mean(v))) / sd, -2.5, 2.5)

    shift = np.clip(eta * z, -max_shift, max_shift)
    df["cua_z"] = z
    df["residual_shift"] = shift
    df["final_score"] = df["structural_score"] + shift
    df = df.sort_values(["final_score", "structural_rank"], ascending=[False, True]).reset_index(drop=True)
    df["final_pred_rank"] = np.arange(1, len(df) + 1)
    return df
