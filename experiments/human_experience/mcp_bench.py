"""Signed-in production-MCP runs added to the handoff's e2e benchmark (experiments/staged_context/e2e_bench.py on
branch claude/modest-euler-6111ae, checked out at $CTX_ROOT).

Same held-out Capterra reviewers, same tasks (extracted from each reviewer's own review), same predictor, same judge.
Conditions:
  C1  agent alone                      (cached, from the handoff)
  C2  review package only              (cached, from the handoff)
  C3  logged-out local run only        (cached, from the handoff's e2e_bench)
  C4  logged-out local run + package   (cached, from the handoff's e2e_bench)
  C5  signed-in MCP run only           (new)
  C6  signed-in MCP run + package      (new)
C5/C6 feed only what the run saw of the product: frictions and benefits it observed after reaching the signed-in
product. Agent failures are dropped. A run that never got signed in to the product feeds "no product observations".

    python mcp_bench.py dump --product Smartsheet      # writes the cases the runner subagents work from
    python mcp_bench.py score --product Smartsheet     # predictions + scoring for every case with a run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CTX = Path(os.environ.get("CTX_ROOT", "/home/user/UserSim-ctx"))
sys.path.insert(0, str(CTX / "experiments/staged_context"))

import e2e_bench as B  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/mcp_bench"
PER_PRODUCT = 5
CONDS = B.CONDS + ["C5_mcp_run_only", "C6_mcp_run_plus_reviews"]


def product_cases(product: str) -> list[dict]:
    return [c for c in B.cases(PER_PRODUCT) if c["row"]["product_name"] == product]


def dump(product: str) -> None:
    OUT.joinpath("cases").mkdir(parents=True, exist_ok=True)
    for c in product_cases(product):
        rid = c["row"]["review_id"]
        card = {k: c["card"][k] for k in ("product", "url", "role_title", "role_family", "industry", "company_size",
                                           "time_used", "task")}
        (OUT / "cases" / f"{rid}.json").write_text(json.dumps({"rid": rid, **card}, indent=1))
        print(rid, card["role_title"], "|", card["task"])


def run_evidence(run: dict) -> str:
    if not (run.get("signed_in") and run.get("reached_product")):
        return ("## Simulated user's signed-in session in the product today\n"
                "No product observations: the session did not get signed in to the product.")
    obs = [o for o in run.get("observations") or [] if o.get("kind") in ("product_friction", "product_benefit")]
    lines = [f"- [{o['kind'].replace('product_', '')}] {o['what']}" for o in obs] or ["- nothing notable observed"]
    return ("## What a simulated user with this person's profile saw when doing this task in the signed-in product today "
            f"(outcome: {run.get('outcome')}; product behaviour only, the simulated user's own mistakes are left out)\n"
            + "\n".join(lines))


def predict(c: dict, cond: str, run: dict | None) -> dict:
    if not cond.startswith(("C5", "C6")):
        return B.predict(c, cond, B.E.read_json(B.BOUT / "runs" / f"{c['row']['review_id']}.json")
                         if cond.startswith(("C3", "C4")) else None)
    ev = "\nData:\n" + run_evidence(run)
    if cond.startswith("C6"):
        ev += "\n\n" + "\n\n".join(B.package(c)["sections"].values())
    out = B.E.call_model("mcp_bench_predict", B.FLASH, B.MT.PRED_SYSTEM, B.RE.PRED.format(**c["card"], evidence=ev),
                         temperature=B.E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192, thinking_budget=1024,
                         key_extra=f"{c['row']['review_id']}|{cond}")
    return out.get("json") if isinstance(out.get("json"), dict) else {}


def score(products: list[str]) -> None:
    cs = [c for p in products for c in product_cases(p)
          if (OUT / "runs" / f"{c['row']['review_id']}.json").exists()]
    runs = {c["row"]["review_id"]: json.loads((OUT / "runs" / f"{c['row']['review_id']}.json").read_text()) for c in cs}
    old = {c["row"]["review_id"] for c in cs if (B.BOUT / "runs" / f"{c['row']['review_id']}.json").exists()}
    jobs = [(c, k) for c in cs for k in CONDS if not (k.startswith(("C3", "C4")) and c["row"]["review_id"] not in old)]
    pool = ThreadPoolExecutor(32)
    preds = list(pool.map(lambda ck: predict(ck[0], ck[1], runs[ck[0]["row"]["review_id"]]), jobs))
    judged = list(pool.map(lambda x: B.judge(x[0][0], x[1]), zip(jobs, preds)))
    rows = []
    for (c, k), j, g in zip(jobs, preds, judged):
        r, run = c["row"], runs[c["row"]["review_id"]]
        row = {"rid": r["review_id"], "product": r["product_name"], "condition": k,
               "signed_in": bool(run.get("signed_in") and run.get("reached_product")), "outcome": run.get("outcome")}
        for out, (lo, hi) in B.U.RATINGS.items():
            v = B.RE.U_num(j.get(out), lo, hi)
            row[f"{out}_abs_err"] = abs(v - r[out]) if v is not None and r.get(out) is not None else None
            row[f"{out}_pred"], row[f"{out}_actual"] = v, r.get(out)
        row.update(g)
        rows.append(row)
    m = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(OUT / "per_case.csv", index=False)
    cols = [c for c in m.columns if c.endswith("_abs_err")] + ["pros", "cons", "overall_experience"]
    summary = m.groupby("condition")[cols].mean().reindex([c for c in CONDS if c in set(m.condition)])
    summary.to_csv(OUT / "summary.csv")
    pd.set_option("display.width", 250)
    print(f"{len(cs)} cases, signed in and reached product: {sum(bool(r.get('signed_in') and r.get('reached_product')) for r in runs.values())}")
    print(summary.round(2).T.to_string())
    print(f"model-call spend: ${B.E.spent_usd():.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "score"])
    ap.add_argument("--product", action="append", required=True)
    a = ap.parse_args()
    dump(a.product[0]) if a.cmd == "dump" else score(a.product)
