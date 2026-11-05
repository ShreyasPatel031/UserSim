#!/opt/venv/bin/python
"""Parallel deep pass (babysitter, 2026-11-04 2130Z; orchestrator 2125Z: deep must go parallel).
Same work as `ph_batch.py --mode deep` (pull_deep: resume saved cursors, merge by id, no caps, server end / budget only),
but K people at once in ONE warm Camoufox: each worker gets its own pages (own p0 + own GraphQL response capture, so
thread/stack captures never mix between people) and its own R2 runner (own rate gate). PRODCACHE (product pages) is shared.
Nothing in ph_batch.py changes; this file only schedules pull_deep() concurrently.
Env: PDEEP_K workers (default 4 on <6 GB RAM, else 8), PDEEP_TABS pages per worker (default 2).
Stop rules as deep mode: first block -> all workers stop, exit 3; STOP_ALL / STOP.budget / STOP.<vm> / no GO -> stop before
the next person; weekly byte cap -> STOP.budget, exit 4; 3 consecutive non-block errors on one worker -> exit 6."""
import asyncio, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ph_batch as PB
from ph_person import Blocked

def _mem_gb():
    try: return int(next(l for l in open('/proc/meminfo') if l.startswith('MemTotal')).split()[1]) / 1e6
    except Exception: return 4.0
_ACTIVE = [0]
def _over_budget(R):
    """2140Z audit fix 1: nic() is the whole VM's counter, so with K workers each person would be charged everyone's bytes.
    Charge each person an equal share of the VM's traffic since that person started (per-worker stop-gap)."""
    return False  # 0030Z Shreyas: no per-person budget; only PH limits and the 195e9 weekly stop
PB.over_budget = _over_budget  # module-global lookup: pull()/paging use this from here on
_WB = {"t": 0.0, "v": (0, {})}
def _week_bytes_cached():
    """2352Z: week_bytes() reads every VM's status file (tens of seconds); each worker called it before every person, so
    workers sat idle. Cache it 2 min; the fleet uses ~1 GB/h, so the 29 GB stop can overshoot by ~35 MB at most."""
    if time.time() - _WB["t"] > 120: _WB["v"] = PB.week_bytes(); _WB["t"] = time.time()
    return _WB["v"]
FULL = os.environ.get('PDEEP_MODE') == 'full'  # 0205Z Shreyas: pull everything about a person in one go, or don't pull
K = int(os.environ.get('PDEEP_K', 4 if _mem_gb() < 6 else 16))  # 0205Z (population audit): RAM-based default; PDEEP_K per VM overrides
TABS = int(os.environ.get('PDEEP_TABS', 2))  # pages per worker
B, VM = PB.B, PB.VM


async def worker_pages(ctx, R, first_handle, n):
    """n new pages at the PH origin + a response capture on the first one (as open_browser does for pages[0])."""
    pages = []
    for _ in range(n):
        pg = await ctx.new_page(); await pg.goto("https://www.producthunt.com/robots.txt", timeout=60000); pages.append(pg)  # 0200Z: same-origin warm-up that is not a profile page (32 profile loads in a row got CF blocks)
    cap = []
    async def onr(r):
        if '/frontend/graphql' in r.url and (r.request.method == 'POST' or re.search('Comment|Thread|Discussion|Stack', r.url)):
            try: cap.append(await r.json())
            except Exception: pass
    pages[0].on('response', onr)
    return pages, cap


async def main(a):
    S = PB.Status(); token = a.token
    PB.BUDGET_SECS = PB.DEEP_SECS; PB.BUDGET_BYTES = PB.DEEP_BYTES  # deep budget, as in deep mode
    a.person_timeout = None  # 0030Z: no per-person timeout
    ramp = [tuple(int(x) for x in t.split(":")) for t in a.ramp.split(",")]
    S.put(event="start", method="pfull_v1" if FULL else "pdeep_v1", mode="pfull" if FULL else "pdeep", token=token, workers=K, tabs_per_worker=TABS,
          port=int(os.environ.get('PROXY_PORT', 0)), pkg_md5=PB.PKG_MD5)
    claims = set(PB.sh('gsutil', 'ls', f'{B}/claims/deep_*').stdout.split())
    queue = [h for h in sorted(PB.deep_handles(0)) if f'{B}/claims/deep_{h}' not in claims]
    if FULL:  # new people only, pool order (likely > active_rest > other > discovery), skip anyone with a saved pull or a deep entry
        have = set(x.rsplit('/', 1)[-1][:-5].lower() for x in PB.sh('gsutil', 'ls', f'{B}/*.json').stdout.split() if x.endswith('.json'))
        dq = set(PB.deep_handles(0)); rows = []
        PB.sh('gsutil', '-q', 'cp', 'gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live/need_list.jsonl', 'need_list.jsonl')
        for l in open('need_list.jsonl'):
            try: rows.append(json.loads(l))
            except Exception: pass
        _tr = {'likely': 0, 'active_rest': 1, 'other': 2}
        rows.sort(key=lambda x: (_tr.get(x.get('tier'), 3), x.get('rank') or 1e9))
        queue = [h for h in dict.fromkeys((x.get('handle') or '').lower() for x in rows) if h and h not in have and h not in dq]
    tl = PB.sh('gsutil', 'cat', f'{B}/pdeep_list.{VM}.txt')  # optional test list: only these deep_list people, in this order
    if tl.returncode == 0 and tl.stdout.strip():
        only = [l.strip().lower() for l in tl.stdout.splitlines() if l.strip()]; queue = [h for h in only if h in set(queue)]
        S.put(event="pdeep_test_list", n=len(queue))
    if not queue: S.put(event="done", people=0, note="deep_list empty"); return 0
    lr = PB.R2('_session', f'out/_session_{VM}.log', ramp); os.makedirs('out', exist_ok=True)
    b0 = PB.nic(); t_start = time.time()
    try: cm, pages0, cap0 = await PB.open_browser(lr, TABS, queue[0])
    except Exception as e:
        S.put(event="browser_open_failed", err=str(e)[:300], bytes=PB.nic() - b0)
        S.put(event="stopped_on_block", note="pdeep: browser open/Cloudflare clear failed; no retry"); return 3
    S.put(event="browser_open", bytes=PB.nic() - b0, note="pdeep: one Cloudflare clear for all workers")
    try: S.put(event="exit_ip", **(await asyncio.to_thread(PB.exit_info)))
    except Exception: pass
    ctx = pages0[0].context
    slots = [(pages0, cap0)]
    for _ in range(K - 1):
        slots.append(await worker_pages(ctx, lr, queue[0], TABS))
    st = {"stop": None, "done": 0, "rc": 0, "qi": 0}

    def stopflag():
        for f in ('STOP_ALL', 'STOP.budget', f'STOP.{VM}'):
            if PB.gexists(f): return f
        if not PB.gexists(f'GO.{VM}'): return f'no GO.{VM}'
        return None

    async def next_handle():
        while st["qi"] < len(queue) and not st["stop"]:
            h = queue[st["qi"]]; st["qi"] += 1
            if await asyncio.to_thread(PB.claim, h if FULL else f'deep_{h}'): return h
        return None

    async def work(wi, pages, cap):
        consec = 0
        while not st["stop"]:
            f = await asyncio.to_thread(stopflag)
            if f: st["stop"] = f; S.put(event="stop_flag", flag=f, worker=wi); break
            tot, _ = await asyncio.to_thread(_week_bytes_cached)
            if tot + 25e6 > a.cap:
                open('/tmp/sb', 'w').write(f'STOP budget {PB.now()} week bytes {tot} >= cap {a.cap} (set by {VM} pdeep)\n')
                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', '/tmp/sb', f'{B}/STOP.budget')
                st["stop"] = "budget"; st["rc"] = 4; S.put(event="budget_stop", week_bytes=tot); break
            h = await next_handle()
            if not h: break
            R = PB.R2(h, f'out/{h}.log', ramp); R.t0 = time.time(); R.b0 = PB.nic(); R.over = (lambda R=R: PB.over_budget(R)); R.partial = []
            t0 = time.time(); res = err = None; _ACTIVE[0] += 1
            try: res = await PB.no_progress_watch((PB.pull(R, pages, h, a, cap) if FULL else PB.pull_deep(R, pages, h, a, cap)), R)
            except Blocked as e: err = ("block", str(e))
            except PB.PersonError as e: err = ("person_error", str(e))
            except asyncio.TimeoutError: err = ("timeout", "")
            except Exception as e: err = ("error", f"{type(e).__name__}: {e}"[:300])
            secs = int(time.time() - t0); _ACTIVE[0] -= 1
            if res:
                PB._CUR_R[0] = R; cv = PB.coverage(res)  # sync: no other worker runs between these two statements
                json.dump(res, open(f'out/{h}.json', 'w'), indent=1, ensure_ascii=False)
                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.json', f'{B}/{h}.json')
                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')
                if not FULL: await asyncio.to_thread(PB.deep_done, h, res, R)
                elif res.get('truncated_budget') or getattr(R, 'trunc', None): await asyncio.to_thread(PB.deep_add, h, 'full_partial', list(getattr(R, 'trunc', []) or res.get('truncated_budget') or []), getattr(R, 'cursors', {}), {})
                S.put(handle=h, rc=0, method="pfull_v1" if FULL else "pdeep_v1", worker=wi, secs=secs, gql=res["run"]["gql_calls"], html=res["run"]["html_fetches"],
                      navs=res["run"]["thread_navs"], header_pct=cv["header_pct"], header_items=cv["header_items"], coverage=cv["tabs"],
                      fill=cv["field_fill_pct"], port=int(os.environ.get('PROXY_PORT', 0)))
                st["done"] += 1; consec = 0
            else:
                await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'cp', f'out/{h}.log', f'{B}/logs/{h}.log')
                if 'no profile' not in (err[1] or ''):  # audit fix 4: release the claim on every error except a deleted account, so the entry is retried
                    await asyncio.to_thread(PB.sh, 'gsutil', '-q', 'rm', f'{B}/claims/{h}' if FULL else f'{B}/claims/deep_{h}')
                S.put(handle=h, rc=3 if err[0] == "block" else 1, method="pdeep_v1", worker=wi, secs=secs, error=err[0], detail=err[1])
                if err[0] == "block":
                    st["stop"] = "block"; st["rc"] = 3; S.put(event="stopped_on_block", handle=h, note="pdeep: first block stops every worker"); break
                if 'no profile' in (err[1] or ''): continue
                consec += 1
                if consec >= 3: st["stop"] = "errors"; st["rc"] = 6; S.put(event="stopped_on_errors", worker=wi, note="3 consecutive non-block errors"); break

    await asyncio.gather(*[work(i, p, c) for i, (p, c) in enumerate(slots)])
    try: await cm.__aexit__(None, None, None)
    except Exception: pass
    S.put(event="done", people=st["done"], mode="pdeep", workers=K, stop=st["stop"], session_nic_bytes=PB.nic() - b0, session_secs=int(time.time() - t_start))
    return st["rc"]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--token', default=''); ap.add_argument('--ramp', default=os.environ.get('PDEEP_RAMP', '4:60'))  # per-worker rate gate; the IP held 8,700 req/min in the 2001Z lab
    ap.add_argument('--threads', type=int, default=0); ap.add_argument('--followers-cap', type=int, default=0)
    ap.add_argument('--tabs', type=int, default=TABS); ap.add_argument('--person-timeout', type=int, default=1500); ap.add_argument('--cap', type=float, default=PB.CAP)
    a = ap.parse_args(); a.cap = min(a.cap, PB.CAP); a.mode = 'deep'
    sys.exit(asyncio.run(main(a)))
