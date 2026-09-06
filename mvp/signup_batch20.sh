#!/usr/bin/env bash
# Batch-signup against 20 public products. Serial, fail-early per product.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${ROOT}"

if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi

OUT_DIR="${ROOT}/results/signup_batch"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="${OUT_DIR}/batch_${STAMP}.jsonl"
SUMMARY="${OUT_DIR}/batch_${STAMP}_summary.json"

# 20 public products with free/freemium signup paths (homepages; agent finds Sign up).
PRODUCTS=(
  "https://linear.app"
  "https://www.notion.so"
  "https://todoist.com"
  "https://clickup.com"
  "https://calendly.com"
  "https://airtable.com"
  "https://www.canva.com"
  "https://www.figma.com"
  "https://miro.com"
  "https://www.loom.com"
  "https://coda.io"
  "https://bitwarden.com"
  "https://www.dropbox.com"
  "https://zoom.us"
  "https://buffer.com"
  "https://webflow.com"
  "https://github.com"
  "https://gitlab.com"
  "https://www.reddit.com"
  "https://medium.com"
)

TIMEOUT_S="${SIGNUP_TIMEOUT_S:-300}"
MAX_STEPS="${SIGNUP_MAX_STEPS:-28}"
HEADLESS_FLAG=()
if [[ "${SIGNUP_HEADLESS:-1}" == "1" ]]; then
  HEADLESS_FLAG=(--headless)
fi

echo "Batch signup → ${LOG}"
echo "  timeout=${TIMEOUT_S}s  max_steps=${MAX_STEPS}  products=${#PRODUCTS[@]}"
echo "[]" > "$SUMMARY"

idx=0
ok=0
fail=0
for url in "${PRODUCTS[@]}"; do
  idx=$((idx + 1))
  echo ""
  echo "═══ [${idx}/${#PRODUCTS[@]}] ${url} ═══"
  start=$(date +%s)
  set +e
  out=$("${ROOT}/.venv/bin/python" -m mvp.auto_signup \
    --url "$url" \
    --timeout "$TIMEOUT_S" \
    --max-steps "$MAX_STEPS" \
    "${HEADLESS_FLAG[@]}" 2>"${OUT_DIR}/$(echo "$url" | sed 's|https://||;s|/|_|g')_${STAMP}.stderr")
  rc=$?
  set -e
  elapsed=$(( $(date +%s) - start ))
  # auto_signup prints JSON on stdout
  if echo "$out" | "${ROOT}/.venv/bin/python" -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    row=$(echo "$out" | "${ROOT}/.venv/bin/python" -c "
import sys, json
d=json.load(sys.stdin)
d['url']='$url'
d['elapsed_s']=$elapsed
d['exit_code']=$rc
print(json.dumps(d))
")
  else
    row=$(printf '{"url":"%s","ok":false,"reason":"no_json","elapsed_s":%s,"exit_code":%s,"raw":%s}\n' \
      "$url" "$elapsed" "$rc" "$(echo "$out" | "${ROOT}/.venv/bin/python" -c 'import sys,json; print(json.dumps(sys.stdin.read()[:500]))')")
  fi
  echo "$row" | tee -a "$LOG"
  if echo "$row" | grep -q '"ok": true'; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
  fi
  "${ROOT}/.venv/bin/python" - <<PY
import json
from pathlib import Path
rows=[json.loads(l) for l in Path("$LOG").read_text().splitlines() if l.strip()]
summary={
  "stamp": "$STAMP",
  "total": len(rows),
  "ok": sum(1 for r in rows if r.get("ok")),
  "fail": sum(1 for r in rows if not r.get("ok")),
  "by_reason": {},
  "results": rows,
}
for r in rows:
    key = r.get("reason") or ("ok" if r.get("ok") else "unknown")
    summary["by_reason"][key] = summary["by_reason"].get(key, 0) + 1
Path("$SUMMARY").write_text(json.dumps(summary, indent=2) + "\n")
print(f"  running tally: {summary['ok']} ok / {summary['fail']} fail / {summary['total']} done")
PY
done

echo ""
echo "DONE  ok=${ok} fail=${fail}  summary=${SUMMARY}"
"${ROOT}/.venv/bin/python" -m mvp.access_report || true
