"""Port pre-screen (Shreyas 2026-11-04 1:20 PM ET: "check ports and rotate past 403s").
On startup: one test-open of PH through the assigned DataImpulse sticky port. If it is blocked (HTTP 403 hard block,
or tunnel 403), move to the next free port in the people-VM pool. Never prints creds; IPs logged masked to /24.
A Cloudflare JS challenge (cf-mitigated: challenge) is NOT a block - Camoufox clears it - so that port is kept."""
import os, json, time, subprocess, urllib.request, urllib.error, urllib.parse as up
B = os.environ.get("PACE_GCS_VM_ROOT") or ("gs://" + os.environ["MVP_GCS_BUCKET"] + "/usersim_sim/raw/ph_population/people_live/vm")
NEVER = {10001, 10005, 10006, 10020}            # daily capture, babysitter x2, signed-in profile
POOL = [p for p in range(10000, 20001) if p not in NEVER]  # strat/feeder: full sticky range; NEVER reserved
FAILED = set()   # ports that failed a probe this session
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"
def mask(ip): return None if not ip else ".".join(ip.split(".")[:3]) + ".0/24"
def _egress_port(logical):
    """DataImpulse: logical port (10000+) is the sticky session. ISP/fixed: URL port only."""
    if os.environ.get("PH_PROXY_FIXED_PORT", "0") in ("1", "true", "yes"):
        u = up.urlparse(os.environ["PROXY_URL"])
        return int(u.port or logical or 0)
    return int(logical)
def _op(port):
    ep = _egress_port(port)
    p = up.urlparse(os.environ["PROXY_URL"]); pu = f"{p.scheme}://{p.username}:{p.password}@{p.hostname}:{ep}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": pu, "https": pu}))
def probe(port):
    op = _op(port); o = {"port": port}
    try: o["ip24"] = mask(json.loads(op.open("https://ipinfo.io/json", timeout=15).read()).get("ip"))
    except Exception as e: o["ip_err"] = str(e)[:80].split("@")[-1]
    try:
        r = op.open(urllib.request.Request("https://www.producthunt.com/", headers={"User-Agent": UA, "Accept": "text/html"}), timeout=25)
        o["status"] = r.status; o["verdict"] = "ok"
    except urllib.error.HTTPError as e:
        b = e.read(6000).decode("utf8", "replace"); o["status"] = e.code; o["cf_mitigated"] = e.headers.get("cf-mitigated")
        if e.code == 403 and (e.headers.get("cf-mitigated") == "challenge" or "Just a moment" in b): o["verdict"] = "challenge_ok"
        else: o["verdict"] = "blocked" if e.code in (403, 429) else "http_err"
    except Exception as e:
        m = str(e); o["err"] = m[:80].split("@")[-1]; o["verdict"] = "blocked" if "403" in m else ("failed_tls" if ("EOF" in m or "SSL" in m or "TLS" in m) else "net_err")
    return o
def _owner_running(owner):
    """Owner VM counts as live if gcloud says RUNNING; if gcloud is unavailable, fall back to a status heartbeat < 20 min."""
    r = subprocess.run(["gcloud", "compute", "instances", "list", f"--filter=name={owner}", "--format=value(status)"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0 and r.stdout.strip(): return r.stdout.strip().splitlines()[0] == "RUNNING"
    if r.returncode == 0: return False   # instance not found
    h = subprocess.run(["gsutil", "-q", "stat", f"{B}/status/{owner}.jsonl"], capture_output=True, text=True)
    import re, datetime as dt
    m = re.search(r"Update time:\s+(.+)", h.stdout)
    if not m: return True                # unknown -> be safe, treat as taken
    t = dt.datetime.strptime(m.group(1).strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() < 1200
def _claim(port, vm):
    """GCS claim so two VMs never share a port. Own claim reused; a claim held by a RUNNING other VM = taken;
    a stale claim (owner not running) is taken over. Claim is written immediately on pick (before probe)."""
    obj = f"{B}/_ports/port.{port}"
    cur = subprocess.run(["gsutil", "-q", "cat", obj], capture_output=True, text=True)
    if cur.returncode == 0:
        owner = cur.stdout.strip()
        if owner == vm: return True
        if owner and _owner_running(owner): return False
        r = subprocess.run(["gsutil", "-q", "cp", "-", obj], input=vm, text=True, capture_output=True)
        return r.returncode == 0
    r = subprocess.run(["gsutil", "-q", "-h", "x-goog-if-generation-match:0", "cp", "-", obj], input=vm, text=True, capture_output=True)
    return r.returncode == 0
def _release(port, vm):
    obj = f"{B}/_ports/port.{port}"; cur = subprocess.run(["gsutil", "-q", "cat", obj], capture_output=True, text=True)
    if cur.returncode == 0 and cur.stdout.strip() == vm: subprocess.run(["gsutil", "-q", "rm", obj], capture_output=True)
def prescreen(vm, log):
    home = int(os.environ.get("PROXY_PORT") or 0)
    if os.environ.get("PH_PROXY_FIXED_PORT", "0") in ("1", "true", "yes"):
        u = up.urlparse(os.environ["PROXY_URL"]); ep = int(u.port or 0)
        if home and ep and home != ep:
            # metadata proxy-port is fleet bookkeeping; egress uses URL port
            pass
        if ep:
            home_only = True
            order = [home] if home else [ep]
            max_try = 1
            tried = []
            if home:
                if _claim(home, vm) or True:
                    o = probe(home); tried.append(o)
                    os.environ["PROXY_PORT"] = str(home)
                    log(event="port_prescreen", home_port=home, chosen_port=home, moved=False,
                        home_only=True, reason="PH_PROXY_FIXED_PORT: single ISP endpoint", tried=tried)
                    return home
            return None
    # Strat bake-off default: stay on assigned sticky port. urllib probe ≠ Camoufox CF clear;
    # failing over silently (e.g. 10022→10000) wrecks the experiment.
    home_only = os.environ.get("PH_PORTSCREEN_HOME_ONLY", "1") not in ("0", "false", "no")
    nearby = [p for p in range(max(10000, home - 32), min(20001, home + 33)) if p != home and p in set(POOL)]
    rest = [p for p in POOL if p != home and p not in nearby]
    if not home_only and os.environ.get("PH_PORTSCREEN_SKIP_REGISTERED", "0") in ("1", "true", "yes"):
        # One listing instead of a gsutil cat + gcloud lookup per port; registered ports are treated as taken.
        import random
        r = subprocess.run(["gsutil", "ls", f"{B}/_ports/"], capture_output=True, text=True)
        taken = {int(x.rsplit(".", 1)[-1]) for x in r.stdout.split() if x.rsplit(".", 1)[-1].isdigit()}
        rest = [p for p in POOL if p != home and p not in taken and p not in FAILED]
        random.shuffle(rest)
        nearby = []
    order = ([home] if home else []) + ([] if home_only else (nearby + rest))
    max_try = int(os.environ.get("PH_PORTSCREEN_MAX_TRY", "1" if home_only else "24"))
    tried = []
    for p in order[: max(1, max_try)]:
        if p in NEVER: continue
        if p in FAILED: tried.append({"port": p, "verdict": "failed_this_session"}); continue
        if not _claim(p, vm): tried.append({"port": p, "verdict": "claimed_by_running_vm"}); continue
        o = probe(p); tried.append(o)
        # challenge_ok / ok / net_err: keep home — Camoufox clears JS challenges; probe is advisory.
        if o["verdict"] in ("ok", "challenge_ok", "net_err") or (home_only and p == home and o["verdict"] != "blocked"):
            if p != home: _release(home, vm)
            os.environ["PROXY_PORT"] = str(p)
            ev = {"event": "port_prescreen", "home_port": home, "chosen_port": p, "moved": p != home,
                  "home_only": home_only,
                  "reason": "home port kept" if p == home else f"home port {home} blocked; next free pool port passed",
                  "tried": tried}
            log(**ev); return p
        FAILED.add(p); _release(p, vm)   # hard blocked only
        time.sleep(5)
    # Last resort for bake-off: keep claimed home even if probe said blocked (browser may still clear).
    if home_only and home:
        if _claim(home, vm) or True:
            os.environ["PROXY_PORT"] = str(home)
            log(event="port_prescreen", home_port=home, chosen_port=home, moved=False,
                home_only=True, reason="home_only forced keep after probe failures", tried=tried)
            return home
    log(event="port_prescreen", home_port=home, chosen_port=None, moved=False, reason="no pool port passed; stopping", tried=tried)
    return None
if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]: print(json.dumps(probe(int(a))))
