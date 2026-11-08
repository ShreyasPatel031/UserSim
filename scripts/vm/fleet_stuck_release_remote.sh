#!/usr/bin/env bash
# Run on a fleet VM (bash -s). If pdeep has logged no person for STUCK_SEC, release the claims of the people it
# still holds (logs written this run, no status row yet) and kick it so the supervisor relaunches on a new port.
STUCK_SEC="${STUCK_SEC:-480}"
pid=$(pgrep -f '[p]deep.py' | head -1)
[[ -z "$pid" ]] && { echo "$(hostname) no_pdeep"; exit 0; }
sudo PID="$pid" STUCK_SEC="$STUCK_SEC" /opt/venv/bin/python - <<'PY'
import json, os, socket, subprocess, time
pid = os.environ["PID"]; vm = socket.gethostname(); stuck = int(os.environ["STUCK_SEC"])
env = dict(x.split("=", 1) for x in open(f"/proc/{pid}/environ").read().split("\0") if "=" in x)
sb = env.get("PH_SAVE_B") or env.get("PH_B")
t0 = time.time() - int(subprocess.run(["ps", "-o", "etimes=", "-p", pid], capture_output=True, text=True).stdout.strip())
done, last = set(), t0
for l in open(f"/opt/ph/reuse/status_{vm}.jsonl"):
    try: j = json.loads(l)
    except Exception: continue
    if not j.get("handle"): continue
    t = time.mktime(time.strptime(j["utc"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    if t >= t0: done.add(j["handle"].lower()); last = max(last, t)
if time.time() - last < stuck:
    print(vm, "pulling", int(time.time() - last)); raise SystemExit
out = "/opt/ph/reuse/out"
inf = [f[:-4].lower() for f in os.listdir(out) if f.endswith(".log") and not f.startswith("_") and os.stat(f"{out}/{f}").st_mtime >= t0]
inf = [h for h in inf if h not in done]
rel = []
for h in inf:
    cands = [f"{sb}/claims/{h}"] + subprocess.run(["gsutil", "ls", f"{sb}/claims/rerun_*_{h}"], capture_output=True, text=True).stdout.split()
    for c in cands:
        r = subprocess.run(["gsutil", "cat", c], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.startswith(vm):
            subprocess.run(["gsutil", "-q", "rm", c]); rel.append(c.rsplit("/", 1)[-1])
open("/opt/ph/reuse/KICK", "w").write(f"stuck_release {time.time()}\n")
subprocess.run(["pkill", "-TERM", "-f", "[p]deep.py|[p]h_batch.py"])
time.sleep(4); subprocess.run(["pkill", "-x", "-f", "sleep 120"])
print(vm, "kicked idle", int(time.time() - last), "released", rel)
PY
