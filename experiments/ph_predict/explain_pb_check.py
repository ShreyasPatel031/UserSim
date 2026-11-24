"""Daily check of the person-built panel in results/web/explain/<D>.json (orchestrator 18:13Z Nov 24). Counts only; prints no values.
  - say.person_built_panel exists for every launch
  - say.persona_panel items: count per launch unchanged vs the first count this check recorded for that day (state file), within 19-24 when non-empty,
    and no persona item carries person-built fields (comments)
  - no key anywhere looks like a person id / handle / username / salt, and no string value has an @handle or a producthunt.com/@ link"""
import json, re, subprocess, sys, os
D, STATE = sys.argv[1], sys.argv[2]
d = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/explain/{D}.json"], capture_output=True, text=True).stdout)
L = d["launches"]; fails = []
missing = [i for i, v in L.items() if "person_built_panel" not in (v.get("say") or {})]
if missing: fails.append(f"person_built_panel missing for {len(missing)} of {len(L)} launches")
cnt = {i: len(((v.get("say") or {}).get("persona_panel") or {}).get("items") or []) for i, v in L.items()}
odd = [i for i, n in cnt.items() if n and not 19 <= n <= 24]
if odd: fails.append(f"persona_panel item count outside 19-24 for {len(odd)} launches")
mixed = sum(1 for v in L.values() for it in (((v.get("say") or {}).get("persona_panel") or {}).get("items") or []) if isinstance(it, dict) and "comments" in it)
if mixed: fails.append(f"{mixed} persona_panel items carry person-built fields")
st = json.load(open(STATE)) if os.path.exists(STATE) else {}
if D in st:
    ch = [i for i in cnt if i in st[D] and st[D][i] != cnt[i]]
    if ch: fails.append(f"persona_panel item count changed for {len(ch)} launches since first seen")
else: st[D] = cnt; json.dump(st, open(STATE, "w"))
KEY = re.compile(r"(person|user|voter|commenter|maker|hunter)_?(id|ids|handle|handles|username|usernames)$|^(handle|handles|username|usernames|salt|salted_id)$", re.I)
VAL = re.compile(r"(?<![\w.])@(?!someone\b)[A-Za-z0-9_]{2,}|producthunt\.com/@")   # "@someone" is the generator's placeholder, not a handle
nk = nv = 0
def walk(x):
    global nk, nv
    if isinstance(x, dict):
        for k, v in x.items(): nk += bool(KEY.search(str(k))); walk(v)
    elif isinstance(x, list): [walk(v) for v in x]
    elif isinstance(x, str): nv += bool(VAL.search(x))
walk(d)
if nk: fails.append(f"{nk} person-id/handle keys")
if nv: fails.append(f"{nv} string values with an @handle or profile link")
print(json.dumps({"day": D, "launches": len(L), "person_built": len(L) - len(missing), "persona_counts_first_seen": D not in st or st[D] == cnt, "fails": fails}))
sys.exit(1 if fails else 0)
