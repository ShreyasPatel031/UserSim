"""Repro A1 (stability review Nov 14): a past-day final read must not overwrite site/live_board/latest.json, and a cold instance
must still serve today's board from site/live_board/<today>.json when Product Hunt is down. No network: in-memory GCS, frozen clock.
    python repro_A1.py <ph-website checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, types, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ROOT = sys.argv[1]; sys.path.insert(0, ROOT); PT = ZoneInfo("America/Los_Angeles")
store = {}
class Blob:
    def __init__(s, p): s.p = p
    def upload_from_string(s, data, content_type=None, **k): store[s.p] = data
    def exists(s): return s.p in store
    def download_as_bytes(s): return store[s.p].encode() if isinstance(store[s.p], str) else store[s.p]
class Bucket:
    def blob(s, p): return Blob(p)
g = types.ModuleType("mvp.ph_site.gcs"); g.ROOT = "usersim_sim"; g._bucket = lambda: Bucket()
def read_json(path, ttl=0):
    v = store.get(f"{g.ROOT}/{path}"); return json.loads(v) if v else None
g.read_json = read_json; g.read_bytes = lambda path, ttl=0: (store.get(f"{g.ROOT}/{path}") or "").encode() or None
g._cached = lambda key, ttl, fn: fn()
pkg = types.ModuleType("mvp.ph_site"); pkg.__path__ = [f"{ROOT}/mvp/ph_site"]; sys.modules.setdefault("mvp", types.ModuleType("mvp")); sys.modules["mvp"].__path__ = [f"{ROOT}/mvp"]
sys.modules["mvp.ph_site"] = pkg; sys.modules["mvp.ph_site.gcs"] = g; pkg.gcs = g
import importlib.util
spec = importlib.util.spec_from_file_location("mvp.ph_site.ph_live", f"{ROOT}/mvp/ph_site/ph_live.py"); pl = importlib.util.module_from_spec(spec); sys.modules["mvp.ph_site.ph_live"] = pl; spec.loader.exec_module(pl)
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=PT)   # 10:00 PT Nov 14: yesterday (Nov 13) is closed (after 03:00 PT)
class FD(datetime):
    @classmethod
    def now(cls, tz=None): return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
pl.datetime = FD
import os; os.environ["PH_TOKEN"] = "x" * 20
pl._snapshot = lambda day, nodes, final: {"day": day, "fetched_at": NOW.astimezone(timezone.utc).isoformat(), "final": final, "votes_hidden": False, "source": "test", "launches": [{"id": day}]}
TODAY, YDAY = "2026-11-14", "2026-11-13"
pl._persist({"day": TODAY, "fetched_at": NOW.astimezone(timezone.utc).isoformat(), "final": False, "launches": [{"id": "today"}]})
pl._persist({"day": YDAY, "fetched_at": "2026-11-14T06:00:00+00:00", "final": False, "launches": [{"id": "yday"}]})   # last snapshot of yesterday, not final
pl._persist({"day": TODAY, "fetched_at": NOW.astimezone(timezone.utc).isoformat(), "final": False, "launches": [{"id": "today"}]})
pl.board(YDAY, fetch=lambda day: [{"x": 1}])     # a visitor opens yesterday -> final re-read
latest = json.loads(store["usersim_sim/site/live_board/latest.json"])
ok1 = latest["day"] == TODAY
pl._mem.clear()                                   # cold instance; Product Hunt down
def down(day): raise pl.Upstream("rate_limit_reached")
b = pl.board(TODAY, fetch=down); ok2 = bool(b) and b.get("day") == TODAY
print(json.dumps({"latest.json day after a past-day read (want today)": latest["day"], "cold board(today) with PH down": (b or {}).get("day"), "A1 fixed": ok1 and ok2}))
sys.exit(0 if ok1 and ok2 else 1)
