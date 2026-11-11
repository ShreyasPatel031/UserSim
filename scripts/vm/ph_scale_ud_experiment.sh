#!/usr/bin/env bash
# Scale-up vs scale-down bake on the 403'd feeder arms; stop at first BLOCK.
#   ./scripts/vm/ph_scale_ud_experiment.sh start   # A=scale_up, D=scale_down
#   ./scripts/vm/ph_scale_ud_experiment.sh sample
#   ./scripts/vm/ph_scale_ud_experiment.sh watch    # poll until both ding or timeout
#   ./scripts/vm/ph_scale_ud_experiment.sh summary
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:?}"
ZONE="${PACE_ZONE:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"
GC=(gcloud --account="$SA")
RUN_ID="${PACE_CEILING_BASE_RUN:-20261107t170953z}"
ART_ROOT="${ROOT}/results/ph_scale_ud"
VM_GCS="gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm"

# A/D were the arms that already 403'd at fixed-32; B stays the clean control if still up.
ARMS=(
  "a:scale_up:${ROOT}/scripts/vm/ph_strategies/scale_up.env"
  "d:scale_down:${ROOT}/scripts/vm/ph_strategies/scale_down.env"
)
vm() { echo "feeder-strat-${RUN_ID}-${1}"; }

art_dir() {
  if [[ -f "${ART_ROOT}/latest.txt" ]]; then
    ART="$(cat "${ART_ROOT}/latest.txt")"
  else
    echo "no scale_ud run; start first" >&2
    exit 1
  fi
}

cmd_start() {
  mkdir -p "$ART_ROOT"
  ART="${ART_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$ART"
  echo "$ART" >"${ART_ROOT}/latest.txt"
  GO_TOKEN="run:scaleud-$(date -u +%Y%m%dT%H%M%SZ)"
  GO_TOKEN="${GO_TOKEN,,}"
  echo "$GO_TOKEN" >"$ART/go_token.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo -e "sid\tstrat\tvm\tenv" >"$ART/arms.tsv"
  echo -e "# ts\tsid\tstrat\tjson\tblocks\tpulls\tramp\tnote" >"$ART/samples.tsv"

  "${GC[@]}" storage cp \
    "$ROOT/scripts/vm/reuse_overlays/supervisor_strat.sh" \
    "$ROOT/scripts/vm/reuse_overlays/portscreen.py" \
    "$ROOT/scripts/vm/reuse_overlays/strategy_args.py" \
    "$ROOT/scripts/vm/reuse_overlays/ensure_geoip.sh" \
    "$ROOT/scripts/vm/reuse_overlays/patch_week_bytes.py" \
    "$ROOT/scripts/vm/reuse_overlays/patch_stop_first_block.py" \
    "$ROOT/scripts/vm/reuse_overlays/ceiling_relaunch.sh" \
    "$ROOT/scripts/vm/ph_strategies/scale_up.env" \
    "$ROOT/scripts/vm/ph_strategies/scale_down.env" \
    "${VM_GCS}/_code/overlays/" >/dev/null

  # Relaunch helper: apply both patches + named strategy env (not ceiling_N.env).
  cat >"$ART/scale_relaunch.sh" <<'EOS'
#!/bin/bash
set +e
STRAT_FILE="${1:?scale_up.env|scale_down.env}"
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
gcloud storage cp -q "$B/_code/overlays/supervisor_strat.sh" "$B/_code/overlays/portscreen.py" \
  "$B/_code/overlays/strategy_args.py" "$B/_code/overlays/ensure_geoip.sh" \
  "$B/_code/overlays/patch_week_bytes.py" "$B/_code/overlays/patch_stop_first_block.py" /opt/ph/overlays/
gcloud storage cp -q "$B/_code/overlays/${STRAT_FILE}" /opt/ph/strategy.env
chmod +x /opt/ph/overlays/ensure_geoip.sh /opt/ph/overlays/supervisor_strat.sh
PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/ensure_geoip.sh
cp -f /opt/ph/overlays/portscreen.py /opt/ph/reuse/portscreen.py
cp -f /opt/ph/overlays/strategy_args.py /opt/ph/reuse/strategy_args.py
# Re-apply patches after every reuse.tgz unpack
if ! grep -q patch_week_bytes /opt/ph/overlays/supervisor_strat.sh; then
  awk '
    /apply_overlays/ && !done {
      print
      print "  gcloud storage cp -q \"$B/_code/overlays/patch_week_bytes.py\" \"$B/_code/overlays/patch_stop_first_block.py\" /opt/ph/overlays/ 2>/dev/null || true"
      print "  /opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py >> supervisor.log 2>&1 || true"
      print "  /opt/venv/bin/python /opt/ph/overlays/patch_stop_first_block.py >> supervisor.log 2>&1 || true"
      done=1; next
    }
    { print }
  ' /opt/ph/overlays/supervisor_strat.sh > /tmp/sup.sh && mv /tmp/sup.sh /opt/ph/overlays/supervisor_strat.sh
fi
sed -i -E '/^PH_(STRATEGY|TABS|BROWSER_TABS|MAX_INFLIGHT|RAMP|REQ_PER_MIN|PERSON_INTERVAL|START_|AIMD_|BURST_|COAST_|LAZY_|CIRCUIT_|INTER_REQ|SKIP_|SERIALIZE_|STOP_ON)/d' /opt/ph/pace.env
grep -q PH_PORTSCREEN_HOME_ONLY= /opt/ph/pace.env || echo PH_PORTSCREEN_HOME_ONLY=1 >> /opt/ph/pace.env
systemctl stop phsuper 2>/dev/null || true
pkill -f ph_batch.py 2>/dev/null || true
sleep 1
rm -f /opt/ph/reuse/last_token
rm -rf /opt/ph/profiles
mkdir -p /opt/ph/profiles /opt/ph/golden_quarantine
mv /opt/ph/reuse/out "/opt/ph/golden_quarantine/out.scaleud.$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null || true
mkdir -p /opt/ph/reuse/out
: > /opt/ph/reuse/setup_timing.jsonl
/opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py || true
/opt/venv/bin/python /opt/ph/overlays/patch_stop_first_block.py || true
set -a; source /opt/ph/pace.env; source /opt/ph/strategy.env; set +a
echo -n "args="; /opt/venv/bin/python /opt/ph/reuse/strategy_args.py; echo
echo "STOP_ON_FIRST_BLOCK=${PH_STOP_ON_FIRST_BLOCK:-}"
grep -n "STOP_ON_FIRST_BLOCK_PATCH\|WEEK_BYTES_CACHE" /opt/ph/reuse/ph_batch.py | head -6
systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse \
  -p EnvironmentFile=/opt/ph/pace.env -p EnvironmentFile=/opt/ph/strategy.env \
  /bin/bash -c 'bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1'
sleep 1
systemctl is-active phsuper || true
echo DONE
EOS
  "${GC[@]}" storage cp "$ART/scale_relaunch.sh" "${VM_GCS}/_code/overlays/scale_relaunch.sh" >/dev/null

  for spec in "${ARMS[@]}"; do
    IFS=: read -r sid strat envf <<<"$spec"
    name="$(vm "$sid")"
    envbase="$(basename "$envf")"
    echo -e "${sid}\t${strat}\t${name}\t${envbase}" >>"$ART/arms.tsv"
    echo "==> $strat on $name"
    "${GC[@]}" storage cp "$envf" "${VM_GCS}/_code/overlays/${envbase}" >/dev/null
    "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" --project="$PROJECT" \
      --metadata-from-file="ph-strategy-env=${envf}" >/dev/null
    set +e
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet \
      --command="sudo bash -c 'set +e; B=\$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-); gcloud storage cp -q \$B/_code/overlays/scale_relaunch.sh /tmp/scale_relaunch.sh; chmod +x /tmp/scale_relaunch.sh; bash /tmp/scale_relaunch.sh ${envbase}'" \
      </dev/null 2>&1 | grep -vE 'NumPy|setlocale|WARNING:|cloud.google.com/iap|To increase|Warning: Permanently|known hosts' | tail -20
    set -e
    echo "$GO_TOKEN" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}"
  done
  echo "GO=$GO_TOKEN"
  echo "ART=$ART"
}

sample_one() {
  local sid=$1 strat=$2 name=$3 ts=$4
  local remote
  remote='L=$(ls -t /opt/ph/reuse/run_*.log 2>/dev/null | head -1)
json=$(find /opt/ph/reuse/out -name "*.json" ! -name "_*" 2>/dev/null | wc -l)
blocks=$(grep -cE "BLOCK " "$L" 2>/dev/null || true)
pulls=$(grep -cE " paged_v2 " "$L" 2>/dev/null || true)
ramp=$(grep "RAMP " "$L" 2>/dev/null | tail -1 | tr " \t" "_" | cut -c1-80)
alive=$(pgrep -f "python.*ph_batch" >/dev/null && echo 1 || echo 0)
fp=$(grep -c FINGERPRINT_ "$L" 2>/dev/null || true)
pull_utc=$(grep first_pull /opt/ph/reuse/setup_timing.jsonl 2>/dev/null | tail -1 | sed -n "s/.*\"utc\":\"\\([^\"]*\\)\".*/\\1/p")
echo "$json $blocks $pulls $alive ${ramp:-.} ${fp:-0} ${pull_utc:-.}"'
  local line json blocks pulls alive ramp fp pull_utc
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --command="sudo bash -c $(printf '%q' "$remote")" </dev/null 2>/dev/null)" || line="0 0 0 0 . 0 ."
  read -r json blocks pulls alive ramp fp pull_utc <<<"$line"
  echo -e "${ts}\t${sid}\t${strat}\t${json}\t${blocks}\t${pulls}\t${ramp}\talive=${alive}|fp=${fp}|first_pull=${pull_utc}"
  echo -e "${ts}\t${sid}\t${strat}\t${json}\t${blocks}\t${pulls}\t${ramp}\talive=${alive}|fp=${fp}|first_pull=${pull_utc}" >>"$ART/samples.tsv"
}

cmd_sample() {
  art_dir
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  while IFS=$'\t' read -r sid strat name _env; do
    [[ "$sid" == "sid" || -z "$sid" ]] && continue
    sample_one "$sid" "$strat" "$name" "$ts"
  done <"$ART/arms.tsv"
}

cmd_watch() {
  art_dir
  local max_min="${1:-90}"
  local end=$((SECONDS + max_min * 60))
  echo "watching up to ${max_min}m for first BLOCK on each arm"
  while (( SECONDS < end )); do
    cmd_sample
    # both dinged?
    python3 - <<'PY' "$ART" && break
import sys
from pathlib import Path
from collections import defaultdict
art = Path(sys.argv[1])
last = {}
for line in (art/"samples.tsv").read_text().splitlines():
    if line.startswith("#") or not line.strip(): continue
    p = line.split("\t")
    if len(p) < 5: continue
    last[p[1]] = int(p[4] or 0)
arms = {r.split("\t")[0] for r in (art/"arms.tsv").read_text().splitlines()[1:] if r.strip()}
ok = arms and all(last.get(a, 0) >= 1 for a in arms)
sys.exit(0 if ok else 1)
PY
    sleep 60
  done
  cmd_summary
}

cmd_summary() {
  art_dir
  python3 - <<'PY' "$ART"
import json, sys
from pathlib import Path
from datetime import datetime, timezone
art = Path(sys.argv[1])
arms = {}
for line in (art/"arms.tsv").read_text().splitlines()[1:]:
    if not line.strip(): continue
    sid, strat, vm, env = line.split("\t")
    arms[sid] = {"strat": strat, "vm": vm, "env": env}

last = {}
for line in (art/"samples.tsv").read_text().splitlines():
    if line.startswith("#") or not line.strip(): continue
    p = line.split("\t")
    if len(p) < 8: continue
    ts, sid, strat, json_n, blocks, pulls, ramp, note = p[:8]
    last[sid] = {
        "ts": ts, "strat": strat, "json": int(json_n or 0), "blocks": int(blocks or 0),
        "pulls": int(pulls or 0), "ramp": ramp, "note": note,
    }

def parse_utc(s):
    if not s or s == ".": return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

rows = []
print("sid\tstrat\tjson\tblocks\tfirst_pull\tding_ts\telapsed_min\tpeople_per_min\tramp")
best = None
for sid, meta in sorted(arms.items()):
    s = last.get(sid, {})
    note = s.get("note") or ""
    fp = "."
    if "first_pull=" in note:
        fp = note.split("first_pull=")[-1].split("|")[0]
    pull_t = parse_utc(fp)
    ding_t = parse_utc(s.get("ts")) if (s.get("blocks") or 0) >= 1 else None
    # Prefer ding time from note if we later enrich; else sample ts when blocks>=1
    elapsed = None
    ppm = None
    if pull_t and ding_t:
        elapsed = max(0.01, (ding_t - pull_t).total_seconds() / 60.0)
        ppm = s.get("json", 0) / elapsed
    elif pull_t and ding_t is None:
        # still running — ppm so far to last sample
        now = parse_utc(s.get("ts")) or datetime.now(timezone.utc)
        elapsed = max(0.01, (now - pull_t).total_seconds() / 60.0)
        ppm = s.get("json", 0) / elapsed
    ding_s = ding_t.strftime("%Y-%m-%dT%H:%M:%SZ") if ding_t else "."
    print(f"{sid}\t{meta['strat']}\t{s.get('json',0)}\t{s.get('blocks',0)}\t{fp}\t{ding_s}\t{elapsed and round(elapsed,2)}\t{ppm and round(ppm,3)}\t{s.get('ramp','.')}")
    rows.append((sid, meta["strat"], s.get("json",0), s.get("blocks",0), ppm, elapsed))
    if ppm is not None:
        score = (ppm, s.get("json",0))
        if best is None or score > best[0]:
            best = (score, sid, meta["strat"], ppm, s.get("blocks",0))

summary = {
    "art": str(art),
    "go": (art/"go_token.txt").read_text().strip(),
    "arms": rows,
    "winner": None,
}
if best:
    summary["winner"] = {"sid": best[1], "strat": best[2], "people_per_min": best[3], "blocks": best[4]}
    print(f"\nWINNER: {best[2]} ({best[1]}) people/min={best[3]:.3f} blocks={best[4]}")
(art/"SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")

lines = ["# Scale-up vs scale-down (stop at first 403)", ""]
lines.append(f"- GO: `{(art/'go_token.txt').read_text().strip()}`")
lines.append(f"- Started UTC: `{(art/'started_at.txt').read_text().strip()}`")
lines.append("")
lines.append("| sid | strat | json | blocks | people/min |")
lines.append("|-----|-------|-----:|-------:|-----------:|")
for sid, strat, jn, blk, ppm, _el in rows:
    lines.append(f"| {sid} | {strat} | {jn} | {blk} | {ppm and round(ppm,3) or '?'} |")
if best:
    lines.append("")
    lines.append(f"**Winner:** `{best[2]}` @ {best[3]:.3f} people/min (ding blocks={best[4]}).")
(art/"SUMMARY.md").write_text("\n".join(lines) + "\n")
print(f"ART={art}")
PY
}

case "${1:-}" in
  start) cmd_start ;;
  sample) cmd_sample ;;
  watch) shift; cmd_watch "${1:-90}" ;;
  summary) cmd_summary ;;
  *) echo "usage: $0 start|sample|watch [minutes]|summary"; exit 1 ;;
esac
