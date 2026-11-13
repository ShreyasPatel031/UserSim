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
orders=[o for o in d.get("data", []) if (o.get("proxy_data") or {}).get("proxies")]
if not orders:
    raise SystemExit("no ISP order with proxies in API response")
proxies=[]
port=None
for o in sorted(orders, key=lambda x: -len(x["proxy_data"]["proxies"])):
    pd=o["proxy_data"]
    if not port:
        port=pd["ports"]["http|https"]
    for p in pd["proxies"]:
        proxies.append({**p, "_order_id": o.get("id")})
seen=set()
uniq=[]
for p in proxies:
    ip=p.get("ip")
    if ip in seen: continue
    seen.add(ip); uniq.append(p)
proxies=uniq
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
fleet_slots = int(__import__("os").environ.get("PACE_IPROYAL_FLEET_SLOTS", "20"))
include_spain = __import__("os").environ.get("PACE_IPROYAL_INCLUDE_SPAIN", "").strip() in (
    "1",
    "true",
    "yes",
)
if include_spain and spain.is_file() and spain.read_text().strip():
    pool_lines.append("secrets/iproyal.purl")
    print("pool head: Spain control", spain)
else:
    print("pool: Finland-only (PACE_IPROYAL_INCLUDE_SPAIN unset)")
fi_cap = max(0, fleet_slots - len(pool_lines))
pool_lines.extend(paths[:fi_cap])
header = (
    "# Slot N → line N. Finland ISP from API (set PACE_IPROYAL_INCLUDE_SPAIN=1 to prepend secrets/iproyal.purl).\n"
)
spares = paths[fi_cap:]
body = "\n".join(pool_lines)
if spares:
    body += "\n# spare Finland:\n" + "\n".join(f"# {p}" for p in spares)
(ROOT / "secrets/iproyal.pool").write_text(header + body + "\n")
oids=sorted({p.get("_order_id") for p in proxies if p.get("_order_id")})
print("pool", len(pool_lines), "fi_in_pool", min(len(paths), fi_cap), "fi_total", len(paths), "orders", oids)
PY
