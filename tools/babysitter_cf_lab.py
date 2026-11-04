"""Babysitter Camoufox lab: one VM, one DataImpulse sticky port, signed out, read-only Product Hunt profile reads.
Answers in one run:
  P1 cold open (persistent profile)           -> clear time, exit IP/AS
  P2 close + reopen same profile              -> does Cloudflare clearance persist?
  P3 bytes per read: GraphQL JSON vs tab HTML -> MB per item
  P4 parallel GraphQL in one page (1,2,4,8)   -> per-IP request rate edge
  P5 fingerprint_preset=True browser          -> clears on the same IP?
  P6 browsers per VM (1..4, separate procs)   -> aggregate rate, CPU/RAM limit
Stop rule: any step with >=2 blocked responses ends the run (no retry, no new port/IP). Usernames stay on the VM/GCS.
Env: PH_PORT (default 10006), STEP_S (default 180). Output: gs://.../raw/_babysitter/lab/<run>/{events,steps}.jsonl + live.out"""
import datetime as dt, json, multiprocessing as mp, os, random, re, shutil, subprocess, sys, time
from urllib.parse import urlsplit

G = "gs://usersim-bakeoff-347838016394/usersim_sim/"
RUN = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%MZ")
OUT = G + f"raw/_babysitter/lab/{RUN}/"
PORT = int(os.environ.get("PH_PORT", "10006"))
STEP_S = int(os.environ.get("STEP_S", "180"))
OPS = {"upvotes": ("ProfileUpvotesQuery", "7496733c7f8ad1fcaca9c5ef0dac10f28b1198faff3441a51fa5030781798498", {"query": ""}),
       "followers": ("ProfileFollowersQuery", "e3464b823a584638d66d8ec52469068c03b0da0ab575c59af1b737e21577b3c8", {}),
       "following": ("ProfileFollowingQuery", "bc50252859f131bf8e120a10e343cc85de938ba479faea31e49d6e2d91da897e", {}),
       "activity": ("ProfileActivityPage", "01c4f730aa9ebbbbe6d2995662a5b3e66659b613d4ba1b1bad0ac0da6ed45c15", {"filter": "all", "activityLimit": 20})}
GQL_JS = """async (calls)=>Promise.all(calls.map(async ([n,v,h])=>{try{const u='/frontend/graphql?operationName='+n+'&variables='+
 encodeURIComponent(JSON.stringify(v))+'&extensions='+encodeURIComponent(JSON.stringify({persistedQuery:{version:1,sha256Hash:h}}));
 const r=await fetch(u,{headers:{'accept':'application/json','content-type':'application/json'},credentials:'include'});
 const t=await r.text(); return [r.status,t.length,t.slice(0,300).includes('Just a moment'),t.includes('"errors"')];}catch(e){return [-1,0,false,true];}}))"""
HTML_JS = """async (u)=>{const r=await fetch(u,{credentials:'include'});const t=await r.text();
 return [r.status,t.length,t.slice(0,5000).includes('Just a moment'),t.includes('ApolloSSRDataTransport')];}"""


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True).stdout


def emit(kind, **kw):
    rec = dict(t=now(), kind=kind, **kw)
    with open("events.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)
    return rec


def upload():
    sh(f"gsutil -q cp events.jsonl {OUT}events.jsonl; gsutil -q cp live.out {OUT}live.out 2>/dev/null")


def proxy():
    raw = sh(f"gsutil -q cat {G}secrets/proxy_url.txt").strip()
    u = urlsplit(raw)
    user = u.username if "__cr." in u.username else u.username + "__cr.us"
    return {"server": f"http://{u.hostname}:{PORT}", "username": user, "password": u.password}


def sysinfo():
    try:
        load = float(open("/proc/loadavg").read().split()[0])
        mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith(("MemAvailable", "MemTotal"))}
        return dict(load1=load, mem_avail_mb=mem.get("MemAvailable", 0) // 1024)
    except Exception:
        return {}


def people():
    out = []
    for l in sh(f"gsutil -q cat {G}raw/ph_population/people_live/need_list.jsonl").splitlines():
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("tier") == "likely" and d.get("handle"):
            out.append(d["handle"])
    random.seed(RUN)
    random.shuffle(out)
    return out


def open_browser(profile_dir, preset=False, label="b"):
    from camoufox.sync_api import Camoufox
    kw = dict(headless=True, humanize=True, geoip=True, block_images=True, proxy=proxy(), i_know_what_im_doing=True,
              persistent_context=True, user_data_dir=profile_dir)
    if preset:
        kw["fingerprint_preset"] = True
    try:
        cm = Camoufox(**kw)
    except TypeError as e:
        kw.pop("fingerprint_preset", None)
        emit("note", label=label, msg=f"fingerprint_preset unsupported: {str(e)[:80]}")
        cm = Camoufox(**kw)
    ctx = cm.__enter__()
    page = ctx.pages[0] if getattr(ctx, "pages", None) else ctx.new_page()
    exit_ip = {}
    try:
        page.goto("https://ipinfo.io/json", timeout=60000)
        t = re.sub(r"<[^>]+>", "", page.content())
        d = json.loads(t[t.index("{"):t.rindex("}") + 1])
        exit_ip = {k: d.get(k) for k in ("ip", "org", "city", "country")}
    except Exception as e:
        exit_ip = {"err": str(e)[:80]}
    t0 = time.time()
    r = page.goto("https://www.producthunt.com/", timeout=60000)
    ok = False
    for _ in range(30):
        try:
            if "ApolloSSRDataTransport" in page.content():
                ok = True
                break
        except Exception:
            pass
        time.sleep(2)
    emit("open", label=label, preset=preset, profile=os.path.basename(profile_dir), exit=exit_ip, first_status=r.status if r else None,
         cleared=ok, secs=round(time.time() - t0, 1), **sysinfo())
    return cm, page, ok


def gql_calls(handles, ops_cycle):
    calls = []
    for h, op in zip(handles, ops_cycle):
        n, hsh, extra = OPS[op]
        v = dict(username=h, cursor=None, **extra) if op != "activity" else dict(username=h, eventsCursor=None, **extra)
        calls.append([n, v, hsh])
    return calls


def gql_step(page, ppl, conc, label, step_s=STEP_S):
    ops = list(OPS)
    t_end = time.time() + step_s
    n = ok = blocked = errs = byts = 0
    i = 0
    while time.time() < t_end:
        hs = [ppl[(i + k) % len(ppl)] for k in range(conc)]
        cyc = [ops[(i + k) % len(ops)] for k in range(conc)]
        i += conc
        t0 = time.time()
        res = page.evaluate(GQL_JS, gql_calls(hs, cyc))
        for st, ln, ch, err in res:
            n += 1
            byts += ln
            if ch or st in (403, 429):
                blocked += 1
            elif st == 200 and not err:
                ok += 1
            else:
                errs += 1
        if blocked >= 2:
            break
        time.sleep(max(0.0, 1.0 - (time.time() - t0)))
    secs = step_s - max(0, t_end - time.time())
    return emit("step", step=label, conc=conc, requests=n, ok=ok, blocked=blocked, errors=errs, per_min=round(n / (secs / 60), 1),
                kb_per_req=round(byts / max(1, n) / 1024, 1), **sysinfo())


def worker(idx, ppl, conc, step_s, q):
    """P6: one browser in its own process, own persistent profile, same port."""
    try:
        cm, page, ok = open_browser(f"/root/prof_w{idx}", label=f"w{idx}")
        if not ok:
            q.put(dict(idx=idx, cleared=False))
            return
        s = gql_step(page, ppl[idx::7], conc, f"P6_w{idx}", step_s)
        q.put(dict(idx=idx, cleared=True, **{k: s[k] for k in ("requests", "ok", "blocked", "errors", "per_min")}))
        cm.__exit__(None, None, None)
    except Exception as e:
        q.put(dict(idx=idx, err=str(e)[:120]))


def main():
    ppl = people()
    if os.environ.get("LAB_PHASE") == "2":
        emit("run", run=RUN, phase=2, port=PORT, people=len(ppl), **sysinfo()); upload()
        return p5_p6(ppl)
    emit("run", run=RUN, port=PORT, people=len(ppl), cpus=os.cpu_count(), step_s=STEP_S, **sysinfo())
    upload()
    # P1 cold open with a persistent profile
    cm, page, ok = open_browser("/root/prof1", label="P1_cold")
    upload()
    if not ok:
        emit("stop", why="P1 cold open not cleared"); upload(); return
    # P3 bytes: GraphQL JSON vs tab HTML for 6 people
    for h in ppl[:3]:
        st, ln, ch, apollo = page.evaluate(HTML_JS, f"https://www.producthunt.com/@{h}/upvotes")
        emit("bytes", how="html_tab", status=st, kb=round(ln / 1024, 1), challenge=ch, data=apollo)
        time.sleep(3)
    for h in ppl[3:6]:
        st, ln, ch, err = page.evaluate(GQL_JS, gql_calls([h], ["upvotes"]))[0]
        emit("bytes", how="graphql_upvotes_p1", status=st, kb=round(ln / 1024, 1), challenge=ch, error=err)
        time.sleep(3)
    upload()
    # P2 close and reopen the same profile: does clearance persist?
    cm.__exit__(None, None, None)
    time.sleep(10)
    cm, page, ok = open_browser("/root/prof1", label="P2_reopen_same_profile")
    upload()
    if not ok:
        emit("stop", why="P2 reopen not cleared"); upload(); return
    # P4 parallel GraphQL in one page
    for conc in (1, 2, 4, 8):
        s = gql_step(page, ppl[10:], conc, f"P4_c{conc}")
        upload()
        if s["blocked"] >= 2:
            emit("stop", why=f"P4 edge at concurrency {conc}"); upload(); return
    cm.__exit__(None, None, None)
    p5_p6(ppl)


def p5_worker(q):
    """P5 in its own process: Playwright sync API allows one Camoufox per process."""
    try:
        cm5, page5, ok5 = open_browser("/root/prof_preset", preset=True, label="P5_preset")
        q.put(dict(cleared=ok5))
        cm5.__exit__(None, None, None)
    except Exception as e:
        q.put(dict(err=str(e)[:120]))


def p5_p6(ppl):
    # P5 preset browser on the same IP, separate process
    q = mp.Queue()
    p = mp.Process(target=p5_worker, args=(q,)); p.start(); p.join(300)
    emit("step", step="P5_preset", **(q.get() if not q.empty() else dict(err="timeout")))
    upload()
    # P6 browsers per VM: 2, 3, 4 browsers in separate processes, each concurrency 2
    for nb in (2, 3, 4):
        q = mp.Queue()
        ps = [mp.Process(target=worker, args=(i, ppl, 2, STEP_S, q)) for i in range(nb)]
        for p in ps:
            p.start(); time.sleep(5)
        for p in ps:
            p.join(STEP_S + 240)
        res = [q.get() for _ in range(q.qsize())] if not q.empty() else []
        agg = dict(browsers=nb, cleared=sum(1 for r in res if r.get("cleared")), requests=sum(r.get("requests", 0) for r in res),
                   blocked=sum(r.get("blocked", 0) for r in res), per_min_total=round(sum(r.get("per_min", 0) for r in res), 1))
        emit("step", step=f"P6_{nb}browsers", **agg, **sysinfo())
        upload()
        if agg["blocked"] >= 2 or agg["cleared"] < nb:
            emit("stop", why=f"P6 stop at {nb} browsers"); upload(); return
    emit("done"); upload()


if __name__ == "__main__":
    mp.set_start_method("spawn")
    main()
