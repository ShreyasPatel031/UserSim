#!/usr/bin/env bash
# usage: T=<token> apify_scrape.sh names.txt outdir   (curl only; python never sees the token)
set -u
LIST=$1; OUT=$2; mkdir -p "$OUT"; API=https://api.apify.com/v2
slug() { python3 -c 'import re,sys; print(re.sub(r"[^a-z0-9]+","-",sys.argv[1].lower()).strip("-"))' "$1"; }
one() {
  name=$1; s=$(slug "$name"); [ -s "$OUT/$s.json" ] && return
  body=$(python3 -c 'import json,sys; print(json.dumps({"query":sys.argv[1],"platforms":["g2","capterra","trustradius","gartner"],"maxResults":100,"sort":"most_recent","starRatings":[]}))' "$name")
  for a in 1 2 3 4; do
    run=$(curl -sS -m 60 -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d "$body" "$API/acts/zen-studio~software-review-scraper/runs")
    id=$(echo "$run" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])' 2>/dev/null) && break
    echo "$name: start failed ($(echo "$run" | head -c 200)); retry" ; sleep $((30*a))
  done
  [ -z "${id:-}" ] && { echo "$name: GAVE UP"; return; }
  for i in $(seq 1 120); do
    st=$(curl -sS -m 30 -H "Authorization: Bearer $T" "$API/actor-runs/$id" | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(d["status"], d["defaultDatasetId"], d.get("usageTotalUsd"))' 2>/dev/null)
    set -- $st; [ "${1:-}" != "READY" ] && [ "${1:-}" != "RUNNING" ] && [ -n "${1:-}" ] && break; sleep 10
  done
  if [ "${1:-}" != "SUCCEEDED" ]; then echo "$name: run $id ended ${1:-?}"; return; fi
  curl -sS -m 120 -H "Authorization: Bearer $T" "$API/datasets/$2/items?clean=true" > "$OUT/.$s.items"
  python3 -c 'import json,sys,time; items=json.load(open(sys.argv[1])); json.dump({"query":sys.argv[2],"run_id":sys.argv[3],"usd":float(sys.argv[4] or 0),"ts":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"items":items},open(sys.argv[5],"w")); print(sys.argv[2]+":",len(items),"reviews $"+sys.argv[4])' "$OUT/.$s.items" "$name" "$id" "$3" "$OUT/$s.json" && rm -f "$OUT/.$s.items"
}
export -f one slug; export OUT API
tr '\n' '\0' < "$LIST" | xargs -0 -P 4 -I{} bash -c 'one "$@"' _ {}
echo DONE
