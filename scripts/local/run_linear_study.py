"""Start the 24-agent Linear study on the local server and wait for the report."""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:3000"
BODY = {
    "url": "https://linear.app",
    "competitors": ["https://asana.com/", "https://trello.com/"],
    "tasks": ["Find how to create a new issue", "Look for pricing or how to get started"],
    "segment": "Product managers comparing issue trackers",
    "max_agents": 24,
}


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def main() -> int:
    t0 = time.time()
    out = _req("POST", "/api/studies", BODY)
    sid = out.get("id") or out.get("study_id")
    print(f"study {sid} submitted at {time.strftime('%H:%M:%S')}", flush=True)
    first_action = None
    last = ""
    while time.time() - t0 < 620:
        time.sleep(2)
        try:
            st = _req("GET", f"/api/studies/{sid}")
        except Exception as exc:  # noqa: BLE001
            print(f"poll error {exc!r}", flush=True)
            continue
        live = st.get("live_sessions") or []
        rows = list(live.values()) if isinstance(live, dict) else list(live)
        opened = sum(1 for r in rows if r.get("page_open_at_ts"))
        acted = sum(1 for r in rows if r.get("first_action_at_ts"))
        done = len(st.get("agent_results") or [])
        if first_action is None and acted:
            first_action = round(time.time() - t0, 1)
            print(f"first action visible to poller at +{first_action}s", flush=True)
        line = f"+{int(time.time()-t0)}s status={st.get('status')} phase={st.get('phase')} open={opened} acted={acted} done={done}"
        if line.split(' ', 1)[1] != last:
            print(line, flush=True)
            last = line.split(' ', 1)[1]
        if st.get("status") in {"complete", "error", "abandoned"}:
            print(json.dumps({k: st.get(k) for k in ("status", "error", "time_to_first_value_s", "time_to_first_value_agent", "total_time_s")}), flush=True)
            break
    print(f"STUDY_ID={sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
