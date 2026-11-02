"""Honest at-launch audience counts: the makers' and hunter's Product Hunt follower counts (and X handles) as the API
returned them at the 00:05 PT launches step, before votes come in (data/today/<day>.json). The later re-reads in
data/days/<day>.json are not used: for Nov 1, 25 of 26 makers had a higher count there. Table at_launch_followers:
launch_id, day, role (maker | hunter), person, ph_followers, twitter, read_at (file time, UTC), source_file.
X follower counts at launch are saved by the forecast step (results/forecast_<day>.parquet: x_maker_sum_followers,
x_company_followers) from the shadow bundle on.
usage: python -m pipeline.at_launch backfill [--dry-run]   (every data/today/<day>.json not yet in the table)"""
import datetime as dt, json, os, sys
import pandas as pd
from . import warehouse as W

PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ph_predict")
TODAY = os.path.join(PH, "data", "today")


def rows(d):
    f = os.path.join(TODAY, f"{d}.json")
    if not os.path.exists(f):
        return pd.DataFrame()
    at = dt.datetime.fromtimestamp(os.path.getmtime(f), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for p in json.load(open(f)):
        people = [("maker", m) for m in (p.get("makers") or []) if isinstance(m, dict)] + [("hunter", p.get("user") or {})]
        for role, u in people:
            if u.get("username") or u.get("id"):
                out.append({"launch_id": str(p["id"]), "day": d, "role": role, "person": u.get("username") or str(u.get("id")),
                            "ph_followers": u.get("followersCount"), "twitter": u.get("twitterUsername") or None,
                            "read_at": at, "source_file": f"today/{d}.json"})
    return pd.DataFrame(out)


def backfill(dry=False):
    have = set()
    try:
        have = set(W.query("SELECT DISTINCT day FROM at_launch_followers").day.astype(str))
    except Exception:  # noqa: BLE001  (table not created yet)
        pass
    days = sorted(f[:-5] for f in os.listdir(TODAY) if f.endswith(".json") and f[:-5] not in have)
    n = 0
    for d in days:
        R = rows(d); n += len(R)
        print(d, len(R), "rows", flush=True)
        if not dry and len(R):
            W.write("at_launch_followers", R)
    return n


if __name__ == "__main__":
    if sys.argv[1:2] == ["backfill"]:
        print("rows", backfill("--dry-run" in sys.argv))
