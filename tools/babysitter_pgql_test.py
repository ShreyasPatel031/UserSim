#!/opt/venv/bin/python
"""Parallel GraphQL-only person pull TEST (Data Feeder, orchestrator 1955Z). VM-2 only, separate package (pgql.tgz);
does NOT replace reuse.tgz. ONE warm Camoufox page (same per-port profile/fingerprint as the normal driver); all person
lists via the site's own persisted GraphQL GETs fired with page.evaluate(fetch) at concurrency N (semaphore + rate cap).
HTML (in-page SSR fetch) only where GraphQL has no source: header counts if ProfileAboutPage lacks them, reviews.
Not pulled in this mode (HTML/navigation only): collection item lists, product pages (launch history/descriptions),
forum thread bodies/replies. Signed out, read-only. First 403/429/challenge -> stop everything, exit 3.
Output = DRAFT, separate prefix people_live/vm_pgql/ (normal person JSON untouched; claims released at the end)."""
import asyncio, json, os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ph_person as P
import ph_batch as PB
from ph_person import post_item, user_item, PH
from camoufox.async_api import AsyncCamoufox
ROOT = "gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/people_live"; B = ROOT + "/vm"; OUT = ROOT + "/vm_pgql"
VM = os.uname().nodename; now = PB.now; sh = PB.sh
class Block(Exception): pass
HINT = {}  # 2155Z: per-handle *Count fields seen in list responses
class G:
    stop = None; reqs = 0; s429 = 0; lat = []; sem = None; rate = 120; last = 0.0; lock = None; page = None; phase = None
async def gql(op, h, **vars):
    o = P.OPS[op]; v = dict(o["vars"]); v.update(vars); v["username"] = h
    for attempt in range(3):
        if G.stop: raise Block(G.stop)
        async with G.lock:
            gap = 60.0 / G.rate; t = time.time()
            if t - G.last < gap: await asyncio.sleep(gap - (t - G.last))
            G.last = time.time()
        async with G.sem:
            if G.stop: raise Block(G.stop)
            t0 = time.time(); st, txt = await G.page.evaluate(P.GQL_JS, [op, v, o["hash"]]); G.lat.append(time.time() - t0); G.reqs += 1; G.phase["reqs"] += 1
        if st in (403, 429) or "Just a moment" in txt[:2000] or "security verification" in txt[:5000]:
            if st == 429: G.s429 += 1
            G.stop = f"{op} HTTP {st} ({h}) at session_req {G.reqs}, phase {G.phase['name']}, {round((time.time()-G.phase['t0'])/60,1)} min into phase"; raise Block(G.stop)
        try: j = json.loads(txt)
        except Exception: G.stop = f"{op} non-JSON HTTP {st} ({h})"; raise Block(G.stop)
        if j.get("errors") and not j.get("data"): await asyncio.sleep(3); continue
        return j.get("data") or {}
    raise RuntimeError(f"{op} gql errors 3x")
HTML_PER_MIN = float(os.environ.get('PGQL_HTML_PER_MIN', 6)); _HL = [0.0]
async def ssr(path, h):
    if G.stop: raise Block(G.stop)
    # 2155Z babysitter: the c32 block (21:42Z) hit an SSR page load, not GraphQL. Space HTML loads to <= HTML_PER_MIN per VM.
    while True:
        w = _HL[0] + 60.0 / HTML_PER_MIN - time.time()
        if w <= 0: _HL[0] = time.time(); break
        await asyncio.sleep(min(w, 5))
        if G.stop: raise Block(G.stop)
    async with G.sem:
        st, c = await G.page.evaluate(PB.FETCH_JS, path); G.reqs += 1; G.phase["reqs"] += 1; G.phase["html"] += 1
    if st in (403, 429) or 'Just a moment' in c[:5000] or 'security verification' in c[:20000]:
        G.stop = f"SSR {path} HTTP {st}"; raise Block(G.stop)
    data = {}
    for o in PB.ssr_results(c):
        for ev in o.get("events") or []:
            if ev.get("type") == "next" and isinstance(ev.get("value"), dict):
                for k, vv in (ev["value"].get("data") or {}).items(): data.setdefault(k, []).append(vv)
    return data
async def chain(op, h, path, var="cursor", extra=None, cap=None, maxp=None):  # nocap2: no page cap (was 500)
    """server endCursor chain, sequential within one list; returns items, paging"""
    extra = extra or {}; seen = {}; c = None; pg = 0; ended = None; zn = 0
    while maxp is None or pg < maxp:
        d = await gql(op, h, **{var: c}, **extra); pg += 1; x = d
        if pg == 1 and isinstance(d.get("profile"), dict): HINT.setdefault(h, {}).update({k: v for k, v in d["profile"].items() if k.endswith("Count") and isinstance(v, int)})
        for k in path: x = x.get(k) if isinstance(x, dict) else None
        x = x or {}; ed = x.get("edges") or []; pi = x.get("pageInfo") or {}; new = 0
        for e in ed:
            n = (e or {}).get("node") or {}
            if n.get("id") and n["id"] not in seen: seen[n["id"]] = n; new += 1
        if not ed: ended = "empty_page"; break
        zn = zn + 1 if new == 0 else 0
        if zn >= 3: ended = "no_new_3pages"; break
        if cap and len(seen) >= cap: ended = "cap"; break
        if not pi.get("hasNextPage"): ended = "hasNextPage_false"; break
        c = pi.get("endCursor")
        if not c: ended = "no_endCursor"; break
    return list(seen.values()), {"pages": pg, "ended": ended or "max_pages"}
async def person(h):
    t0 = time.time(); r0 = G.reqs
    d = await gql("ProfileAboutPage", h, newProductsCursor=None); ab = (d.get("profile") or {})
    if not ab: raise RuntimeError("no profile in ProfileAboutPage")
    hdr_src = "graphql:ProfileAboutPage"
    hd = {"followers": ab.get("followersCount"), "following": ab.get("followingsCount"), "hunted": ab.get("submittedPostsCount"), "collections": ab.get("collectionsCount"),
          "reviews": ab.get("reviewsCount"), "upvotes": ab.get("votesCount"), "products": ab.get("productsCount"), "stacks": ab.get("stacksCount")}
    _need_ssr = any(hd[k] is None for k in ("followers", "following", "hunted", "collections"))
    if False:  # 2155Z: header SSR moved after the lists (counts usually come back in the list responses)
        dd = await ssr(f"/@{h}", h); hdr_src = "html:SSR /@h (counts not in ProfileAboutPage)"
        lay = next((x for x in dd.get("profile", []) if isinstance(x, dict) and "followersCount" in x), {})
        a2 = next((x for x in dd.get("profile", []) if isinstance(x, dict) and "newProducts" in x), {})
        for k, kk in (("followers", "followersCount"), ("following", "followingsCount"), ("hunted", "submittedPostsCount"), ("collections", "collectionsCount"), ("reviews", "reviewsCount"), ("products", "productsCount")):
            if hd[k] is None: hd[k] = lay.get(kk)
        if hd["upvotes"] is None: hd["upvotes"] = a2.get("votesCount")
        ab = {**a2, **ab} if a2 else ab
        if not lay: raise RuntimeError("no profile in SSR")
    mh = [e["node"] for e in (ab.get("newProducts") or {}).get("edges", [])]; pi = (ab.get("newProducts") or {}).get("pageInfo") or {}
    while pi.get("hasNextPage"):
        dd = await gql("ProfileAboutPage", h, newProductsCursor=pi["endCursor"]); np_ = dd["profile"]["newProducts"]; mh += [e["node"] for e in np_["edges"]]; pi = np_["pageInfo"]
    res = {"profile": f"{PH}/@{h}", "signed_in": False, "draft": True, "ph_user_id": ab.get("id"), "name": ab.get("name"), "header": hd, "header_source": hdr_src,
           "method": f"pgql_test: one warm Camoufox page, parallel persisted GraphQL (concurrency {G.phase['conc']}), port {os.environ.get('PROXY_PORT')}, signed out",
           "about": {"bio": ab.get("about"), "headline": ab.get("headline"), "joined": ab.get("createdAt"), "badges_count": ab.get("badgesCount"),
                     "maker_history": [{"name": m.get("name"), "url": f"{PH}/products/{m.get('slug')}", "product_id": m.get("id"), "tagline": m.get("tagline"), "date": m.get("createdAt")} for m in mh], "count": len(mh)}}
    L = [("upvotes", "ProfileUpvotesQuery", ["profile", "votedPosts"], "cursor", {"query": ""}, None, hd["upvotes"]),
         ("hunted", "ProfileHuntedPage", ["profile", "submittedPosts"], "cursor", {"query": ""}, None, hd["hunted"]),
         ("following", "ProfileFollowingQuery", ["profile", "following"], "cursor", {}, None, hd["following"]),
         ("forums", "ProfileForumsPage", ["profile", "forumActivity"], "cursor", {}, None, 1),
         ("collections", "ProfileCollectionsIndexPage", ["profile", "collections"], "cursor", {}, None, hd["collections"]),
         ("stacks", "ProfileStacksPage", ["profile", "stacks"], "cursor", {"query": ""}, None, hd.get("stacks") if hd.get("stacks") is not None else 1),
         ("followers", "ProfileFollowersQuery", ["profile", "followers"], "cursor", {}, None, hd["followers"]),
         ("activity", "ProfileActivityPage", ["profile", "activityEvents"], "eventsCursor", {"filter": "all", "activityLimit": 20}, None, 1)]  # 2028Z: small tabs first, followers + activity last
    async def one(k, op, path, var, extra, cap, total):
        if total == 0: return k, [], {"pages": 0, "ended": "header 0"}
        try: return (k,) + await chain(op, h, path, var, extra, cap)
        except Block: raise
        except Exception as e: return k, None, {"error": str(e)[:160]}
    out = await asyncio.gather(*[one(*x) for x in L])
    lists = {k: v for k, v, _ in out}; paging = {k: p for k, _, p in out}
    _hm = {"followers": "followersCount", "following": "followingsCount", "hunted": "submittedPostsCount", "collections": "collectionsCount", "reviews": "reviewsCount", "products": "productsCount", "stacks": "stacksCount", "upvotes": "votesCount"}
    _hi = HINT.pop(h, {})
    for k, kk in _hm.items():
        if hd.get(k) is None and _hi.get(kk) is not None: hd[k] = _hi[kk]
    if _need_ssr and all(hd[k] is not None for k in ("followers", "following", "hunted", "collections")): hdr_src = "graphql:list responses (*Count)"
    elif _need_ssr and (HTML_PER_MIN <= 0 or time.time() - _HL[0] < 60.0 / HTML_PER_MIN):  # 2203Z: HTML budget for this minute used: skip, deep pass fills the header later
        hdr_src = "missing: HTML page-load budget (deep pass fills it)"; res.setdefault("notes", []).append("header counts not read: HTML budget; queued via deep_list")
    elif _need_ssr:  # still missing: one rate-gated SSR page load
        dd = await ssr(f"/@{h}", h); hdr_src = "html:SSR /@h (counts not in GraphQL)"
        lay = next((x for x in dd.get("profile", []) if isinstance(x, dict) and "followersCount" in x), {})
        for k, kk in _hm.items():
            if hd.get(k) is None: hd[k] = lay.get(kk)
    res["header"] = hd; res["header_source"] = hdr_src
    revs = []
    if hd.get("reviews") and HTML_PER_MIN > 0 and time.time() - _HL[0] >= 60.0 / HTML_PER_MIN:  # 2203Z: reviews page only within the HTML budget; else deep pass
        dr = await ssr(f"/@{h}/reviews", h); revs = [e["node"] for x in dr.get("user", []) for e in (x.get("detailedReviews") or {}).get("edges", [])]
    res["upvotes"] = {"header": hd["upvotes"], "count": len(lists["upvotes"] or []), "items": [post_item(n) for n in lists["upvotes"] or []]}
    res["hunted"] = {"header": hd["hunted"], "count": len(lists["hunted"] or []), "items": [post_item(n) for n in lists["hunted"] or []]}
    res["following"] = {"header": hd["following"], "count": len(lists["following"] or []), "items": [user_item(n) for n in lists["following"] or []]}
    res["followers"] = {"header": hd["followers"], "count": len(lists["followers"] or []), "cap": None, "items": [user_item(n) for n in lists["followers"] or []]}
    res["collections"] = {"header": hd["collections"], "count": len(lists["collections"] or []), "items": [{"name": c.get("name"), "collection_id": c.get("id"), "url": P.purl(c.get("path")), "products_count": c.get("productsCount")} for c in lists["collections"] or []], "note": "index only; collection item lists need HTML (not pulled in pgql test)"}
    res["stacks"] = {"header": hd.get("stacks"), "count": len(lists["stacks"] or []), "items": [{"name": (s.get("product") or {}).get("name"), "url": f"{PH}/products/{(s.get('product') or {}).get('slug')}", "stacked": s.get("createdAt")} for s in lists["stacks"] or []]}
    res["activity"] = {"count": len(lists["activity"] or []), "items": lists["activity"] or []}
    res["forums"] = {"count": len(lists["forums"] or []), "items": [{"title": n.get("title"), "url": P.purl(n.get("path")), "date": n.get("createdAt"), "comments": n.get("commentsCount")} for n in lists["forums"] or []], "note": "list only; thread bodies/replies need navigation (not pulled)"}
    res["reviews"] = {"header": hd.get("reviews"), "count": len(revs), "items": revs}
    res["run"] = {"paging": paging, "requests": G.reqs - r0, "secs": round(time.time() - t0, 1), "finished_utc": now()}
    return res
def cov(res):
    c = {}
    for k in ("upvotes", "hunted", "following", "followers", "collections", "stacks"):
        hh = res["header"].get(k if k != "stacks" else "stacks"); got = res[k]["count"]; cap = res[k].get("cap")
        exp = min(hh, cap) if (hh is not None and cap) else hh
        c[k] = {"header": hh, "got": got, "pct": round(100 * min(got, exp) / exp, 1) if exp else None, "ended": res["run"]["paging"].get(k, {}).get("ended")}
        pgk = res["run"]["paging"].get(k, {}) or {}
        if exp and got < 0.98 * exp:  # 2028Z label rule: complete_not_visible only if PH's server ended the list after >=1 fetched page
            c[k]["status"] = "complete_not_visible" if (pgk.get("ended") in ("empty_page", "hasNextPage_false") and (pgk.get("pages") or 0) >= 1) else "FAIL"
    return c
async def main(a):
    try:
        import hashlib, base64
        _t = [f for f in ('pgql.tgz', '/opt/ph/reuse/reuse.tgz') if os.path.exists(f)]
        PB.Status().put(event='package_md5', file=_t[0] if _t else None, md5=base64.b64encode(hashlib.md5(open(_t[0], 'rb').read()).digest()).decode() if _t else None, mode='pgql')
    except Exception: pass
    os.makedirs("out_pgql", exist_ok=True); S = PB.Status(); G.lock = asyncio.Lock()
    have = set(x.rsplit('/', 1)[-1][:-5] for x in sh('gsutil', 'ls', f'{B}/*.json').stdout.split() if x.endswith('.json'))
    have |= set(x.rsplit('/', 1)[-1][:-5] for x in sh('gsutil', 'ls', f'{OUT}/*.json').stdout.split() if x.endswith('.json'))
    pr = [l.strip().lower() for l in sh('gsutil', 'cat', f'{B}/priority_feeder-phpeople-2.txt').stdout.splitlines() if l.strip()]
    def _disc():
        # Test 3 discovery candidates ranked by list overlap (go32 2030Z)
        r = sh('gsutil', 'cat', 'gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_population/discovery_yield_20261104/candidates*.jsonl')
        L = []
        for l in (r.stdout or '').splitlines():
            try: x = json.loads(l); L.append((-(x.get('overlap') or x.get('list_overlap') or 0), (x.get('handle') or '').lower()))
            except Exception: pass
        return [h for _, h in sorted(L) if h]
    def _build():
        dq = PB.deep_handles(0)  # 2040Z: deep mode alone owns deep_list; pgql never claims those people
        base = PB.load_handles(a)
        try: rows = [json.loads(l) for l in open('need_list.jsonl')]
        except Exception: rows = []
        disc = [x['handle'].lower() for x in sorted((x for x in rows if x.get('tier') == 'discovery'), key=lambda x: (-(x.get('lists') or 0), x.get('rank') or 1e9))]
        if os.environ.get('PGQL_ORDER') == 'pool':  # 2300Z: yield test 3.4% -> pool tiers first, discovery last (kept)
            _tr = {'likely': 0, 'active_rest': 1, 'other': 2}
            pool = [x['handle'].lower() for x in sorted((x for x in rows if x.get('handle') and x.get('tier') != 'discovery'), key=lambda x: (_tr.get(x.get('tier'), 3), x.get('rank') or 1e9))]
            return [h for h in dict.fromkeys(pool + pr + base + disc + _disc()) if h not in have and h not in dq]
        return [h for h in dict.fromkeys(disc + _disc() + pr + base) if h not in have and h not in dq]
    queue = _build()
    cmp_handles = [l.strip() for l in open("compare_list.txt") if l.strip()] if os.path.exists("compare_list.txt") else []
    S.put(event="pgql_test_start", pkg_md5=PB.PKG_MD5, pgql_md5=PB.pkg_md5("pgql.tgz"), token=a.token, port=int(os.environ.get('PROXY_PORT', 0)), phases=a.phases, note="parallel GraphQL test (orchestrator 1955Z); people JSON to vm_pgql/")
    R = PB.R2('_pgql', 'out_pgql/_session.log', [(1, 30)])
    nic0 = PB.nic(); b0 = nic0
    for _try in range(2):
        try: cm = AsyncCamoufox(from_options=PB.stable_options(R), persistent_context=True, headless="virtual"); ctx = await cm.__aenter__(); break
        except Exception as e:
            S.put(event="pgql_browser_open_failed", err=str(e)[-600:], attempt=_try + 1)
            if _try: return 1
            await asyncio.sleep(45)
    G.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    first = cmp_handles[0] if cmp_handles else queue[0]
    try: await R.goto(G.page, f"/@{first}", 150)
    except Exception as e: S.put(event="stopped_on_block", note=f"pgql: Cloudflare clear failed: {str(e)[:200]}", bytes=PB.nic() - b0); return 3
    S.put(event="browser_open", bytes=PB.nic() - b0, note="pgql test: one Cloudflare clear"); b0 = PB.nic()
    try: S.put(event="exit_ip", **(await asyncio.to_thread(PB.exit_info)))
    except Exception: pass
    summary = []; rc = 0; claimed = []
    async def flags():
        while True:
            await asyncio.sleep(60)
            for f in ('STOP_ALL', 'STOP.budget', f'STOP.{VM}', f'STOP.pgql.{VM}'):
                if await asyncio.to_thread(PB.gexists, f): G.halt = f
            nonlocal b0
            nb = PB.nic(); S.put(event="pgql_bw", bytes=nb - b0, phase=G.phase["name"] if G.phase else None); b0 = nb
            tot, _ = await asyncio.to_thread(PB.week_bytes)
            if tot + 50e6 > 29e9:  # $30/wk people budget, Shreyas 2021Z
                open('/tmp/sb', 'w').write(f'STOP budget {now()} week bytes {tot} (pgql test {VM})\n'); sh('gsutil', '-q', 'cp', '/tmp/sb', f'{B}/STOP.budget'); G.halt = "budget"
            sh('gsutil', '-q', '-m', 'rsync', 'out_pgql', f'{OUT}/_run_{a.token}')
    G.halt = None; ft = asyncio.create_task(flags())
    for pi_, (conc, mins) in enumerate(a.phases):
        G.sem = asyncio.Semaphore(conc); G.rate = 60 * conc; ph = {"name": f"c{conc}", "conc": conc, "reqs": 0, "html": 0, "people": 0, "errors": 0, "t0": time.time(), "nic0": PB.nic(), "cov": [], "cmp": []}
        G.phase = ph; G.lat = []; S.put(event="pgql_phase_start", phase=ph["name"], concurrency=conc, minutes=mins, rate_cap_per_min=G.rate)
        tend = time.time() + mins * 60; todo = (cmp_handles[pi_::len(a.phases)] if cmp_handles else [])
        async def worker():
            while time.time() < tend and not G.stop and not G.halt:
                if todo: h = todo.pop(0); is_cmp = True
                else:
                    if not queue:
                        async with G.lock:
                            if not queue: queue.extend(h for h in await asyncio.to_thread(_build) if h not in claimed)
                        if not queue: return
                    h = queue.pop(0); is_cmp = False
                    if h in PB.deep_handles() or not await asyncio.to_thread(PB.claim, h): continue
                    claimed.append(h)
                try: res = await person(h)
                except Block: return
                except Exception as e: ph["errors"] += 1; S.put(event="pgql_person_error", handle=h, err=str(e)[:200]); continue
                fn = f"out_pgql/{'cmp_' if is_cmp else ''}{h}.json"; json.dump(res, open(fn, "w"), ensure_ascii=False)
                if not is_cmp:  # 2210Z: save the lists as the person JSON (vm/<h>.json) so deep starts from them; deep fills only what pgql can't read
                    _tabs = ["collections", "reviews", "forum_threads"]  # + header (pull() always reads it) + product pages (filled for every maker/stack product with no saved fields)
                    _pg = (res.get("run") or {}).get("paging") or {}  # 2325Z: a tab that errored, or a follow list that ended short of its header, goes to deep too (deep re-pages it with paging_v2 and merges by id)
                    for _k in ("stacks", "hunted", "following", "followers", "activity", "forums", "upvotes"):
                        _t = res.get(_k) or {}; _h = _t.get("header")
                        if (_pg.get(_k) or {}).get("error") or (_k in ("following", "followers") and _h and (_t.get("count") or 0) < 0.98 * _h):
                            if _k not in _tabs: _tabs.append(_k)
                    res["deep_pending"] = _tabs; res.setdefault("notes", []).append("2210Z pgql lists saved as vm/<h>.json; deep fills header, reviews, collection items, product pages, forum threads")
                    json.dump(res, open(fn, "w"), ensure_ascii=False)
                    if not await asyncio.to_thread(PB.gexists, f"{h}.json"): await asyncio.to_thread(sh, 'gsutil', '-q', 'cp', fn, f'{B}/{h}.json')
                    _dl = f"/tmp/deep_pgql_{h}.json"; open(_dl, "w").write(json.dumps({"handle": h, "reason": "pgql_lists_only", "tabs": _tabs, "cursors": {}, "counts": {}, "vm": VM, "utc": now()}) + "\n")
                    await asyncio.to_thread(sh, 'gsutil', '-q', 'cp', _dl, f'{B}/deep_list/{h}.{VM}.pgql.json')
                c = cov(res); ph["people"] += 1; row = {"handle": h, "cmp": is_cmp, "reqs": res["run"]["requests"], "secs": res["run"]["secs"], "cov": c, "header_source": res["header_source"]}
                ph["cov"].append(row)
                if is_cmp:
                    old = json.loads(sh('gsutil', 'cat', f'{B}/{h}.json').stdout or "{}"); d = {}
                    for k in ("upvotes", "hunted", "following", "followers", "collections", "stacks", "activity", "forums", "reviews"):
                        d[k] = {"html_pull": (old.get(k) or {}).get("count"), "pgql": res[k]["count"]}
                    d["maker_history"] = {"html_pull": (old.get("about") or {}).get("count"), "pgql": res["about"]["count"]}
                    d["fields_only_in_html_pull"] = sorted(set(k for it in (old.get("upvotes") or {}).get("items", [])[:50] for k, v in it.items() if v not in (None, "", [])) - set(k for it in res["upvotes"]["items"][:50] for k, v in it.items() if v not in (None, "", [])))
                    ph["cmp"].append({"handle": h, **d})
                if not is_cmp:
                    S.put(event="pgql_person", handle=h, phase=ph["name"], requests=row["reqs"], secs=row["secs"], coverage=c)
        ws = [asyncio.create_task(worker()) for _ in range(conc * 2)]
        await asyncio.gather(*ws, return_exceptions=True)
        el = (time.time() - ph["t0"]) / 60; by = PB.nic() - ph["nic0"]
        lat = sorted(G.lat); s = {"phase": ph["name"], "concurrency": conc, "minutes": round(el, 1), "people": ph["people"], "people_per_min": round(ph["people"] / el, 2) if el else None,
             "requests": ph["reqs"], "req_per_min": round(ph["reqs"] / el, 1) if el else None, "html_fetches": ph["html"], "mb_total": round(by / 1e6, 2), "mb_per_person": round(by / 1e6 / ph["people"], 3) if ph["people"] else None,
             "lat_p50_s": round(lat[len(lat)//2], 2) if lat else None, "lat_p95_s": round(lat[int(len(lat)*.95)], 2) if lat else None, "errors": ph["errors"], "block": G.stop, "s429": G.s429, "halt": G.halt,
             "session_minutes_at_end": round((time.time() - (summary[0]["_t0"] if summary else ph["t0"])) / 60, 1), "_t0": summary[0]["_t0"] if summary else ph["t0"]}
        rows = [r for r in ph["cov"] if not r["cmp"]]
        for k in ("upvotes", "hunted", "following", "followers", "collections", "stacks"):
            vals = [r["cov"][k] for r in rows if r["cov"][k]["header"]]
            s[f"cov_{k}"] = {"people_with_header": len(vals), "items_got": sum(min(v["got"], v["header"]) for v in vals), "items_header": sum(v["header"] for v in vals), "people_100pct": sum(1 for v in vals if (v["pct"] or 0) >= 98)}
        s["upvotes_short"] = [{"handle": r["handle"], "header": r["cov"]["upvotes"]["header"], "got": r["cov"]["upvotes"]["got"], "ended": r["cov"]["upvotes"]["ended"]} for r in rows if r["cov"]["upvotes"]["header"] and r["cov"]["upvotes"]["got"] < 0.98 * r["cov"]["upvotes"]["header"]][:30]
        s["header_sources"] = {x: sum(1 for r in ph["cov"] if r["header_source"] == x) for x in set(r["header_source"] for r in ph["cov"])}
        s["compare_vs_html_pull"] = ph["cmp"]
        summary.append(s); json.dump(summary, open("out_pgql/summary.json", "w"), indent=1, default=str)
        S.put(event="pgql_phase_end", **{k: v for k, v in s.items() if not k.startswith(("_", "compare", "upvotes_short", "cov_"))})
        prev = summary[-2] if len(summary) > 1 else None
        if prev and prev.get("lat_p50_s") and s.get("lat_p50_s") and s["lat_p50_s"] > 2 * prev["lat_p50_s"]:
            s["slowdown"] = f"median latency {s['lat_p50_s']}s > 2x previous step {prev['lat_p50_s']}s"; S.put(event="pgql_slowdown_stop", phase=ph["name"], note=s["slowdown"], session_requests=G.reqs); json.dump(summary, open("out_pgql/summary.json", "w"), indent=1, default=str); break
        if G.stop: rc = 3; S.put(event="stopped_on_block", note=f"pgql test: stop at first block: {G.stop}", phase=ph["name"], session_requests=G.reqs, session_minutes=s["session_minutes_at_end"]); break
        if G.halt: break
    ft.cancel()
    nb = PB.nic(); S.put(event="pgql_bw", bytes=nb - b0, phase="end")
    try: await cm.__aexit__(None, None, None)
    except Exception: pass
    for h in claimed: sh('gsutil', '-q', 'rm', f'{B}/claims/{h}')
    sh('gsutil', '-q', '-m', 'rsync', 'out_pgql', f'{OUT}/_run_{a.token}'); sh('gsutil', '-q', 'cp', 'out_pgql/summary.json', f'{OUT}/_run_{a.token}/summary.json')
    S.put(event="pgql_test_done", rc=rc, session_nic_bytes=nb - nic0, claims_released=len(claimed))
    return rc
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument('--token', default=time.strftime('%Y%m%dT%H%MZ', time.gmtime())); ap.add_argument('--phases', default=os.environ.get('PGQL_PHASES','32:600'))
    a = ap.parse_args()
    import re as _re; _m = _re.search(r'_c(\d+)$', a.token or '')  # 2048Z: concurrency from GO token suffix, e.g. pgql:x_c64 -> 64 for 600 min
    if _m and '--phases' not in sys.argv: a.phases = f'{int(_m.group(1))}:600'
    a.phases = [tuple(int(x) for x in p.split(':')) for p in a.phases.split(',')]
    sys.exit(asyncio.run(main(a)))
