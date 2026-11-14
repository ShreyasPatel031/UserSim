"""Bug sweep item 3 (orchestrator 18:35Z Nov 14): prob_writer.py on a none_available night (12a.2 publishes model null, ranking []).
Stub gsutil: `cat` serves the fixture for results/web/predictions/<day>_<kind>.json and fails for everything else; `cp` fails for
downloads, succeeds for the final upload. PASS = exit 0 and status "not published" (no crash, no calibration applied to nothing).
    python repro_B3.py <prob_writer.py>     exit 0 = fixed"""
import sys, os, json, subprocess, tempfile
W = sys.argv[1]; t = tempfile.mkdtemp(); D = "2026-11-10"; res = {}
pub = {"0005": {"day": D, "model": None, "fallback_used": "none_available", "ranking": []},
       "prereveal": {"day": D, "model": None, "fallback_used": "none_available", "ranking": []}}
os.makedirs(f"{t}/bin"); open(f"{t}/bin/gsutil", "w").write(f"""#!/bin/bash
a=("$@"); [ "$1" = -q ] && a=("${{a[@]:1}}")
case "${{a[0]}}" in cat) case "${{a[1]}}" in *predictions/{D}_0005.json) cat {t}/0005.json;; *predictions/{D}_prereveal.json) cat {t}/prereveal.json;; *) exit 1;; esac;;
  cp) case "${{a[1]}}" in gs://*) exit 1;; *) exit 0;; esac;; *) exit 1;; esac
"""); os.chmod(f"{t}/bin/gsutil", 0o755)
env = {**os.environ, "PATH": f"{t}/bin:" + os.environ["PATH"]}
RK = [{"rank": i + 1, "id": str(1000 + i), "score": 2 - i / 10} for i in range(12)]
def go(k, want, tag):
    json.dump(pub[k], open(f"{t}/{k}.json", "w"))
    r = subprocess.run([sys.executable, W, k, D, t], env=env, capture_output=True, text=True); f = f"{t}/prob_{D}_{k}.json"
    out = json.load(open(f)) if os.path.exists(f) else None
    res[f"{k} {tag}"] = {"rc": r.returncode, "status": out and out.get("status"), "method": out and out.get("method"), "err": r.stderr.strip().splitlines()[-1][:160] if r.returncode else "",
              "PASS": r.returncode == 0 and bool(out) and out.get("status") == want}
for k in list(pub): go(k, "not published", "none_available")
pub = {"0005": {"day": D, "model": "arm2", "ranking": RK}, "prereveal": {"day": D, "model": "hybrid_vm", "ranking": [{k_: v for k_, v in r.items() if k_ != "score"} for r in RK]}}
for k in list(pub): go(k, "ok", "normal night (control)")
ok = all(v["PASS"] for v in res.values()); print(json.dumps({**res, "B3 fixed": ok})); sys.exit(0 if ok else 1)
