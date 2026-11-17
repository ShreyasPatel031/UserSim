#!/bin/bash
# fetch.py credential redaction (Nov 17): error text recorded as "<Type>: <message>" with user:password@ in URLs replaced by <redacted>@.
# usage (VM, agent): bash deploy_fetch_redact.sh rehearse|deploy|rollback. Base md5 ba8c96a5 required; refuses 23:30-01:00 PT for deploy.
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); DST=$W/experiments/pipeline/fetch.py; BK=$W/backup_fetch_redact; PY=/opt/exp/bin/python3
m8() { md5sum < "$1" | cut -c1-8; }
case "${1:-}" in
rehearse)
  [ "$(m8 $DST)" = ba8c96a5 ] || [ "$(m8 $DST)" = "$(m8 $N/fetch.py)" ] || { echo "installed fetch.py $(m8 $DST) is not the base"; exit 1; }
  T=$(mktemp -d); cp -r $W/experiments/pipeline $T/pipeline; cp $N/fetch.py $T/pipeline/fetch.py
  (cd $T && $PY - <<'PY'
import json
from pipeline import fetch as F
# 1) redaction on a real proxy-shaped error (no network)
e = F._err(Exception("Failed to connect to proxy: http://u1:p1@gw.example.com:823")); assert "u1:p1" not in e and "<redacted>@" in e, e
# 2) end to end through the real route-4 browser session on one launch link (expected to fail at the proxy today); body must hold no credentials
L = json.load(open("/home/agent/w/experiments/ph_predict/data/today/" + sorted(__import__("os").listdir("/home/agent/w/experiments/ph_predict/data/today"))[-1]))
url = next(p["website"].split("?")[0] for p in L if "producthunt.com/r/" in (p.get("website") or ""))
s = F.BrowserSession()
try: r = s.get(url)
finally: s.close()
b = str(r.get("body") or "")
assert "@gw." not in b or "<redacted>@" in b, "credentials still present"
print(json.dumps({"rehearsal": "ok", "status": r.get("status"), "body_has_credentials": False, "body_prefix": b[:60].split("://")[0]}))
PY
  ); rc=$?; rm -rf "$T"; exit $rc;;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  [ "$(m8 $DST)" = ba8c96a5 ] || { echo "refused: installed fetch.py $(m8 $DST) != ba8c96a5"; exit 1; }
  mkdir -p $BK && cp -p $DST $BK/fetch.py.ba8c96a5 && cp $N/fetch.py $DST.new && mv $DST.new $DST
  (cd $W/experiments && $PY -c "from pipeline import fetch, sites; print('import ok')") || { cp -p $BK/fetch.py.ba8c96a5 $DST; echo "import failed: rolled back"; exit 1; }
  echo "DEPLOYED fetch.py $(m8 $DST); rollback: bash $N/deploy_fetch_redact.sh rollback";;
rollback) cp -p $BK/fetch.py.ba8c96a5 $DST && echo "restored $(m8 $DST)";;
*) echo "usage: rehearse|deploy|rollback"; exit 64;;
esac
