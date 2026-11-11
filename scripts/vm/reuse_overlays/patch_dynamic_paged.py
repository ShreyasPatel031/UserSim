#!/usr/bin/env python3
"""Cap offset fanout dynamically: probe page 0 first; if empty, stop (no 32 empty pages).

Keeps --tabs as the *max* parallel for non-empty lists; does not hardcode a lower tab count.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_person.py")
src = p.read_text()
if "DYNAMIC_PAGED_EMPTY_FIRST" in src:
    print("dynamic_paged already patched")
    sys.exit(0)

needle = '''async def paged(R, pages, op, conn_path, var="cursor", step=20, total=None, cap=None, extra=None):
    """Fetch offset pages in parallel across tabs. conn_path: keys into data to the connection."""
    extra = extra or {}; results = {}; done_at = [None]; nxt = [0]; t0 = time.time()
    limit = min(x for x in [total and (total + step), cap] if x) if (total or cap) else None
    def _ob():  # 1426Z in-tab per-person budget (R.over set by ph_batch)
        f = getattr(R, "over", None)
        if f and f(): R.budget_hit = True; return True
        return False
    async def worker(i):
        while not R.stop and not _ob():
            off = nxt[0]
            if (limit and off >= limit) or (done_at[0] is not None and off > done_at[0]): return
            if i >= R.tabs: await asyncio.sleep(2); continue
            nxt[0] += step
            d = await R.gql(pages[i % len(pages)], op, **{var: cur(off)}, **extra)
            c = d
            for k in conn_path: c = c[k] if c else None
            edges = (c or {}).get("edges") or []
            results[off] = edges
            if not edges or not (c.get("pageInfo") or {}).get("hasNextPage"):
                done_at[0] = off if done_at[0] is None else min(done_at[0], off)
            if len(results) % 25 == 0: R.log(op, "pages", len(results), "items", sum(len(v) for v in results.values()), f"{time.time()-t0:.0f}s tabs={R.tabs} rate={R.rate}")
    try: await asyncio.gather(*[worker(i) for i in range(len(pages))])
    except Blocked as e: R.log("paged stopped", op, e)'''

repl = '''async def paged(R, pages, op, conn_path, var="cursor", step=20, total=None, cap=None, extra=None):
    """Fetch offset pages in parallel across tabs. conn_path: keys into data to the connection."""
    # DYNAMIC_PAGED_EMPTY_FIRST: page 0 first; empty → no 32-way empty fanout. tabs stay the max for real lists.
    extra = extra or {}; results = {}; done_at = [None]; nxt = [0]; t0 = time.time()
    limit = min(x for x in [total and (total + step), cap] if x) if (total or cap) else None
    def _ob():  # 1426Z in-tab per-person budget (R.over set by ph_batch)
        f = getattr(R, "over", None)
        if f and f(): R.budget_hit = True; return True
        return False
    try:
        if not R.stop and not _ob():
            d0 = await R.gql(pages[0], op, **{var: cur(0)}, **extra)
            c0 = d0
            for k in conn_path: c0 = c0[k] if c0 else None
            e0 = (c0 or {}).get("edges") or []
            results[0] = e0
            nxt[0] = step
            if not e0 or not ((c0 or {}).get("pageInfo") or {}).get("hasNextPage"):
                done_at[0] = 0
                R.log(op, "pages", 1, "items", len(e0), f"{time.time()-t0:.0f}s tabs={R.tabs} rate={R.rate} empty_first=1")
    except Blocked as e:
        R.log("paged stopped", op, e)
    async def worker(i):
        while not R.stop and not _ob() and done_at[0] is None:
            off = nxt[0]
            if (limit and off >= limit) or (done_at[0] is not None and off > done_at[0]): return
            if i >= R.tabs: await asyncio.sleep(2); continue
            nxt[0] += step
            d = await R.gql(pages[i % len(pages)], op, **{var: cur(off)}, **extra)
            c = d
            for k in conn_path: c = c[k] if c else None
            edges = (c or {}).get("edges") or []
            results[off] = edges
            if not edges or not (c.get("pageInfo") or {}).get("hasNextPage"):
                done_at[0] = off if done_at[0] is None else min(done_at[0], off)
            if len(results) % 25 == 0: R.log(op, "pages", len(results), "items", sum(len(v) for v in results.values()), f"{time.time()-t0:.0f}s tabs={R.tabs} rate={R.rate}")
    if done_at[0] is None and not R.stop:
        try: await asyncio.gather(*[worker(i) for i in range(len(pages))])
        except Blocked as e: R.log("paged stopped", op, e)'''

if needle not in src:
    print("paged() pattern not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched dynamic_paged empty-first")
