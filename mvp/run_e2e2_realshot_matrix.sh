#!/usr/bin/env bash
# Rerun 24-agent matrix under REAL first-screenshot metric.
set -u
cd /workspace
export PATH="/workspace/.venv/bin:$PATH"
export PYTHONPATH=/workspace/src:/workspace
export E2E2_FIRST_SHOT_S=5
export E2E2_EXPECTED=24 E2E2_MAX_AGENTS=24
export E2E2_STALL_S=200 E2E2_TIMEOUT_S=900 E2E2_MAX_ELAPSED_S=400
export E2E2_MIN_PERSONAS=4
RESULTS=/workspace/results/e2e2_realshot
mkdir -p "$RESULTS"

write_summary() {
  local name="$1" url="$2" out="$3"
  python3 - "$name" "$url" "$out" "$RESULTS" <<'PY'
import json, sys
from pathlib import Path
name, url, out, results = sys.argv[1:5]
p = Path(out) / "result.json"
d = json.loads(p.read_text()) if p.exists() else {}
s = {
  "pass": d.get("pass"),
  "product_url": d.get("product_url") or url,
  "agents": d.get("agents"),
  "yeses": d.get("yeses"),
  "elapsed_s": d.get("elapsed_s"),
  "t_first_task_created_s": d.get("t_first_task_created_s"),
  "t_all_tasks_created_s": d.get("t_all_tasks_created_s"),
  "creation_to_first_real_shot": d.get("creation_to_first_real_shot") or d.get("creation_to_first_shot"),
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
    export E2E2_TASKS=$'Skim the homepage and note what stands out\nFind something to open or watch and try it'
  fi
  export E2E2_OUT_DIR="/workspace/results/e2e2_${name}"
  mkdir -p "$E2E2_OUT_DIR"
  rm -f "$E2E2_OUT_DIR"/*.png "$E2E2_OUT_DIR"/result.json "$E2E2_OUT_DIR"/summary.json
  echo "===== START $name $(date -u +%H:%M:%S) ====="
  python -c "from mvp.kill_switch import kill_all_browserbase, abandon_local_studies; from capability.browserbase_client import BB_OWNER_E2E, reset_local_slots; abandon_local_studies(); print(kill_all_browserbase(owner=BB_OWNER_E2E)); reset_local_slots()"
  set +e
  bash mvp/run_e2e2.sh http://127.0.0.1:3000 2>&1 | tee "/tmp/e2e2_${name}_real.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "===== END $name rc=$rc ====="
  write_summary "$name" "$url" "$E2E2_OUT_DIR" || true
  return 0
}

run_one youtube 'https://www.youtube.com/' $'https://vimeo.com/\nhttps://www.dailymotion.com/' 'People looking for videos to watch' 3 2
run_one mdn24 'https://developer.mozilla.org/' $'https://docs.python.org/\nhttps://devdocs.io/' 'Developers reading documentation' 3 2
run_one etsy24 'https://www.etsy.com/' $'https://www.ikea.com/\nhttps://www.ebay.com/' 'People shopping for handmade goods' 3 2
run_one bbc24 'https://www.bbc.com/news' $'https://www.npr.org/\nhttps://apnews.com/' 'People reading news online' 3 2
run_one excalidraw24 'https://excalidraw.com/' $'https://www.tldraw.com/' 'People making diagrams and whiteboard sketches' 2 3
run_one linear24 'https://linear.app/' $'https://www.notion.so/' 'Product teams managing issues and roadmaps' 2 3
echo ALL_REALSHOT_DONE
