"""List RUNNING Browserbase sessions; release only ones clearly left by UserSim studies.

A session is released only when its userMetadata owner is a UserSim study tag
(integration/e2e/testfix/gates/taskfix) AND it carries a study_id whose study is
not the one about to run. Signup and untagged sessions are never touched.
Prints counts and owners only, never keys.
"""
from __future__ import annotations

import argparse
import collections
import json

from mvp.browser_slots import _age_s
from mvp.kill_switch import list_running_browserbase, release_browserbase_session

STUDY_OWNERS = {"integration", "e2e", "testfix", "gates", "taskfix"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--keep-study", default="")
    ap.add_argument("--min-age-s", type=float, default=600.0)
    args = ap.parse_args()
    rows = list_running_browserbase(owner="*")
    if rows and rows[0].get("status") == "error":
        print(json.dumps({"error": rows[0].get("error")}))
        return 1
    by_owner = collections.Counter((r.get("owner") or "(untagged)") for r in rows)
    print(json.dumps({"running": len(rows), "by_owner": by_owner}, default=dict))
    if not args.release:
        return 0
    released = 0
    for r in rows:
        owner = r.get("owner") or ""
        study = r.get("study_id") or ""
        # Another server (the VM, another stream) may be mid-study on the same
        # project with the same owner tag. Only sessions older than any study
        # budget are certainly leftovers.
        age = _age_s(r.get("started_at"))
        if age is None or age < args.min_age_s:
            continue
        if owner in STUDY_OWNERS and study and study != args.keep_study:
            if release_browserbase_session(r["id"]):
                released += 1
    print(json.dumps({"released_usersim_leftovers_older_than_min_age": released}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
