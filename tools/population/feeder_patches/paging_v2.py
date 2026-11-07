"""Drop-in fix for ph_person.paged() (Data Feeder's reuse puller): followers/following paging (population agent, 2026-11-04).

Evidence (people_live/vm pulls + logs, Nov 4):
  1. Exhaustion was only detected in the parallel offset phase. When the offset pages repeat (dups ~= items, e.g. "items 40 of 42
     offset pages 4 seq pages 2 dups 40") and the server's own endCursor chain is what reaches the end, R.last_exhausted stayed
     False, so 12 short lists pulled after the 07:09Z marker code have no complete_not_visible and no reason.
  2. Big lists: offset pages read in parallel over a newest-first list that grows during a ~15 min pull return duplicates
     (alchemist: 100 pages, 418 dups -> 1,622 unique of a 2,000 cap; benln 224 dups -> 1,816). Offsets shift when new followers
     arrive; a cursor chain does not. The global rate limit (rate=25) makes the parallel tabs no faster than one chain.
  3. Nothing records why a list stopped (server end / cap / page limit / budget / error), so short lists can't be told apart
     from paging faults afterwards. (Upvotes already log a trail since 1059Z; lists didn't.)
  4. An offset-page PersonError (gql errors 4x) escaped paged() (only Blocked was caught), failing the whole person.

Fix: for follow lists (and any list > CHAIN_MIN items) page ONLY by the server's endCursor chain, sequentially, from the start;
for small other lists keep the offset phase but run the chain when short. Every page logs [n_edges, n_new, hasNextPage]; the
result carries paging = {method, pages, ended, dups, trail_tail}. R.last_exhausted is True iff some phase reached the server's
end (an empty page or hasNextPage=false) without stop/budget/error. A page of already-seen ids is not an end (as 1059Z).

Install: in ph_person.py,  `from paging_v2 import make_paged; paged = make_paged(paged, cur, Blocked)`  after paged() is defined,
and in ph_batch.py copy R.last_paging into res[key]["paging"] next to R.exh[key]. Same signature and return value as paged().
"""
import base64, time

CHAIN_OPS = {"ProfileFollowersQuery", "ProfileFollowingsQuery", "ProfileFollowingQuery"}
CHAIN_MIN = 200
MAX_PASSES = 8  # full re-page passes per attempt; reaching it ends as repage_max_passes (not whole), resumable


class _Stop(Exception):
    """internal: the offset re-page was stopped (R.stop) or hit the per-person budget"""


def make_paged(offset_paged, cur, Blocked, error_types=(Exception,)):
    async def paged(R, pages, op, conn_path, var="cursor", step=20, total=None, cap=None, extra=None):
        extra = extra or {}
        t0 = time.time()
        goal = min(x for x in [total, cap] if x) if (total or cap) else None
        over = lambda: bool(getattr(R, "over", None) and R.over())
        items, seen, trail = [], set(), []
        endc = None; off_resume = None
        dups = 0
        npg = 0
        ended = None

        def add(edges):
            nonlocal dups
            new = 0
            for e in edges or []:
                n = (e or {}).get("node") or {}
                if not n.get("id"):
                    continue
                if n["id"] in seen:
                    dups += 1
                    continue
                seen.add(n["id"]); items.append(n); new += 1
            return new

        def conn(d):
            c = d
            for k in conn_path:
                c = c[k] if isinstance(c, dict) else None
            return c or {}

        method = "endCursor_chain" if (op in CHAIN_OPS or (goal or 0) > CHAIN_MIN) else "offset+chain"
        # 2017Z nocap: deep pass resumes a list from the endCursor saved in deep_list (R.resume = {op: cursor})
        start = (getattr(R, "resume", None) or {}).pop(op, None)
        if start: method = "endCursor_chain"
        # 2049Z (babysitter fix 2): a saved cursor that is an offset (ours, or PH's own offset-encoded endCursor) can skip items
        # if some were deleted between passes. Resume one page earlier (overlap; merge dedupes by id) so up to `step`
        # deletions cost nothing; an opaque (non-offset) server endCursor is used exactly as saved.
        start_saved = start; off_back = None
        if start:
            try:
                _n = int(base64.b64decode(start + "=" * (-len(start) % 4)).decode())
                off_back = max(0, _n - step); start = cur(off_back) or None
            except Exception: pass
        if method == "offset+chain":
            try:
                off_items, _, off_npg = await offset_paged(R, pages, op, conn_path, var, step, total, cap, extra)
            except error_types as e:  # bug 4: an offset-phase error no longer fails the person; the chain below covers it
                R.log("offset phase error", op, str(e)[:200]); off_items, off_npg = [], 0
            npg += off_npg
            for n in off_items:
                if n.get("id") and n["id"] not in seen:
                    seen.add(n["id"]); items.append(n)
            if getattr(R, "last_exhausted", False):
                ended = "server_end_offset"
            elif getattr(R, "budget_hit", False) or R.stop:
                # 2140Z activity cursor: the offset phase stopped on budget/stop -> resume point = offset of the items already
                # held (rounded down to a page; offsets only overlap, never gap; merge dedupes by id). Was: no cursor -> restart.
                off_resume = cur((len(items) // step) * step); ended = "stopped" if R.stop else "budget"
        need_chain = method == "endCursor_chain" or (goal and len(items) < goal and ended is None)  # 2020Z nocap2: was 0.98*goal
        if need_chain and not R.stop:
            maxp = None  # 2020Z nocap2: page cap removed (was goal//step+10 or 500); server end / budget only
            endc, seq = (start or off_resume or cur(0)), 0  # start None after back-off to 0 -> cur(0)=None -> first page
            try:
                while True:
                    if R.stop: ended = "stopped"; break
                    if over(): R.budget_hit = True; ended = "budget"; break
                    if cap and len(items) >= cap: ended = "cap"; break
                    d = await R.gql(pages[0], op, **{var: endc}, **extra); npg += 1; seq += 1
                    c = conn(d); pi = c.get("pageInfo") or {}; edges = c.get("edges") or []
                    nnew = add(edges)
                    trail.append([len(edges), nnew, bool(pi.get("hasNextPage"))])
                    if not edges or not pi.get("hasNextPage") or not pi.get("endCursor"):
                        ended = "server_end"; break
                    endc = pi["endCursor"]
            except Blocked as e:
                ended = "blocked"; R.log("chain stopped", op, e)
            except error_types as e:
                ended = "error"; R.log("chain error", op, str(e)[:200])
        # paging_v3 / full18b (population agent, 2026-11-07; E5 review of full18). For follow lists the chain above was the only
        # phase, so "server_end_offset" was never recorded. On big lists PH's endCursor chain repeats some accounts and skips
        # others (the order is not stable between requests) and still ends at hasNextPage=false short of the header.
        # A follow list that ends that way short by more than 2 accounts and more than 2% (E5 classes 2 and 3) is re-paged
        # by offset from 0, sequentially (one tab, same rate limiter), merging by id, one full pass after another.
        #   closes (ended = "server_end_offset") only on full-depth passes: each served >= 98% of the union in rows, and either
        #     the union reaches 98% of the header, or ZERO_NEEDED zero-new full-depth passes in a row
        #     (3 for lists over 1,000 or a union under 98% of the header, else 2)
        #   repage_short_end: passes that add nothing but serve less than 98% of the union (PH's offset paging stops early);
        #     repage["ph_offset_depth"] records the depth PH served
        #   repage_stalled: 3 passes in a row each add fewer than max(2, 0.2% of the header)
        #   repage_max_passes: MAX_PASSES full passes without closing
        #   repage_offset_clamped / _offset_ignored / _offset_runaway: PH repeats a page or ignores the offset
        #   repage_stopped / _budget / _blocked / _error
        # Every repage_* end is NOT whole (no exhausted flag) and goes to the deep pass; the union and pass state are saved
        # through R.repage_save(op, state) when the caller provides it, and loaded with R.repage_load(op) so a retry resumes.
        repage = None
        if (op in CHAIN_OPS and ended == "server_end" and goal and (goal - len(items)) > 2 and len(items) < 0.98 * goal
                and not R.stop):
            st = None
            try: st = R.repage_load(op) if getattr(R, "repage_load", None) else None
            except Exception as e: R.log("repage state load failed", op, str(e)[:120])
            repage = {"passes": 0, "new": [], "served": [], "pages": 0, "start_items": len(items), "start_dups": dups,
                      "header": goal, "resumed_passes": 0}
            if st:
                for n in st.get("union") or []:
                    if n.get("id") and n["id"] not in seen: seen.add(n["id"]); items.append(n)
                for k in ("passes", "new", "served"): repage[k] = st.get(k, repage[k])
                repage["resumed_passes"] = repage["passes"]
            stall_min = max(2, 0.002 * goal)
            try:
                while True:
                    if repage["passes"] - repage["resumed_passes"] >= MAX_PASSES: raise _Stop("max_passes")
                    pass_new, served, off, first_ids, prev_ids = 0, 0, 0, None, None
                    while True:
                        if R.stop: raise _Stop("stopped")
                        if over(): R.budget_hit = True; raise _Stop("budget")
                        if off > 2 * goal + 10 * step: raise _Stop("offset_runaway")  # loop guard, ends as a failure
                        d = await R.gql(pages[0], op, **{var: cur(off)}, **extra); npg += 1; repage["pages"] += 1
                        c = conn(d); pi = c.get("pageInfo") or {}; edges = c.get("edges") or []
                        ids = [((e or {}).get("node") or {}).get("id") for e in edges]
                        if off == 0: first_ids = ids
                        elif ids and set(ids) <= set(first_ids or []): raise _Stop("offset_ignored")  # PH served page 0 again
                        if ids and prev_ids and set(ids) == set(prev_ids): raise _Stop("offset_clamped")  # PH served the same page twice in a row
                        prev_ids = ids; served += len(edges); pass_new += add(edges)
                        if not edges or not pi.get("hasNextPage"): break
                        off += step
                    repage["passes"] += 1; repage["new"].append(pass_new); repage["served"].append(served)
                    full_depth = served >= 0.98 * len(items)
                    need = 3 if (goal > 1000 or len(items) < 0.98 * goal) else 2
                    zero_full = 0
                    for nw, sv in zip(reversed(repage["new"]), reversed(repage["served"])):
                        if nw == 0 and sv >= 0.98 * len(items): zero_full += 1
                        else: break
                    if full_depth and (len(items) >= 0.98 * goal or zero_full >= need):
                        ended = "server_end_offset"; break
                    if pass_new == 0 and not full_depth and len(repage["new"]) >= 2 and repage["new"][-2] == 0:
                        repage["ph_offset_depth"] = served; raise _Stop("short_end")
                    last3 = repage["new"][-3:]
                    if len(last3) == 3 and all(x < stall_min for x in last3) and not (pass_new == 0 and full_depth):
                        raise _Stop("stalled")
            except _Stop as e:
                ended = "repage_" + str(e)
            except Blocked as e:
                ended = "repage_blocked"; R.log("repage stopped", op, e)
            except error_types as e:
                ended = "repage_error"; R.log("repage error", op, str(e)[:200])
            repage["union"] = len(items)
            try:
                if ended != "server_end_offset" and getattr(R, "repage_save", None):
                    R.repage_save(op, {"union": items, "passes": repage["passes"], "new": repage["new"], "served": repage["served"], "ended": ended})
                elif ended == "server_end_offset" and getattr(R, "repage_save", None):
                    R.repage_save(op, None)  # closed: drop any saved state
            except Exception as e: R.log("repage state save failed", op, str(e)[:120])
            R.log("repage", op, "items", len(items), "of", goal, "passes", repage["passes"], "new", repage["new"], "served", repage["served"], "ended", ended)
        if cap and len(items) > cap:
            items = items[:cap]
        if ended is None:
            ended = "complete" if goal and len(items) >= 0.98 * goal else "unknown"
        # 1640Z Data Feeder: upvotes end where the server ends (hasNextPage=false, ~200 signed-out); flag the signed-out cap
        if op == "ProfileUpvotesQuery" and ended in ("server_end", "server_end_offset") and total and len(items) < 0.98 * total:
            R.upv_capped = True
        R.last_exhausted = ended in ("server_end", "server_end_offset", "complete") and not R.stop and (npg >= 1 or bool(items))  # 2028Z: server-ended only after >=1 page fetched
        nxt = endc if (need_chain and ended in ("budget", "blocked", "error", "max_pages", "stopped")) else None
        if nxt is None and off_resume and ended not in ("server_end", "server_end_offset", "complete"):
            nxt = off_resume  # 2140Z: offset-phase budget stop keeps a resume cursor
        R.last_paging = {"method": method, "pages": npg, "ended": ended, "dups": dups, "repage": repage, "trail_tail": trail[-3:], "next_cursor": nxt, "resumed_from": start_saved, "resume_overlap_from_offset": off_back}
        R.log("paged_v2", op, "items", len(items), "of", goal, "pages", npg, "ended", ended, "dups", dups)
        return items, time.time() - t0, npg

    return paged
