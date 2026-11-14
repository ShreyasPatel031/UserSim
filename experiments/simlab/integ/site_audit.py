"""Read-side silent-reuse audit of the public /ph site (orchestrator 20:00Z Nov 14). The site's own routes (mvp/ph_site/routes.py on
origin/main) run locally on a FastAPI app; gcs.list_names / read_bytes / read_tail_jsonl are pointed at a local mirror of today's (D) and
yesterday's (D-1) objects. Product Hunt API unconfigured (no token): the live board is only what is persisted. Nothing is written anywhere.
For each file family: (i) missing for D, (ii) only D-1 present (+ *_latest pointers at D-1), (iii) present for D but labelled for another
model or day, (iv) older than its expected write time. Reuse = a D-1 launch id, or a D-1 day/value, shown on D's page as current.
    python site_audit.py <site checkout> <mirror dir> <out json>"""
import copy, json, os, shutil, sys, tempfile
from datetime import datetime, timezone, timedelta
SITE, MIRROR, OUT = sys.argv[1:4]; sys.path.insert(0, SITE)
for k in ("PH_TOKEN", "PH_CLIENT_ID", "PH_CLIENT_SECRET", "VERCEL", "VERCEL_ENV"): os.environ.pop(k, None)
from mvp.ph_site import gcs, live, ph_live, routes
from fastapi import FastAPI
from fastapi.testclient import TestClient
FB = None
def _p(rel): return os.path.join(FB, rel)
def list_names(prefix, ttl=120):
    out = []; base = _p(prefix); root = base if os.path.isdir(base) else os.path.dirname(base)
    for dp, _, fs in os.walk(root):
        for f in fs:
            rel = os.path.relpath(os.path.join(dp, f), FB)
            if rel.startswith(prefix): out.append((rel, datetime.fromtimestamp(os.path.getmtime(os.path.join(dp, f)), timezone.utc).isoformat()))
    return sorted(out)
def read_bytes(path, ttl=300):
    return open(_p(path), "rb").read() if os.path.isfile(_p(path)) else None
def read_tail_jsonl(path, nbytes=400_000, ttl=120):
    raw = read_bytes(path); return [json.loads(x) for x in raw.decode().splitlines() if x.strip()] if raw else []
class NoBucket:
    def blob(self, *a, **k): raise RuntimeError("audit: no writes")
    client = None
gcs.list_names, gcs.read_bytes, gcs.read_tail_jsonl, gcs._bucket = list_names, read_bytes, read_tail_jsonl, lambda: NoBucket()
app = FastAPI(); app.include_router(routes.router); C = TestClient(app)
D = live.today_pt(); P1 = (datetime.fromisoformat(D) - timedelta(days=1)).strftime("%Y-%m-%d")
def ids_of(day):
    s = set()
    for rel in (f"raw/daily/{day}/today_0005.json", f"raw/daily/{day}/{day}.json"):
        if os.path.isfile(os.path.join(MIRROR, rel)): s |= {str(r["id"]) for r in json.load(open(os.path.join(MIRROR, rel)))}
    return s
IDS_D, IDS_P1 = ids_of(D), ids_of(P1) - ids_of(D)
def fresh():
    global FB
    FB = tempfile.mkdtemp(); shutil.copytree(MIRROR, FB, dirs_exist_ok=True)
    gcs._cache.clear(); ph_live._mem.clear()
    # yesterday's published prediction files (the published era began Nov 14): today's files re-keyed to D-1 with D-1 ids
    m = sorted(IDS_P1)
    for kind in ("0005", "prereveal"):
        src = _p(f"results/web/predictions/{D}_{kind}.json")
        if os.path.isfile(src):
            J = json.load(open(src)); J["day"] = P1; J["written_at"] = f"{P1}T08:06:00+00:00"
            J["ranking"] = [{**r, "id": m[i % len(m)], "name": "YESTERDAY"} for i, r in enumerate(J["ranking"])]
            json.dump(J, open(_p(f"results/web/predictions/{P1}_{kind}.json"), "w"))
def rm(*rels):
    for r in rels:
        p = _p(r)
        if os.path.isdir(p): shutil.rmtree(p)
        elif os.path.exists(p): os.remove(p)
def edit(rel, fn):
    J = json.load(open(_p(rel))); J = fn(J) or J; json.dump(J, open(_p(rel), "w"))
def latest_to_p1():
    for kind in ("0005", "prereveal"):
        s = _p(f"results/web/predictions/{P1}_{kind}.json")
        if os.path.isfile(s): shutil.copy(s, _p(f"results/web/predictions/{kind}_latest.json"))
def view():
    gcs._cache.clear(); ph_live._mem.clear(); r = C.get("/api/ph/today"); j = r.json()
    pts = [{"key": p["key"], "method": p.get("method"), "fallback": p.get("fallback"), "source": p.get("source"), "made": p.get("time_pt"), "late": p.get("late"),
            "top3": [i for i, n in sorted(p["ranks"].items(), key=lambda t: t[1])][:3], "backtest_line": (p.get("backtest_line") or "")[:70]} for p in j.get("points", [])]
    shown = {x["id"] for x in j.get("launches", [])} | {i for p in j.get("points", []) for i in p["ranks"]}
    acc = {k: [(r["flag"], r["top3"], r.get("days")) for r in v][:3] for k, v in (j.get("accuracy") or {}).items()}
    return {"status": r.status_code, "day": j.get("day"), "n_launches": len(j.get("launches", [])), "points": pts,
            "yesterday ids shown": sorted(shown & IDS_P1)[:5], "n yesterday ids shown": len(shown & IDS_P1),
            "freshness": {k: j.get("freshness", {}).get(k) for k in ("missing_points", "board_stale", "board_stale_label")},
            "board": j.get("board"), "why": {k: v.get("as_of") for k, v in (j.get("why") or {}).items()}, "accuracy": acc, "input_flag": j.get("input_flag")}
def weekly():
    gcs._cache.clear(); r = C.get("/api/ph/weekly"); j = r.json() or {}
    return {"status": r.status_code, "week_monday": j.get("week_monday"), "as_of_day": j.get("as_of_day"), "point": j.get("point"), "written_at": j.get("written_at"),
            "top3": [x.get("id") for x in (j.get("top") or [])][:3], "month": {k: (j.get("month") or {}).get(k) for k in ("month", "as_of_day", "written_at")}}
R = {"today (D)": D, "yesterday (D-1)": P1, "lineup ids D / D-1 only": [len(IDS_D), len(IDS_P1)], "cases": {}}
def case(name, setup, fn=view):
    fresh(); setup(); R["cases"][name] = fn(); print(json.dumps({name: R["cases"][name]}, default=str)[:600], flush=True)
case("S0 baseline", lambda: None)
# F1/F2 published predictions
case("F1(i) D_0005 missing", lambda: rm(f"results/web/predictions/{D}_0005.json"))
case("F1(ii) D_0005 missing, D-1 file + 0005_latest at D-1", lambda: (rm(f"results/web/predictions/{D}_0005.json"), latest_to_p1()))
case("F1(ii') D-1 content copied under D's name", lambda: shutil.copy(_p(f"results/web/predictions/{P1}_0005.json"), _p(f"results/web/predictions/{D}_0005.json")))
case("F1(iii) D_0005 model clean_nosite but arm-2 label", lambda: edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "model": "clean_nosite", "fallback_used": "clean_nosite_fallback"}))
case("F1(iii') D_0005 none_available (legacy forecast_0005 export present)", lambda: edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "model": None, "fallback_used": "none_available", "ranking": [], "backtest": "no model ran (no forecast for this night)"}))
case("F1(iv) D_0005 written yesterday 20:00 PT (before its 00:05 cut)", lambda: edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "written_at": f"{D}T04:00:00+00:00"}))
case("F1(iv') D_0005 written 09:30 PT (late)", lambda: edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "written_at": f"{D}T17:30:00+00:00"}))
case("F2(i) D_prereveal missing", lambda: rm(f"results/web/predictions/{D}_prereveal.json"))
case("F2(ii) D_prereveal missing, D-1 file + latest at D-1", lambda: (rm(f"results/web/predictions/{D}_prereveal.json"), latest_to_p1()))
case("F2(iii) D_prereveal midnight_order with hybrid label", lambda: edit(f"results/web/predictions/{D}_prereveal.json", lambda J: {**J, "model": "midnight_order", "fallback_used": "midnight_order"}))
case("F1+F2(i) both published files missing (cutover passed)", lambda: rm(f"results/web/predictions/{D}_0005.json", f"results/web/predictions/{D}_prereveal.json"))
# F3/F4 legacy 00:05 sources and the line-up
case("F3(ii) forecast_0005/D.json holds D-1's export (+ D_0005 none_available)", lambda: (shutil.copy(_p(f"results/web/forecast_0005/{P1}.json"), _p(f"results/web/forecast_0005/{D}.json")),
     edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "model": None, "fallback_used": "none_available", "ranking": []})))
case("F4(i) raw/daily/D missing (line-up files)", lambda: rm(f"raw/daily/{D}"))
case("F4(ii) raw/daily/D/today_0005.json holds D-1's line-up", lambda: (shutil.copy(_p(f"raw/daily/{P1}/today_0005.json"), _p(f"raw/daily/{D}/today_0005.json"))))
# F5 why
case("F5(ii) why D_0005 holds D-1's file", lambda: shutil.copy(_p(f"results/web/why/{P1}_0005.json"), _p(f"results/web/why/{D}_0005.json")))
case("F5(iii) why D_0005 present while 00:05 is a clean_nosite fallback", lambda: edit(f"results/web/predictions/{D}_0005.json", lambda J: {**J, "model": "clean_nosite", "fallback_used": "clean_nosite_fallback"}))
# F6 live board (no API token: persisted snapshots only)
case("F6(i) live_board latest + D missing", lambda: rm("site/live_board/latest.json", f"site/live_board/{D}.json"))
case("F6(ii) live_board latest holds D-1's board", lambda: (rm(f"site/live_board/{D}.json"), shutil.copy(_p(f"site/live_board/{P1}.json"), _p("site/live_board/latest.json"))))
case("F6(iv) live_board latest from today 01:00 PT", lambda: edit("site/live_board/latest.json", lambda J: {**J, "fetched_at": f"{D}T09:00:00+00:00"}))
# F7 track record / scoreboard
case("F7(i) track_record_v1.json missing", lambda: rm("tmp/e5/website/track_record_v1.json"))
case("F7(iv) track_record_v1.json written 5 days ago", lambda: edit("tmp/e5/website/track_record_v1.json", lambda J: {**J, "written_at": "2026-11-09T09:25:00+00:00", "built_at": "2026-11-09T09:25:00+00:00"}))
case("F8(iii) scoreboard day_flags only for D-1", lambda: edit("results/web/scoreboard.json", lambda J: {**J, "day_flags": {P1: "built on polluted hunter-history inputs (yesterday)"}}))
# F9 weekly / monthly
case("F9 baseline weekly", lambda: None, weekly)
case("F9(i) weekly_latest pointer missing", lambda: rm("results/web/weekly_latest.json"), weekly)
case("F9(iv) weekly_latest points at last week's file", lambda: edit("results/web/weekly_latest.json", lambda J: {**J, "points": {"running": {"file": "results/weekly_live/2026-11-09_2026-11-11_R4.json", "day": "2026-11-11"}}}), weekly)
case("F9(iv') newest monthly_live is last month's", lambda: (rm("results/monthly_live"), os.makedirs(_p("results/monthly_live")),
     json.dump({**json.load(open(os.path.join(MIRROR, "results/monthly_live/2026-11_2026-11-13_running.json"))), "month": "2026-10", "day": "2026-10-31"}, open(_p("results/monthly_live/2026-10_2026-10-31_running.json"), "w"))), weekly)
json.dump(R, open(OUT, "w"), indent=1, default=str); print("done")
