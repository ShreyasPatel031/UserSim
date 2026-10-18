"""End-to-end benchmark: does a real UserSim browser run (and its feedback) improve predictions of a real reviewer's
experience, with and without the competitor-review package?

Cases: Capterra reviewers from router_eval's held-out TEST products whose review states a task (the task is the
reviewer's own, extracted neutrally). Hidden answer: their ratings and review text. Same final predictor throughout.
  C1  agent alone                         (router_eval agent_alone, cached)
  C2  review package only, no run         (router_eval agent_full, cached)
  C3  UserSim run -> feedback without reviews -> predictor
  C4  UserSim run -> feedback with reviews -> predictor given feedback + review package
The package always excludes the target product's own reviews. Runs are logged out (no accounts in this
environment; MVP_AUTO_SIGNUP/SIGNIN forced off), on Browserbase via mvp.browser_agent.run_browser_agent.

    python experiments/staged_context/e2e_bench.py --cases 1      # smoke one case
    python experiments/staged_context/e2e_bench.py --per-product 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / "src"))
os.environ["MVP_AUTO_SIGNUP"] = "0"
os.environ["MVP_AUTO_SIGNIN"] = "0"

import experiment as E  # noqa: E402
import g2_merge as G  # noqa: E402
import matched as MT  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

BOUT = E.OUT / "e2e_bench"
FLASH = "gemini-2.5-flash"
CONDS = ["C1_agent_alone", "C2_reviews_only", "C3_run_only", "C4_run_plus_reviews"]


def cases(per_product: int) -> list[dict]:
    people = [r for r in RE.sample(U.data()) if r["product_name"] in RE.TEST]
    refs = {r["review_id"]: G.RE_extract(r) for r in people}
    out, seen = [], {}
    for r in people:
        p = r["product_name"]
        if refs[r["review_id"]]["task"] and seen.get(p, 0) < per_product:
            seen[p] = seen.get(p, 0) + 1
            out.append({"row": r, "ref": refs[r["review_id"]], "card": RE.card(r, refs[r["review_id"]]["task"])})
    return out


def package(c: dict) -> dict:
    r, card = c["row"], c["card"]
    return U.build_package(RE.URLS[r["product_name"]], {"role_family": card["role_family"], "company_size": r["reviewer_company_size"],
                                                         "time_used": r["reviewer_time_used_product"], "industry": r["reviewer_industry"]},
                           exclude_product=r["product_name"], mask=U.mask_for(r["product_name"]))


async def run_case(c: dict, sem: asyncio.Semaphore) -> dict:
    from mvp.browser_agent import run_browser_agent
    from mvp.study import summarize_agent_feedback

    r, card = c["row"], c["card"]
    rid = r["review_id"]
    path = BOUT / "runs" / f"{rid}.json"
    if path.exists():
        rec = E.read_json(path)
        if not _infra_error(rec["run"].get("error")):
            return rec
    persona = {"id": rid, "name": card["role_title"] or card["role_family"],
               "bio": f"{card['role_title']} at a {card['company_size']} company in {card['industry']}, trying {card['product']} for this job."}
    url = RE.URLS[r["product_name"]]
    t0 = time.time()
    async with sem:
        try:
            run = await asyncio.wait_for(run_browser_agent(study_id="e2e_bench", agent_id=rid.replace("Capterra___", "c"), url=url,
                                                           task_prompt=card["task"], persona=persona,
                                                           segment=f"{card['role_family']} / {card['industry']}"), timeout=420)
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 - browser_use cancels on internal timeouts
            run = {"error": f"{type(exc).__name__}: {exc}"[:400], "trace": [], "completed": False, "visited_urls": []}
    pk = package(c)
    ev = ("\nEvidence from real Capterra and G2 reviews of competing products by people like this persona "
          f"(category: {pk['category']}):\n" + "\n\n".join(pk["sections"].values())[:9000] + "\n")
    task = {"prompt": card["task"], "site_url": url}
    fb_no = await summarize_agent_feedback(url=url, segment=card["role_family"], persona=persona, task=task, run=run, review_evidence="")
    fb_yes = await summarize_agent_feedback(url=url, segment=card["role_family"], persona=persona, task=task, run=run, review_evidence=ev)
    rec = {"rid": rid, "product": r["product_name"], "url": url, "task": card["task"], "secs": round(time.time() - t0, 1),
           "run": {k: run.get(k) for k in ("completed", "visited_urls", "error", "num_steps", "final_url")},
           "steps": [{k: s.get(k) for k in ("step", "url", "action", "observation")} for s in (run.get("trace") or [])][:20],
           "feedback_no_reviews": fb_no, "feedback_with_reviews": fb_yes}
    if not _infra_error(run.get("error")):  # rate limits / lost sessions are retried on the next invocation
        E.write_json(path, rec)
    return rec


def _infra_error(err: str | None) -> bool:
    return bool(err) and any(k in err for k in ("RateLimit", "429", "Browserbase", "CancelledError", "TimeoutError"))


async def run_in_child(c: dict, sem: asyncio.Semaphore, per_product: int) -> dict:
    """One case per process: browser_use's CDP clients fail when several sessions share one event loop."""
    rid = c["row"]["review_id"]
    path = BOUT / "runs" / f"{rid}.json"
    if path.exists() and not _infra_error(E.read_json(path)["run"].get("error")):
        return E.read_json(path)
    (BOUT / "logs").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    async with sem:
        with open(BOUT / "logs" / f"{rid}.log", "w") as log:
            proc = await asyncio.create_subprocess_exec(sys.executable, __file__, "--one", rid, "--per-product", str(per_product),
                                                        stdout=log, stderr=asyncio.subprocess.STDOUT)
            try:
                await asyncio.wait_for(proc.wait(), timeout=600)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
    if path.exists():
        return E.read_json(path)
    return {"rid": rid, "product": c["row"]["product_name"], "secs": round(time.time() - t0, 1), "steps": [],
            "run": {"error": "TimeoutError: child process gave no result (infrastructure)", "completed": False}}


def predict(c: dict, cond: str, rec: dict | None) -> dict:
    card, rid = c["card"], c["row"]["review_id"]
    if cond == "C1_agent_alone":
        ev, key = "", f"{rid}|agent_alone"
    elif cond == "C2_reviews_only":
        ev, key = "\nData:\n" + "\n\n".join(package(c)["sections"].values()), f"{rid}|agent_full"
    else:
        fb = rec["feedback_no_reviews" if cond == "C3_run_only" else "feedback_with_reviews"]
        run_ev = ("## What happened when a simulated user with this person's profile attempted this task in the product today "
                  "(logged out)\n" + json.dumps(fb, ensure_ascii=False)[:4000])
        ev = "\nData:\n" + run_ev
        if cond == "C4_run_plus_reviews":
            ev += "\n\n" + "\n\n".join(package(c)["sections"].values())
        key = f"{rid}|{cond}"
    out = E.call_model("router_predict" if cond in ("C1_agent_alone", "C2_reviews_only") else "e2e_predict", FLASH, MT.PRED_SYSTEM,
                       RE.PRED.format(**card, evidence=ev), temperature=E.PREDICT_TEMPERATURE, seed=1000, max_tokens=8192,
                       thinking_budget=1024, key_extra=key)
    return out.get("json") if isinstance(out.get("json"), dict) else {}


def judge(c: dict, j: dict) -> dict:
    ref = c["ref"]
    lst = lambda x: [str(v) for v in x][:3] if isinstance(x, list) else []  # noqa: E731
    fmt = lambda xs, p: "\n".join(f"{p}{i + 1}: {x}" for i, x in enumerate(xs)) or "(none)"  # noqa: E731
    rec = E.call_model("router_judge", FLASH, "You are a strict evaluator. Return JSON only.", RE.JUDGE.format(
        pp=fmt(lst(j.get("pros")), "P"), ap=fmt(ref["benefits"], "A"), pc=fmt(lst(j.get("cons")), "P"),
        ac=fmt(ref["frictions"], "A"), po=str(j.get("overall_experience") or ""), at=E.review_for_extraction(c["row"])),
        temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
    g = rec.get("json") if isinstance(rec.get("json"), dict) else {}

    def recall(key, n):
        best = {}
        for m in g.get(key) or []:
            if isinstance(m, dict) and m.get("score") in (1, 2):
                best[m.get("act")] = max(best.get(m.get("act"), 0), m["score"])
        return (sum(v == 2 for v in best.values()) / n) if n else None
    ov = g.get("overall")
    return {"pros": recall("pros", len(ref["benefits"])), "cons": recall("cons", len(ref["frictions"])),
            "overall_experience": float(ov == 2) if ov in (0, 1, 2) else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-product", type=int, default=4)
    ap.add_argument("--cases", type=int, default=0, help="limit total cases (smoke)")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--one", help="run a single case (by review id) in this process; used by the parent")
    a = ap.parse_args()
    cs = cases(a.per_product)
    if a.one:
        c = next(c for c in cs if c["row"]["review_id"] == a.one)
        rec = asyncio.run(run_case(c, asyncio.Semaphore(1)))
        print(json.dumps({"error": rec["run"].get("error")}), flush=True)
        return
    if a.cases:
        cs = cs[: a.cases]
    print(f"{len(cs)} cases across {len({c['row']['product_name'] for c in cs})} products", flush=True)

    async def go():
        sem = asyncio.Semaphore(a.concurrency)
        done = 0

        async def one(c):
            nonlocal done
            rec = await run_in_child(c, sem, a.per_product)
            done += 1
            print(f"[{done}/{len(cs)}] {rec['product']}: completed={rec['run'].get('completed')} steps={len(rec['steps'])} "
                  f"err={(rec['run'].get('error') or '')[:60]} {rec['secs']}s", flush=True)
            return rec
        res = await asyncio.gather(*(one(c) for c in cs), return_exceptions=True)
        for c, r in zip(cs, res):
            if isinstance(r, BaseException):
                print(f"case {c['row']['review_id']} failed outside the browser run: {r!r}", flush=True)
        return [r for r in res if isinstance(r, dict)]

    recs = {r["rid"]: r for r in asyncio.run(go()) if "feedback_no_reviews" in r}
    print(f"usable runs: {len(recs)}/{len(cs)}", flush=True)
    cs = [c for c in cs if c["row"]["review_id"] in recs]
    pool = ThreadPoolExecutor(64)
    jobs = [(c, k) for c in cs for k in CONDS]
    preds = dict(zip([(c["row"]["review_id"], k) for c, k in jobs],
                     pool.map(lambda ck: predict(ck[0], ck[1], recs.get(ck[0]["row"]["review_id"])), jobs)))
    judged = dict(zip(list(preds), pool.map(lambda ck: judge(ck[0], preds[(ck[0]["row"]["review_id"], ck[1])]), jobs)))
    rows = []
    for c in cs:
        rid, r = c["row"]["review_id"], c["row"]
        for k in CONDS:
            j = preds[(rid, k)]
            row = {"rid": rid, "product": r["product_name"], "condition": k,
                   "run_completed": recs[rid]["run"].get("completed"), "run_error": bool(recs[rid]["run"].get("error"))}
            for out, (lo, hi) in U.RATINGS.items():
                v = RE.U_num(j.get(out), lo, hi)
                row[f"{out}_abs_err"] = abs(v - r[out]) if v is not None and r.get(out) is not None else None
            row.update(judged[(rid, k)])
            rows.append(row)
    m = pd.DataFrame(rows)
    BOUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(BOUT / "per_case.csv", index=False)
    cols = [c for c in m.columns if c.endswith("_abs_err")] + ["pros", "cons", "overall_experience"]
    summary = m.groupby("condition")[cols].mean().loc[CONDS]
    summary.to_csv(BOUT / "summary.csv")
    pd.set_option("display.width", 250)
    print(summary.round(3).T.to_string())
    ok = m[~m.run_error].groupby("condition")[cols].mean().loc[CONDS]
    print(f"\nruns without infrastructure error: {int((~m[m.condition == CONDS[0]].run_error).sum())}/{len(cs)}; "
          f"completed task: {int(m[m.condition == CONDS[0]].run_completed.fillna(False).sum())}")
    print(ok.round(3).T.to_string())
    print(f"model-call spend (excl. browser actions/Browserbase): ${E.spent_usd():.3f}")


if __name__ == "__main__":
    main()
