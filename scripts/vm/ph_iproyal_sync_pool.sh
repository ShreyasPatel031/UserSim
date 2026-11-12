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
pool_lines = []
spain = secrets / "iproyal.purl"
fleet_slots = int(__import__("os").environ.get("PACE_IPROYAL_FLEET_SLOTS", "5"))
if spain.is_file() and spain.read_text().strip():
    pool_lines.append("secrets/iproyal.purl")
    print("pool head: Spain control", spain)
fi_cap = max(0, fleet_slots - len(pool_lines))
pool_lines.extend(paths[:fi_cap])
header = (
    "# Slot N → line N. Line 1 = Spain control (secrets/iproyal.purl) when present; "
    "then Finland ISP order from API.\n"
)
spares = paths[fi_cap:]
body = "\n".join(pool_lines)
if spares:
    body += "\n# spare Finland:\n" + "\n".join(f"# {p}" for p in spares)
(ROOT / "secrets/iproyal.pool").write_text(header + body + "\n")
print("pool", len(pool_lines), "fi_in_pool", min(len(paths), fi_cap), "order", order.get("id"))
PY
