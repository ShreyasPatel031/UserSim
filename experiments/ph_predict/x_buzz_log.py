"""Nightly raw-field log of Grok Bot's pre-launch X counts (orchestrator 21:59Z Nov 18: X buzz closed, no signal; log and re-test at ~30 days).
Reads raw/ph_at_launch/<D>/x_buzz_0010.jsonl (pre_launch window only; asserts window_end <= D 00:00 PT), maps slug -> launch id via
raw/daily/<D>/today_0005.json, appends one row per launch to results/x_buzz_daily.jsonl: day, id, pre_posts, log1p_posts, preannounce,
x_missing. Never uses launch_day counts. Skips days already logged. Counts only.
usage: python x_buzz_log.py <D> [<D> ...]"""
import json, math, os, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "results", "x_buzz_daily.jsonl")
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout


def log(d):
    done = {json.loads(l)["day"] for l in open(OUT)} if os.path.exists(OUT) else set()
    if d in done: return {"day": d, "status": "already logged"}
    raw, lu = cat(f"{B}/raw/ph_at_launch/{d}/x_buzz_0010.jsonl"), cat(f"{B}/raw/daily/{d}/today_0005.json")
    if not raw or not lu: return {"day": d, "status": "missing input", "x": bool(raw), "lineup": bool(lu)}
    cut = pd.Timestamp(d + " 00:00", tz="America/Los_Angeles").tz_convert("UTC")
    X = {}
    for l in raw.splitlines():
        if not l.strip(): continue
        x = json.loads(l)
        if x.get("window") != "pre_launch": continue
        if pd.Timestamp(x["window_end"]) > cut: return {"day": d, "status": f"refused: pre_launch window ends {x['window_end']} after the cut"}
        X[x["slug"]] = x
    rows = []
    for p in json.loads(lu):
        x = X.get(p["slug"], {}); n = x.get("post_count")
        rows.append({"day": d, "id": str(p["id"]), "pre_posts": n, "log1p_posts": (round(math.log1p(n), 4) if n is not None else None),
                     "preannounce": bool(x.get("maker_preannounced_ph_launch", False)), "x_missing": n is None,
                     "lower_bound": bool(x.get("post_count_is_lower_bound", False))})
    with open(OUT, "a") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    return {"day": d, "status": "ok", "launches": len(rows), "missing": sum(r["x_missing"] for r in rows), "with_posts": sum((r["pre_posts"] or 0) > 0 for r in rows)}


if __name__ == "__main__":
    for d in sys.argv[1:]: print(json.dumps(log(d)))
