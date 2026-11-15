"""Shared loader for the data-driven population segments (population_segments.py). Replaces the keyword role labels in persona cards,
the persona-panel "say" and the explain file's segments. Falls back to the keyword label only when no segment run exists.
    labels, profiles = segments_lib.load(scratchpad)   # labels: person_id -> "Group name / subgroup name"; profiles: label -> who/says/votes_for"""
import io, json, os, subprocess
import pandas as pd
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
INACTIVE = "rare voters (no upvote on 2025-26 launches)"


def _gs(path, binary=False):
    r = subprocess.run(["gsutil", "cat", f"{B}/{path}"], capture_output=True)
    return (r.stdout if binary else r.stdout.decode()) if r.returncode == 0 and r.stdout else None


def load(sp=None):
    loc = os.path.join(sp, "segments") if sp else None
    pub = _gs("results/web/segments/latest.json"); mem = _gs("tmp/e5/private/segments/latest.parquet", True)
    if pub and mem: J, M = json.loads(pub), pd.read_parquet(io.BytesIO(mem))
    elif loc and os.path.exists(os.path.join(loc, "latest.json")):
        J = json.load(open(os.path.join(loc, "latest.json"))); M = pd.read_parquet(os.path.join(loc, f"members_{J['cut']}.parquet"))
    else: return {}, {}
    names, prof = {}, {}
    for g in J["groups"]:
        gname = g.get("name") or f"group {g['id']}"
        for s in g.get("subgroups", []):
            lab = f"{gname} / {s.get('name') or 'subgroup ' + s['id']}"; names[s["id"]] = lab
            prof[lab] = {"segment_id": s["id"], "group": gname, "who": s.get("who") or g.get("who"), "says": s.get("says") or g.get("says"),
                         "votes_for": s.get("votes_for") or g.get("votes_for"), "group_size": g["n_people"], "subgroup_size": s["n_people"], "segments_cut": J["cut"]}
        names[f"{g['id']}"] = gname
    lab = {p: (names.get(s) or names.get(str(g)) or INACTIVE) if int(g) >= 0 else INACTIVE for p, g, s in zip(M.person_id, M.group, M.subgroup)}
    return lab, prof
