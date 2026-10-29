"""Does the product load and work, (a) as archived by the Wayback Machine nearest the post time and (b) live today?

The Wayback API is unreachable from the cloud container (429s, dropped tunnels), so each check opens
https://web.archive.org/web/<post time>/<url> in the product's own recorded cloud browser (browser.py), which follows
Wayback's redirect to the nearest capture. Same short task for both. Writes hn_snapshots and sim_runs (arm=snapcheck).

    python snapcheck.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

import browser
import llm
import store as S
from judge import deep_posts

PERSONA = "A software engineer who reads Hacker News and tries the products people post there."
TASK = "Open the product from this Show HN post and try its main feature once, the way a curious reader would."


def bb_minutes() -> float | None:
    """Browserbase account-wide browser minutes so far (shared with other workstreams; a delta is an upper bound)."""
    try:
        r = requests.get(f"https://api.browserbase.com/v1/projects/{os.environ['BROWSERBASE_PROJECT_ID']}/usage",
                         headers={"X-BB-API-Key": os.environ["BROWSERBASE_API_KEY"]}, timeout=20)
        return float(r.json()["browserMinutes"])
    except Exception:  # noqa: BLE001
        return None


def one(job):
    p, where = job
    ts = dt.datetime.fromtimestamp(p["created_at_i"], dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    url = f"https://web.archive.org/web/{ts}/{p['url']}" if where == "wayback" else p["url"]
    r = browser.run(url, PERSONA, f"{TASK} Post: {p['title']}", max_actions=5, tag=f"snapcheck_{where}")
    urls = [st.get("url") for st in r.get("steps", []) if st.get("url")]
    m = next((re.search(r"web\.archive\.org/web/(\d{14})", u) for u in urls if "web.archive.org/web/" in u), None)
    lag = None
    if m:
        st = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
        lag = round((st.timestamp() - p["created_at_i"]) / 3600, 1)
    return p, where, r, (m.group(1) if m else None), lag


def main():
    posts = deep_posts().to_dict("records")
    m0, t0 = bb_minutes(), time.time()
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, [(p, w) for p in posts for w in ("wayback", "live")]))
    m1 = bb_minutes()
    snaps, runs = [], []
    for p, where, r, sts, lag in res:
        no_capture = where == "wayback" and any("hasn't archived" in (st.get("result") or "") or
                                                "Wayback Machine has not archived" in (st.get("result") or "")
                                                for st in r.get("steps", []))
        snaps.append({"post_id": p["post_id"], "where": where, "url": r.get("url"), "snapshot_ts": sts,
                      "lag_hours": lag, "session_id": r.get("session_id"), "error": r.get("error"),
                      "worked": bool(r.get("worked")) and not no_capture, "outcome": r.get("outcome"),
                      "actions": r.get("actions"), "seconds": r.get("seconds"), "observed_on": S.now()})
        runs.append({"post_id": p["post_id"], "arm": "snapcheck", "where": where, "person": None,
                     "session_id": r.get("session_id"), "watch_url": r.get("watch_url"), "url": r.get("url"),
                     "outcome": r.get("outcome"), "actions": r.get("actions"), "seconds": r.get("seconds"),
                     "model_usd": r.get("model_usd"), "error": r.get("error"), "worked": r.get("worked"),
                     "observations": json.dumps(r.get("observations")), "steps": json.dumps(r.get("steps"))[:200000],
                     "notes": r.get("notes"), "ran_on": S.now()})
    S.write("hn_snapshots", pd.DataFrame(snaps))
    S.write("sim_runs", pd.DataFrame(runs))
    usd = llm.flush_spend("hn_snapcheck", f"{len(res)} short browser runs (Gemini driver)")
    D = pd.DataFrame(snaps)
    print(f"runs {len(res)}  model ${usd:.3f}  wall {time.time() - t0:.0f}s  browserbase minutes delta "
          f"{(m1 - m0) if m0 is not None and m1 is not None else 'n/a'} (account-wide)")
    print(D.groupby("where")[["worked"]].mean().round(2).to_string(), "\nerrors:", D.error.notna().sum())
    print(D[D["where"] == "wayback"][["post_id", "snapshot_ts", "lag_hours", "worked", "outcome"]].to_string())


if __name__ == "__main__":
    main()
