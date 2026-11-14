#!/bin/bash
# UNDEPLOYED (needs Shreyas's direct word: it changes arm 2's live training set). Syncs the 2025 day lists missing from the VM training dir
# (~/w/ph_history/2025 had 339 of 365: Dec 6-31 fetched after the Nov 13 copy). Checks each file against raw/ph_history/manifest.jsonl
# (post count, valid JSON) and records md5s; copies only into a staging dir first, then moves files that pass. Never overwrites an existing
# day file. Then scores llm_pitch / llm_brand for the new days in the private H25 data dir (h25_llm.py score; Gemini; CAP_USD).
# usage (VM): bash sync_2025.sh [dest dir, default ~/w/ph_history/2025] [H25_DATA, default ~/w/h25/data]
set -euo pipefail
DST=${1:-$HOME/w/ph_history/2025}; HD=${2:-$HOME/w/h25/data}; B=gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history
ST=$(mktemp -d); export PATH=/opt/exp/bin:$PATH
gsutil -q cp $B/manifest.jsonl $ST/manifest.jsonl
python3 - "$DST" "$ST" <<'PY'
import json, os, subprocess, sys, hashlib
dst, st = sys.argv[1], sys.argv[2]
M = {r["day"]: r for r in map(json.loads, open(f"{st}/manifest.jsonl")) if r["year"] == 2025}
have = {f[:-5] for f in os.listdir(dst) if f.endswith(".json")}
need = sorted(set(M) - have); ok = []
for d in need:
    p = f"{st}/{d}.json"
    subprocess.run(["gsutil", "-q", "cp", f"gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history/{M[d]['path']}", p], check=True)
    n = len(json.load(open(p)))
    if n != M[d]["posts"]:
        print(f"{d}: {n} posts != manifest {M[d]['posts']}: skipped"); continue
    ok.append((d, n, hashlib.md5(open(p, "rb").read()).hexdigest()))
for d, n, m in ok:
    if not os.path.exists(f"{dst}/{d}.json"):
        os.replace(f"{st}/{d}.json", f"{dst}/{d}.json")
with open(f"{dst}/../sync_2025_md5.tsv", "a") as f:
    for d, n, m in ok: f.write(f"{d}\t{n}\t{m}\n")
print(json.dumps({"missing_before": len(need), "synced": len(ok), "posts": sum(n for _, n, _ in ok), "days_now": len(have) + len(ok)}))
PY
rm -rf "$ST"
# LLM scores for the new 2025 rows (private dir only; never the pipeline's caches)
cd $HOME/w/experiments/ph_predict && H25_DATA=$HD H25_SRC=$DST PYTHONPATH=$HOME/w/mk:.:$HOME/w/h25 python3 $HOME/w/h25/history_retrain.py --probe > /dev/null
H25_DATA=$HD PYTHONPATH=$HOME/w/mk:. python3 $HOME/w/h25/h25_llm.py score
