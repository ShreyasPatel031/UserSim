"""One extra hourly-recorder read at a non-hour time (bundle 12a; orchestrator 00:52Z Nov 14). pipeline/hourly.py skips a second read in the
same UTC hour, so a 03:45 PT (pre-reveal) or 23:50 PT (day-close) read needs this wrapper. It calls hourly._snapshot (same official API
query, same rows, same raw file + warehouse part) under the recorder's own lock, so it can never run at the same moment as the hourly read.
usage (VM, from ~/w/experiments, PH_TOKEN set): python3 recorder_extra.py"""
import datetime as dt, fcntl, os, sys
sys.path.insert(0, "/home/agent/w/experiments")
from pipeline import hourly as H
now = dt.datetime.now(dt.timezone.utc); d = H.pacific_day(now)
os.makedirs(f"{H.PH}/data/vote_snapshots", exist_ok=True)
with open(f"{H.PH}/data/vote_snapshots/.lock", "w") as lk:
    fcntl.flock(lk, fcntl.LOCK_EX)
    H._snapshot(now, d)
