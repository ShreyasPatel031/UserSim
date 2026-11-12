#!/usr/bin/env bash
# Refresh secrets/iproyal_fi_*.purl + iproyal.pool from IPRoyal API (ISP Dedicated).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/secrets/iproyal.env"
TOKEN="${IPROYAL_API_TOKEN:?}"
curl -sS -m 30 -H "X-Access-Token: ${TOKEN}" \
  "https://apid.iproyal.com/v1/reseller/orders?product_id=9&page=1" -o /tmp/iproyal_fi_orders.json
python3 <<'PY'
import json, pathlib
ROOT=pathlib.Path("/agent/repos/usersim")
d=json.load(open("/tmp/iproyal_fi_orders.json"))
order=next((o for o in d.get("data", []) if (o.get("proxy_data") or {}).get("proxies")), None)
if not order:
    raise SystemExit("no ISP order with proxies in API response")
proxies=order["proxy_data"]["proxies"]
port=order["proxy_data"]["ports"]["http|https"]
(secrets:=ROOT/"secrets").mkdir(exist_ok=True)
paths=[]
for i,p in enumerate(proxies,1):
    u=f"http://{p['username']}:{p['password']}@{p['ip']}:{port}"
    fp=secrets/f"iproyal_fi_{i}.purl"
    fp.write_text(u+"\n")
    paths.append(f"secrets/iproyal_fi_{i}.purl")
    print(i, p["ip"])
(ROOT/"secrets/iproyal.pool").write_text("\n".join(paths)+"\n")
print("pool", len(paths), "order", order.get("id"))
PY
