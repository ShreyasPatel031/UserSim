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
import time

CHAIN_OPS = {"ProfileFollowersQuery", "ProfileFollowingsQuery", "ProfileFollowingQuery"}
CHAIN_MIN = 200


def make_paged(offset_paged, cur, Blocked, error_types=(Exception,)):
    async def paged(R, pages, op, conn_path, var="cursor", step=20, total=None, cap=None, extra=None):
        extra = extra or {}
        t0 = time.time()
        goal = min(x for x in [total, cap] if x) if (total or cap) else None
        over = lambda: bool(getattr(R, "over", None) and R.over())
        items, seen, trail = [], set(), []
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
        need_chain = method == "endCursor_chain" or (goal and len(items) < 0.98 * goal and ended is None)
        if need_chain and not R.stop:
            maxp = (goal // step + 10) if goal else 500
            endc, seq = cur(0), 0
            try:
                while True:
                    if R.stop: ended = "stopped"; break
                    if over(): R.budget_hit = True; ended = "budget"; break
                    if seq >= maxp: ended = "max_pages"; break
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
        if cap and len(items) > cap:
            items = items[:cap]
        if ended is None:
            ended = "complete" if goal and len(items) >= 0.98 * goal else "unknown"
        R.last_exhausted = ended in ("server_end", "server_end_offset", "complete") and not R.stop
        R.last_paging = {"method": method, "pages": npg, "ended": ended, "dups": dups, "trail_tail": trail[-3:]}
        R.log("paged_v2", op, "items", len(items), "of", goal, "pages", npg, "ended", ended, "dups", dups)
        return items, time.time() - t0, npg

    return paged
