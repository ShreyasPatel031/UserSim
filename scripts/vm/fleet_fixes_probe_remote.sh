#!/usr/bin/env bash
python3 <<'PY'
import json, os, socket, subprocess, pathlib

h = socket.gethostname()
pd = pathlib.Path("/opt/ph/reuse/pdeep.py")
pp = pathlib.Path("/opt/ph/reuse/ph_person.py")
st = pathlib.Path(f"/opt/ph/reuse/status_{h}.jsonl")
strat = pathlib.Path("/opt/ph/strategy.env").read_text() if pathlib.Path("/opt/ph/strategy.env").exists() else ""
B = os.environ.get("PACE_GCS_VM_ROOT", "")
if not B and pathlib.Path("/opt/ph/pace.env").exists():
    for ln in open("/opt/ph/pace.env"):
        if ln.startswith("PACE_GCS_VM_ROOT="):
            B = ln.split("=", 1)[1].strip()
go = ""
if B:
    r = subprocess.run(["gsutil", "-q", "cat", f"{B}/GO.{h}"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        go = r.stdout.strip().splitlines()[0]
batch = subprocess.call(["pgrep", "-f", "[p]deep.py"], stdout=subprocess.DEVNULL) == 0
sup = subprocess.call(["pgrep", "-f", "supervisor_strat"], stdout=subprocess.DEVNULL) == 0
last_start = None
if st.exists():
    for ln in st.read_text().splitlines()[-100:]:
        try:
            j = json.loads(ln)
        except Exception:
            continue
        if j.get("event") == "start":
            last_start = j
part = "PDEEP_PARTITION_PATCH" in (pd.read_text() if pd.exists() else "")
cff = "CF_FAST_FAIL_PATCH" in (pp.read_text() if pp.exists() else "")
pdeep_go = go.startswith("pdeep:")
full = "PDEEP_MODE=full" in strat and "PH_BLOCK_NEW_PORT=1" in strat
ok = batch and part and cff and pdeep_go and full and sup
why = []
if not batch:
    why.append("no_pdeep")
if not part:
    why.append("no_partition_patch")
if not cff:
    why.append("no_cf_patch")
if not pdeep_go:
    why.append("go_not_pdeep")
if not full:
    why.append("strategy")
if not sup:
    why.append("no_supervisor")
print(json.dumps({"ok": ok, "go": go, "batch": batch, "part": part, "cff": cff, "full": full,
                  "last_mode": (last_start or {}).get("mode"), "why": why}))
PY
