"""Live readiness for the young-account features (fixes young_comm.py part 4: the live comments_ts username field is not the handle, so
join by commenter_user_id = ph_user_id from the people_live files). Team = hunter + makers user ids from the daily API file of that day.
Share of non-team commenters by 00:30 / 01:00 PT that are complete in the store version live at the launch start (_prev_20261110T0910Z for
Nov 10, _prev_20261113T1148Z for Nov 11-13) with a join date before the day; launches with >= 3 such commenters. Counts only.
    python young_live.py <scratchpad> <result.json to update>
"""
import json, os, subprocess, sys
import pandas as pd
SP, RJ = sys.argv[1:3]; PT = "America/Los_Angeles"
J = pd.read_parquet(f"{SP}/acct/joined.parquet"); J["uid"] = pd.to_numeric(J.ph_user_id, errors="coerce"); J["jt"] = pd.to_datetime(J.joined, utc=True, errors="coerce")
J = J.dropna(subset=["uid"]).drop_duplicates("uid").set_index("uid"); o4 = {}
for d in ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"):
    PP = pd.read_parquet(f"{SP}/acct/prev/_prev_20261110T0910Z.parquet" if d == "2026-11-10" else f"{SP}/acct/prev/_prev_20261113T1148Z.parquet"); comp = set(PP[PP.complete].person_id)
    d0 = pd.Timestamp(d).tz_localize(PT).tz_convert("UTC")
    day = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily/{d}/{d}.json"], capture_output=True, text=True).stdout or "[]")
    team = {str(p["id"]): {str(u.get("id")) for u in [p.get("user")] + (p.get("makers") or []) if u} for p in day}
    C = pd.read_json(f"{SP}/acct/cts_{d}.jsonl", lines=True); C["t"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); C["u"] = C.commenter_user_id.astype(str)
    C = C[[u not in team.get(str(l), set()) for u, l in zip(C.u, C.launch_id)]]; C["uid"] = pd.to_numeric(C.u, errors="coerce")
    for cn, mins in (("0030", 30), ("0100", 60)):
        S = C[C.t <= d0 + pd.Timedelta(minutes=mins)].drop_duplicates(["launch_id", "u"])
        ok = [(x in J.index) and (J.at[x, "person_id"] in comp) and (J.at[x, "jt"] < d0) for x in S.uid]; S = S.assign(ok=ok); g = S.groupby("launch_id").ok.agg(["sum", "size"])
        o4[f"{d} by {cn}"] = {"non-team commenter-launch pairs": len(S), "in live store with join date": int(S.ok.sum()), "share": round(float(S.ok.mean()), 3) if len(S) else None,
                              "launches with >=3 covered / with any commenter / in line-up": [int((g["sum"] >= 3).sum()), len(g), len(day)]}
R = json.load(open(RJ)); R["(4) live readiness"] = o4; R["(4) note"] = "joined by commenter_user_id (young_live.py); the username field in live comments_ts is not the handle"
json.dump(R, open(RJ, "w"), indent=1, default=float); print(json.dumps(o4))
