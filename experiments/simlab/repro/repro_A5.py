"""Repro A5 (stability review Nov 14): the public payload must carry only the two published predictions. With no published
results/web/predictions/<d>_prereveal.json, the server must not present a shadow line (P1-P4 'best' or the agent-written P345 hybrid) as
the 03:45 prediction without a fallback label, and live.forecasts(day) must hold no shadow points (P*/R*). Also checks ph.html's
pointFor('pre') has no P1-P4 fallback. No network: in-memory GCS.
    python repro_A5.py <ph-website checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, types, json, re, importlib.util
ROOT = sys.argv[1]; D = "2026-11-20"
store = {f"results/web/forecast_0005/{D}.json": {"day": D, "forecast": [{"id": str(i), "predicted_rank": i} for i in range(1, 13)]},
         f"results/early_forecast/{D}_P1.json": {"written_at": f"{D}T09:00:00Z", "forecast": [{"id": str(i), "pred_rank": i, "pred_rank_best": 13 - i} for i in range(1, 13)]},
         f"results/early_forecast/{D}_P345.json": {"written_at": f"{D}T11:45:00Z", "forecast": [{"id": str(i), "pred_rank_hybrid": 13 - i} for i in range(1, 13)]}}
g = types.ModuleType("mvp.ph_site.gcs"); g.ROOT = "usersim_sim"
g.read_json = lambda path, ttl=0: store.get(path); g.read_bytes = lambda path, ttl=0: None; g._cached = lambda k, t, fn: fn()
g.list_names = lambda prefix, ttl=0: []; g.read_jsonl = lambda path, ttl=0: []; g.read_tail_jsonl = lambda path, nbytes=0, ttl=0: []; g.read_parquet_cols = lambda *a, **k: None
sys.modules.setdefault("mvp", types.ModuleType("mvp")); sys.modules["mvp"].__path__ = [f"{ROOT}/mvp"]
pkg = types.ModuleType("mvp.ph_site"); pkg.__path__ = [f"{ROOT}/mvp/ph_site"]; pkg.gcs = g; sys.modules["mvp.ph_site"] = pkg; sys.modules["mvp.ph_site.gcs"] = g
spec = importlib.util.spec_from_file_location("mvp.ph_site.live", f"{ROOT}/mvp/ph_site/live.py"); lv = importlib.util.module_from_spec(spec); sys.modules["mvp.ph_site.live"] = lv; spec.loader.exec_module(lv)
F = lv.forecasts(D); keys = sorted(F)
shadow = [k for k in keys if k not in ("0005", "PRE")]
pre = F.get("PRE"); pre_unlabelled_shadow = bool(pre) and "P345" in str(pre.get("source", "")) and not pre.get("fallback")
html = open(f"{ROOT}/mvp/static/ph.html").read(); m = re.search(r"function pointFor\(v\)\{(.*?)\n\}", html, re.S)
html_p_fallback = bool(m and re.search(r"P\\d", m.group(1)))
ok = not shadow and not pre_unlabelled_shadow and not html_p_fallback
print(json.dumps({"forecast keys in payload": keys, "shadow points": shadow, "PRE from agent P345 without fallback label": pre_unlabelled_shadow,
                  "ph.html pre tab falls back to P1-P4": html_p_fallback, "A5 fixed": ok}))
sys.exit(0 if ok else 1)
