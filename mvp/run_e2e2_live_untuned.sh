#!/usr/bin/env bash
# Full 24-agent e2e2 against LIVE prod on untuned public sites.
set -u
cd /workspace
export PATH="/workspace/.venv/bin:$PATH"
export PYTHONPATH=/workspace/src:/workspace
export E2E_BASE="${E2E_BASE:-https://usersim.vercel.app}"
export E2E2_FIRST_SHOT_S=5
export E2E2_EXPECTED=24 E2E2_MAX_AGENTS=24
export E2E2_STALL_S=240 E2E2_TIMEOUT_S=1200 E2E2_MAX_ELAPSED_S=500
export E2E2_MIN_PERSONAS=4
RESULTS=/workspace/results/e2e2_live_untuned
mkdir -p "$RESULTS"

write_summary() {
  local name="$1" url="$2" out="$3"
  python3 - "$name" "$url" "$out" "$RESULTS" <<'PY'
import json, sys
from pathlib import Path
name, url, out, results = sys.argv[1:5]
p = Path(out) / "result.json"
d = json.loads(p.read_text()) if p.exists() else {}
cts = d.get("creation_to_first_real_shot") or d.get("creation_to_first_shot") or {}
s = {
  "pass": d.get("pass"),
  "product_url": d.get("product_url") or url,
  "agents": d.get("agents"),
  "yeses": d.get("yeses"),
  "elapsed_s": d.get("elapsed_s"),
  "t_first_task_created_s": d.get("t_first_task_created_s"),
  "t_all_tasks_created_s": d.get("t_all_tasks_created_s"),
  "creation_to_first_real_shot": cts,
  "real_shot_max_s": (cts or {}).get("max"),
  "warm_timing": d.get("warm_timing"),
  "fail_reasons": d.get("fail_reasons") or d.get("error"),
  "study_id": d.get("study_id"),
}
(Path(out) / "summary.json").write_text(json.dumps(s, indent=2))
(Path(results) / f"{name}_summary.json").write_text(json.dumps(s, indent=2))
print("SUMMARY", name, json.dumps(s))
PY
}

run_one() {
  local name="$1" url="$2" comps="$3" segment="$4" min_sites="${5:-3}" min_tasks="${6:-2}"
  export E2E2_URL="$url"
  export E2E2_COMPETITORS="$comps"
  export E2E2_SEGMENT="$segment"
  export E2E2_MIN_SITES="$min_sites"
  export E2E2_MIN_TASKS="$min_tasks"
  if [[ "$min_tasks" == "3" ]]; then
    export E2E2_TASKS=$'Skim the homepage and note what stands out\nFind something useful and try it\nLocate pricing, plans, or how to start'
  else
    export E2E2_TASKS=$'Skim the homepage and note what stands out\nFind something useful and open it'
  fi
  export E2E2_OUT_DIR="/workspace/results/e2e2_live_${name}"
  mkdir -p "$E2E2_OUT_DIR"
  rm -f "$E2E2_OUT_DIR"/*.png "$E2E2_OUT_DIR"/result.json "$E2E2_OUT_DIR"/summary.json
  echo "===== START $name $(date -u +%H:%M:%S) url=$url base=$E2E_BASE ====="
  python -c "from mvp.kill_switch import kill_all_browserbase, abandon_local_studies; from capability.browserbase_client import BB_OWNER_E2E, reset_local_slots; abandon_local_studies(); print(kill_all_browserbase(owner=BB_OWNER_E2E)); reset_local_slots()" || true
  set +e
  bash mvp/run_e2e2.sh "$E2E_BASE" 2>&1 | tee "/tmp/e2e2_live_${name}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "===== END $name rc=$rc ====="
  write_summary "$name" "$url" "$E2E2_OUT_DIR" || true
  return 0
}

# Varied untuned sites (not YouTube/MDN/Etsy/BBC/Excalidraw/Linear)
run_one verge 'https://www.theverge.com/' $'https://techcrunch.com/\nhttps://www.wired.com/' 'People reading tech news online' 3 2
run_one airtable 'https://www.airtable.com/' $'https://www.monday.com/' 'Teams organizing work in spreadsheets and bases' 2 3
run_one nike 'https://www.nike.com/' $'https://www.adidas.com/\nhttps://www.newbalance.com/' 'People shopping for sneakers and athletic wear' 3 2
run_one reactdev 'https://react.dev/' $'https://vuejs.org/\nhttps://angular.dev/' 'Developers learning a UI framework' 3 2
run_one canva 'https://www.canva.com/' $'https://www.figma.com/' 'People designing graphics and presentations' 2 3

echo ALL_LIVE_UNTUNED_DONE
python3 - <<'PY'
import json
from pathlib import Path
root = Path('/workspace/results/e2e2_live_untuned')
rows = []
for p in sorted(root.glob('*_summary.json')):
    d = json.loads(p.read_text())
    cts = d.get('creation_to_first_real_shot') or {}
    rows.append({
        'name': p.name.replace('_summary.json',''),
        'pass': d.get('pass'),
        'yeses': d.get('yeses'),
        'agents': d.get('agents'),
        'first': d.get('t_first_task_created_s'),
        'all24': d.get('t_all_tasks_created_s'),
        'p50': cts.get('p50'),
        'p95': cts.get('p95'),
        'max': cts.get('max'),
        'elapsed': d.get('elapsed_s'),
        'url': d.get('product_url'),
        'fail': d.get('fail_reasons'),
    })
print('TABLE')
for r in rows:
    print(r)
Path('/workspace/results/e2e2_live_untuned/CATALOG.md').write_text(
    '# Live untuned e2e2 (prod)\n\n'
    + '| # | Product | PASS | run→first | run→all 24 | creation→real p50/p95/max | elapsed |\n'
    + '|---|---------|------|-----------|------------|---------------------------|---------|\n'
    + '\n'.join(
        f"| {i} | {r['url']} | {'PASS' if r['pass'] else 'FAIL'} | {r['first']} | {r['all24']} | "
        f"{r['p50']} / {r['p95']} / **{r['max']}** | {r['elapsed']} |"
        for i,r in enumerate(rows,1)
    )
    + '\n'
)
print('WROTE CATALOG')
PY
