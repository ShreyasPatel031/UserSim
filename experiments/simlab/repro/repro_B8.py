"""Integration audit (orchestrator 19:31Z Nov 14): prob_writer must name the model behind each published order and must not apply the
03:45 hybrid replay table to a midnight_order night. Stub gsutil as repro_B3. PASS per case:
  prereveal midnight_order  -> method names the 00:05 rank table, source names model midnight_order
  prereveal stale_read      -> source names hybrid_vm + stale_read, basis_note present
  prereveal hybrid_vm       -> source names hybrid_vm, no basis_note (control)
  0005 clean_nosite         -> rank table, basis_note says chances likely a little high
    python repro_B8.py <prob_writer.py>     exit 0 = fixed"""
import sys, os, json, subprocess, tempfile
W = sys.argv[1]; t = tempfile.mkdtemp(); D = "2026-11-10"; res = {}
RK = [{"rank": i + 1, "id": str(1000 + i)} for i in range(12)]
os.makedirs(f"{t}/bin"); open(f"{t}/bin/gsutil", "w").write(f"""#!/bin/bash
a=("$@"); [ "$1" = -q ] && a=("${{a[@]:1}}")
case "${{a[0]}}" in cat) case "${{a[1]}}" in *predictions/{D}_0005.json) cat {t}/0005.json;; *predictions/{D}_prereveal.json) cat {t}/prereveal.json;; *) exit 1;; esac;;
  cp) case "${{a[1]}}" in gs://*) exit 1;; *) exit 0;; esac;; *) exit 1;; esac
"""); os.chmod(f"{t}/bin/gsutil", 0o755); env = {**os.environ, "PATH": f"{t}/bin:" + os.environ["PATH"]}
def go(kind, J, check, tag):
    json.dump(J, open(f"{t}/{kind}.json", "w")); r = subprocess.run([sys.executable, W, kind, D, t], env=env, capture_output=True, text=True)
    o = json.load(open(f"{t}/prob_{D}_{kind}.json")) if r.returncode == 0 else {}
    res[tag] = {"rc": r.returncode, "method": o.get("method"), "source": o.get("source"), "basis_note": o.get("basis_note"), "PASS": r.returncode == 0 and check(o)}
go("prereveal", {"day": D, "model": "midnight_order", "fallback_used": "midnight_order", "backtest": "54.5 / 64.7 / 76.0 ... model: clean_nosite (fallback) (the 00:05 order, shown at 03:45)", "ranking": RK},
   lambda o: "00:05 rank table" in o["method"] and "midnight_order" in o["source"] and o["basis_n_days"] == 183 and "basis_note" in o, "prereveal midnight_order (clean_nosite night)")
go("prereveal", {"day": D, "model": "hybrid_vm", "fallback_used": "stale_read", "ranking": RK}, lambda o: "hybrid_vm" in o["source"] and "stale_read" in o["source"] and "basis_note" in o, "prereveal stale_read")
go("prereveal", {"day": D, "model": "hybrid_vm", "fallback_used": None, "ranking": RK}, lambda o: "hybrid_vm" in o["source"] and "basis_note" not in o and o["basis_n_days"] == 11, "prereveal hybrid_vm (control)")
go("0005", {"day": D, "model": "clean_nosite", "fallback_used": "clean_nosite_fallback", "ranking": [{**r, "score": 1 - i / 20} for i, r in enumerate(RK)]},
   lambda o: o["method"].startswith("rank table") and "likely a little high" in o.get("basis_note", ""), "0005 clean_nosite")
ok = all(v["PASS"] for v in res.values()); print(json.dumps({**res, "B8 fixed": ok})); sys.exit(0 if ok else 1)
