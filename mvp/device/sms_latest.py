"""Newest SMS code forwarded to the ntfy topic strictly after `after` (epoch s).
Reuses mvp.sms_provider config; picks the latest message, not the earliest."""
import json, time, httpx
from mvp import sms_provider as s

def newest_code_after(after: float, timeout_s: float = 60, settle_s: float = 4) -> str | None:
    n = s.lease_number("apple")
    topic = n.raw["topic"]
    url = f"{s._ntfy_base()}/{topic}/json"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = httpx.get(url, params={"poll": "1", "since": str(int(after) - 1)}, headers=s._ntfy_headers(), timeout=20)
        ms = [json.loads(l) for l in r.text.splitlines() if l.strip()]
        ms = [m for m in ms if m.get("event") == "message" and m["time"] >= after]
        if ms:
            time.sleep(settle_s)  # in case a second text is in flight, re-poll once
            r = httpx.get(url, params={"poll": "1", "since": str(int(after) - 1)}, headers=s._ntfy_headers(), timeout=20)
            ms2 = [json.loads(l) for l in r.text.splitlines() if l.strip()]
            ms2 = [m for m in ms2 if m.get("event") == "message" and m["time"] >= after] or ms
            m = max(ms2, key=lambda m: m["time"])
            return s._sms_code(m.get("title", ""), m.get("message", ""))
        time.sleep(2)
    return None
