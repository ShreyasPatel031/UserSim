#!/bin/bash
# Shadow job (orchestrator 13:02Z / E5 13:03Z Nov 13): E5's why_writer.py (claude/person-model-v2 fcbcd617), people-side "why" items.
# No LLM, no Product Hunt requests, CPU only. Salted ids + counts only; the salt is read by the script, never printed.
# usage: bash why_run.sh forecast|after|try <D|-> <work dir> <worktree of fcbcd617>
#   forecast D: at/after 00:10 PT on D (store reads fetched before 00:00 PT only) -> results/web/why_shadow/<D>_0005.json
#   after D:    ~09:00 PT on D+1, after the store merge -> results/web/why_shadow/<D>_after.json
#   try -:      weekly /try neighbour sidecar -> results/web/why_shadow/try_neighbours_v1.json
set -euo pipefail
MODE="$1"; D="$2"; W="$3"; WT="$4"; B=gs://usersim-bakeoff-347838016394/usersim_sim
PIN=fcbcd617   # the single source of truth for the pin (E5 14:54Z Nov 13); the worktree is moved / recreated here
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# bundle 12 (VM, no git): a plain copy of the pinned tree with a .pin file holding PIN is used as is
if [ -f "$WT/.pin" ] && [ "$(cat "$WT/.pin")" = "$PIN" ]; then :
elif [ ! -d "$WT/.git" ] && [ ! -f "$WT/.git" ]; then git -C "$REPO" fetch -q origin claude/person-model-v2; git -C "$REPO" worktree add -q --detach "$WT" "$PIN"; fi
[ -f "$WT/.pin" ] || [ "$(git -C "$WT" rev-parse --short=8 HEAD)" = "$PIN" ] || { git -C "$REPO" fetch -q origin claude/person-model-v2 || true; git -C "$WT" checkout -q --detach "$PIN"; }
case "$MODE" in forecast) F="${D}_0005.json";; after) F="${D}_after.json";; try) F="try_neighbours_v1.json";; *) echo "bad mode"; exit 2;; esac
# skip only when a NON-EMPTY file exists (an empty one, e.g. an 'after' run before the merge, is rewritten)
if [ "${FORCE:-0}" != 1 ] && [ "$MODE" != try ] && gsutil -q stat "$B/results/web/why/$F"; then
  N=$(gsutil cat "$B/results/web/why/$F" | python3 -I -c "import json,sys; print(len(json.load(sys.stdin).get('launches') or {}))")
  if [ "$N" -gt 0 ]; then echo "exists $F ($N launches)"; exit 0; fi
fi
mkdir -p "$W/early" "$W/acct" "$W/rbundle" "$W/store" "$W/out"
[ -s "$W/early/salt" ] || gsutil -q cp "$B/raw/population/_salt" "$W/early/salt"
gsutil -q cp "$B/raw/population/store_v3/events.parquet" "$B/raw/population/store_v3/persons.parquet" "$W/store/"
if [ "$MODE" = try ]; then gsutil -q cp "${RBUNDLE:-$B/site/reactions_retrieval_v1.json}" "$W/rbundle/reactions_retrieval_v1.json"; fi
cd "$WT" && python3 experiments/simlab/why_writer.py "$MODE" "$D" "$W/store" "$W" "$W/out"
# checks: no salted ids or handles, shadow flag, launch / item counts
python3 -I - "$W/out/$F" <<'PY'
import json, re, sys
t = open(sys.argv[1]).read(); d = json.loads(t)
assert not re.search(r'"p_[0-9a-f]{16}"|\bp_[0-9a-f]{16}\b', t), "salted id in output"
assert d.get("shadow") is True, "shadow flag missing"
L = d.get("launches") or d.get("rows") or {}
V = list(L.values()) if isinstance(L, dict) else L
print(json.dumps({"file": sys.argv[1].rsplit("/", 1)[-1], "launches": len(V), "items_per_launch": round(sum(len(x) for x in V if isinstance(x, dict)) / max(len(V), 1), 2)}))
assert len(V) > 0 or sys.argv[1].endswith("try_neighbours_v1.json"), "0 launches: not uploaded (for 'after', run after the ~09:00 PT store merge)"
PY
# PROMOTED (orchestrator 13:17Z Nov 13): the live copy is results/web/why/ (read by the website renderer); the shadow copy
# keeps being written until 2026-11-20 for diffing
gsutil -q cp "$W/out/$F" "$B/results/web/why/$F"; echo "wrote $B/results/web/why/$F"
if [[ "$(date -u +%F)" < "2026-11-21" ]]; then gsutil -q cp "$W/out/$F" "$B/results/web/why_shadow/$F"; echo "wrote $B/results/web/why_shadow/$F"; fi
