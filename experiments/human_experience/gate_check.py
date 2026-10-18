"""False-rejection rate of agent mode's identity gate (mvp.agent_mode.check_identity) on known-good data: each of
router_eval's 35 products with its own Capterra reviews and its 3 most-reviewed same-category rivals (snapshot data,
research only). Uses the production judge (Gemini via capability.gemini_config).

    PYTHONPATH=../../src python gate_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pandas as pd

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(CTX / "experiments/staged_context"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / "src"))

import corpus as C  # noqa: E402
import router_eval as RE  # noqa: E402
from agent_mode_eval import live_shape  # noqa: E402

from mvp import agent_mode as A  # noqa: E402

OUT = HERE / "results/gate_check"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    d = C.corpus()
    cap = d[d.source == "capterra"].copy()
    import ux_mcp as U
    raw = U.data().set_index(U.data().review_id.astype(str))
    cap["role_title"] = cap.rid.str[2:].map(raw.reviewer_job_title)
    cap["general_comments"] = cap.rid.str[2:].map(raw.general_comments)
    sem = asyncio.Semaphore(8)

    async def one(p):
        async with sem:
            own = [live_shape(x) for x in cap[cap["product"] == p].head(20).to_dict("records")]
            catg = cap[cap["product"] == p].category.iloc[0]
            comp = cap[(cap.category == catg) & (cap["product"] != p)]
            top = comp.groupby("product").size().sort_values(ascending=False).index[:3]
            rivals = {t: [live_shape(x) for x in comp[comp["product"] == t].head(20).to_dict("records")] for t in top}
            res = await A.check_identity(p, RE.URLS[p], own, rivals, A._default_judge)
            rows = [{"product": p, "kind": "own", "name": p, "ok": res["own"]["ok"], "why": res["own"]["why"]}]
            rows += [{"product": p, "kind": "rival", "name": n, "ok": c["ok"], "direct": c["direct"], "why": c["why"]}
                     for n, c in res["rivals"].items()]
            return rows

    rows = [r for rs in await asyncio.gather(*(one(p) for p in RE.DEV + RE.TEST)) for r in rs]
    M = pd.DataFrame(rows)
    M.to_csv(OUT / "gate_check.csv", index=False)
    print(M.groupby("kind").ok.agg(["mean", "count"]))
    print(M[~M.ok].to_string(index=False))


if __name__ == "__main__":
    asyncio.run(main())
