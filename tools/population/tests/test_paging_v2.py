"""Simulated Product Hunt list server for paging_v2: newest-first list that grows while being read, hidden accounts counted in
the header but never listed, and an offset cursor the server stops honouring past a depth."""
import asyncio, base64, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "feeder_patches"))
import paging_v2

PAGE = 20


def cur(i):
    return None if not i else base64.b64encode(str(i).encode()).decode().rstrip("=")


def uncur(c):
    if not c:
        return 0
    return int(base64.b64decode(c + "=" * (-len(c) % 4)).decode())


class Blocked(Exception):
    pass


class FakeServer:
    """visible list, newest first; `grow` new followers arrive before every request; offsets past `offset_limit` are ignored
    (served as page 0, the failure seen in the logs: dups ~= items)."""

    def __init__(self, n_visible, grow=0, offset_limit=10**9):
        self.items = [{"id": f"u{i}"} for i in range(n_visible)]
        self.grow, self.next_id, self.offset_limit = grow, n_visible, offset_limit
        self.cursor_pos = {}

    def query(self, cursor):
        for _ in range(self.grow):
            self.items.insert(0, {"id": f"u{self.next_id}"}); self.next_id += 1
        if cursor and cursor.startswith("K"):  # opaque endCursor: anchored to an item id, stable under inserts
            start = self.items.index(self.cursor_pos[cursor]) + 1
        else:
            start = uncur(cursor)
            if start > self.offset_limit:
                start = 0
        page = self.items[start:start + PAGE]
        has_next = start + PAGE < len(self.items)
        endc = None
        if page:
            endc = "K" + page[-1]["id"]; self.cursor_pos[endc] = page[-1]
        return {"profile": {"followers": {"edges": [{"node": n} for n in page], "pageInfo": {"hasNextPage": has_next, "endCursor": endc}}}}


class R:
    def __init__(self, server):
        self.s, self.stop, self.logs = server, False, []

    async def gql(self, page, op, cursor=None, **kw):
        return self.s.query(cursor)

    def log(self, *a):
        self.logs.append(a)


async def offset_paged(R_, pages, op, conn_path, var, step, total, cap, extra):
    """Simplified offset phase like ph_person.paged: offsets 0, 20, ... up to total+step; exhaustion only from offsets."""
    items, seen, R_.last_exhausted = [], set(), False
    lim = min(x for x in [total and total + step, cap] if x)
    for off in range(0, lim, step):
        d = await R_.gql(None, op, cursor=cur(off))
        c = d["profile"]["followers"]
        for e in c["edges"]:
            if e["node"]["id"] not in seen:
                seen.add(e["node"]["id"]); items.append(e["node"])
        if not c["edges"] or not c["pageInfo"]["hasNextPage"]:
            R_.last_exhausted = True; break
    return items, 0, 0


def run(server, op, total, cap=None):
    paged = paging_v2.make_paged(offset_paged, cur, Blocked)
    r = R(server)
    items, _, npg = asyncio.run(paged(r, [None], op, ["profile", "followers"], "cursor", PAGE, total, cap, {}))
    return r, items


def test_hidden_accounts_marked_exhausted():
    r, items = run(FakeServer(10), "ProfileFollowersQuery", total=17)  # header 17, server lists 10
    # full18b: short by > 2 and > 2% -> re-paged; closes at what PH lists
    assert len(items) == 10 and r.last_exhausted and r.last_paging["ended"] == "server_end_offset"


def test_growing_big_list_no_dups_reaches_cap():
    s = FakeServer(4000, grow=3)
    r, items = run(s, "ProfileFollowersQuery", total=4221, cap=2000)
    assert len(items) == 2000 and len({n["id"] for n in items}) == 2000
    assert r.last_paging["ended"] == "cap" and r.last_paging["dups"] == 0


def test_offset_ignored_chain_recovers_and_marks_end():
    # small non-follow list: offset phase repeats page 0 past offset 20; the chain completes it and marks the end
    r, items = run(FakeServer(42, offset_limit=20), "ProfileCollectionsIndexPage", total=45)
    assert len(items) == 42 and r.last_exhausted and r.last_paging["method"] == "offset+chain"


def test_budget_is_not_exhaustion():
    s = FakeServer(500)
    paged = paging_v2.make_paged(offset_paged, cur, Blocked)
    r = R(s); calls = {"n": 0}

    def over():
        calls["n"] += 1
        return calls["n"] > 3
    r.over = over
    items, _, _ = asyncio.run(paged(r, [None], "ProfileFollowersQuery", ["profile", "followers"], "cursor", PAGE, 500, None, {}))
    assert r.last_paging["ended"] == "budget" and not r.last_exhausted and len(items) == 60


# ---- paging_v3: offset re-page after a repeated follow-list chain (E5 audit, Nov 7) ----
import random


class UnstableServer(FakeServer):
    """PH's follow lists sort on a key with ties, so the order changes between requests: each request sees the base list with
    neighbours swapped inside blocks of `block`. A chain over it repeats some accounts and never serves others, and still
    ends at hasNextPage=false (the E5 class-2 shape: pages x 20 ~ header, unique ids short)."""

    def __init__(self, n_visible, block=40, seed=7, **kw):
        super().__init__(n_visible, **kw)
        self.block, self.rng = block, random.Random(seed)

    def query(self, cursor):
        base = list(self.items)
        for b in range(0, len(base), self.block):
            blk = base[b:b + self.block]; self.rng.shuffle(blk); base[b:b + self.block] = blk
        if cursor and cursor.startswith("~"):  # the server's own endCursor: always honoured
            start = int(cursor[1:])
        else:  # a bare offset cursor (ours): ignored past offset_limit, served as page 0
            start = uncur(cursor)
            if start > self.offset_limit:
                start = 0
        page = base[start:start + PAGE]
        has_next = start + PAGE < len(base)
        endc = ("~" + str(start + PAGE)) if page else None
        return {"profile": {"followers": {"edges": [{"node": n} for n in page], "pageInfo": {"hasNextPage": has_next, "endCursor": endc}}}}



class RecR(R):
    """runner with the repage state hooks (in-memory) and a request counter"""
    store = {}

    def __init__(self, server, key="p"):
        super().__init__(server); self.key, self.n = key, 0

    async def gql(self, page, op, cursor=None, **kw):
        self.n += 1
        return self.s.query(cursor)

    def repage_load(self, op): return RecR.store.get((self.key, op))
    def repage_save(self, op, st):
        if st is None: RecR.store.pop((self.key, op), None)
        else: RecR.store[(self.key, op)] = st


def runr(server, total, key="p", over=None):
    paged = paging_v2.make_paged(offset_paged, cur, Blocked)
    r = RecR(server, key)
    if over: r.over = over
    items, _, _ = asyncio.run(paged(r, [None], "ProfileFollowersQuery", ["profile", "followers"], "cursor", PAGE, total, None, {}))
    return r, items


class DepthServer(UnstableServer):
    """PH's own chain (the ~ cursors) is unstable; bare offset cursors past `depth` return an empty page (PH stops early)."""

    def __init__(self, n_visible, depth, **kw):
        super().__init__(n_visible, **kw); self.depth = depth

    def query(self, cursor):
        if not (cursor and cursor.startswith("~")) and uncur(cursor) >= self.depth:
            return {"profile": {"followers": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        return super().query(cursor)


class ClampServer(UnstableServer):
    """bare offset cursors past `at` keep returning one identical page (hasNextPage true)"""

    def __init__(self, n_visible, at, **kw):
        super().__init__(n_visible, **kw); self.at, self.clamped = at, None

    def query(self, cursor):
        if not (cursor and cursor.startswith("~")) and uncur(cursor) > self.at:
            if self.clamped is None: self.clamped = super().query(cur(self.at))
            return self.clamped
        return super().query(cursor)


def test_repeated_chain_is_repaged_to_server_end_offset():
    r, items = runr(UnstableServer(1079), 1079, key="a")
    lp = r.last_paging; rp = lp["repage"]
    assert rp["start_items"] < 0.98 * 1079 and rp["start_dups"] > 0  # the chain alone was short
    assert lp["ended"] == "server_end_offset" and len(items) >= 0.98 * 1079 and len({n["id"] for n in items}) == len(items)
    assert rp["served"][-1] >= 0.98 * rp["union"] and r.last_exhausted


def test_hidden_accounts_need_three_full_depth_zero_passes():
    # E5: the 899/900 case. header 1,079, PH lists 900 signed out; a list over 1,000 needs 3 zero-new full-depth passes
    for seed in range(1, 21):
        r, items = runr(UnstableServer(900, seed=seed), 1079, key=f"h{seed}")
        lp = r.last_paging; rp = lp["repage"]
        assert lp["ended"] in ("server_end_offset", "repage_max_passes", "repage_stalled")
        if lp["ended"] == "server_end_offset":
            assert rp["new"][-3:] == [0, 0, 0] and all(sv >= 0.98 * rp["union"] for sv in rp["served"][-3:])
            MISSES.append(900 - len(items))
        else:
            assert not r.last_exhausted
    print("hidden 900/1079, 20 seeds: closed", len(MISSES), "misses per closed run", MISSES)
    assert sum(MISSES) <= 2 and all(m <= 1 for m in MISSES)  # residual risk of the zero-pass closure, reported to E5


MISSES = []


def test_short_offset_end_is_not_whole():
    # E5 point 1: PH's offset paging stops at 75% of the list; two zero-new passes must NOT be labelled server_end_offset
    r, items = runr(DepthServer(1079, depth=800), 1079, key="d")
    lp = r.last_paging
    assert lp["ended"] in ("repage_short_end", "repage_stalled") and not r.last_exhausted
    if lp["ended"] == "repage_short_end":
        assert lp["repage"]["ph_offset_depth"] <= 800


def test_class3_short_without_repeats_is_repaged():
    # E5 point 2: a chain that ends short with no repeat seen (hidden accounts) is still re-paged, and closes
    r, items = runr(FakeServer(860), 1000, key="c3")
    lp = r.last_paging
    assert lp["repage"] is not None and lp["ended"] == "server_end_offset" and len(items) == 860


def test_clamp_detected():
    r, items = runr(ClampServer(1079, at=400), 1079, key="cl")
    assert r.last_paging["ended"] in ("repage_offset_clamped", "repage_short_end") and not r.last_exhausted


def test_max_passes_then_resume_from_saved_state():
    # E5 point 3: bounded, and a retry resumes with the saved union instead of restarting
    RecR.store.clear()
    s = UnstableServer(900, seed=3, block=200)  # very unstable order: slow convergence
    r1, i1 = runr(s, 1079, key="m")
    lp1 = r1.last_paging
    assert lp1["repage"]["passes"] <= paging_v2.MAX_PASSES
    if lp1["ended"] != "server_end_offset":
        assert not r1.last_exhausted and RecR.store.get(("m", "ProfileFollowersQuery"))
        r2, i2 = runr(s, 1079, key="m")
        rp2 = r2.last_paging["repage"]
        assert rp2["resumed_passes"] == lp1["repage"]["passes"] and len(i2) >= len(i1)


def test_large_profile_over_10k():
    r, items = runr(UnstableServer(12000, seed=11), 12500, key="big")
    lp = r.last_paging; rp = lp["repage"]
    assert lp["ended"] in ("server_end_offset", "repage_max_passes", "repage_stalled")
    if lp["ended"] == "server_end_offset":
        assert rp["new"][-3:] == [0, 0, 0] and len(items) >= 0.99 * 12000
    print("large:", lp["ended"], len(items), rp["passes"], rp["new"], r.n)


def test_repage_budget_is_a_failure():
    calls = {"n": 0}

    def over():
        calls["n"] += 1
        return calls["n"] > 60  # the chain (~54 pages) finishes, then the re-page runs out of budget
    r, _ = runr(UnstableServer(1079), 1079, key="b", over=over)
    assert r.last_paging["ended"] == "repage_budget" and not r.last_exhausted


def test_stable_short_by_two_is_not_repaged():
    r, items = run(FakeServer(15), "ProfileFollowersQuery", total=17)
    assert r.last_paging["repage"] is None and r.last_paging["ended"] == "server_end"


# ---- full18c: Chao1 closure, cross-attempt ceiling, state TTL, no state for session runners ----
def test_chao1_formula():
    assert paging_v2.chao1({"a": 1, "b": 2, "c": 2}) == 0.25
    assert paging_v2.chao1({"a": 1, "b": 1}) == 1.0  # f2 = 0: f1 (f1 - 1) / 2
    assert paging_v2.chao1({"a": 3, "b": 4}) == 0


def test_chao1_closure_has_no_misses_over_30_seeds():
    closed, misses, other = 0, [], []
    for seed in range(100, 130):
        RecR.store.clear()
        r, items = runr(UnstableServer(900, seed=seed), 1079, key=f"c{seed}")
        lp = r.last_paging
        while lp["ended"] == "repage_max_passes":  # resume (state saved) until it closes or stops otherwise
            r, items = runr(UnstableServer(900, seed=seed + 1000), 1079, key=f"c{seed}")
            lp = r.last_paging
        if lp["ended"] == "server_end_offset":
            closed += 1; misses.append(900 - len(items))
            assert lp["repage"]["chao1_unseen"] < paging_v2.CHAO1_MAX
        else:
            other.append(lp["ended"]); assert not r.last_exhausted
    print("chao1 closure: closed", closed, "of 30; misses", sum(misses), "; other ends", other)
    assert closed >= 15 and sum(misses) == 0


def test_total_pass_ceiling_is_exhausted():
    RecR.store.clear()
    RecR.store[("x", "ProfileFollowersQuery")] = {"union": [], "passes": 24, "total_passes": 24, "new": [], "served": [], "seen_in": {},
                                                "saved_epoch": __import__("time").time()}
    r, _ = runr(UnstableServer(900, seed=5), 1079, key="x")
    assert r.last_paging["ended"] == "repage_exhausted" and not r.last_exhausted


def test_state_older_than_7_days_restarts():
    RecR.store.clear()
    old = {"union": [{"id": "zz_old"}], "passes": 5, "total_passes": 23, "new": [1], "served": [1], "seen_in": {},
           "saved_epoch": __import__("time").time() - 8 * 86400}
    RecR.store[("t", "ProfileFollowersQuery")] = old
    r, items = runr(UnstableServer(900, seed=6), 1079, key="t")
    assert r.last_paging["repage"]["resumed_passes"] == 0 and all(n["id"] != "zz_old" for n in items)
    assert r.last_paging["ended"] != "repage_exhausted"


def test_no_state_for_session_runner():
    RecR.store.clear()
    s = UnstableServer(900, seed=3, block=200)
    paged = paging_v2.make_paged(offset_paged, cur, Blocked)
    r = RecR(s, "sess"); r.h = "_session"
    asyncio.run(paged(r, [None], "ProfileFollowersQuery", ["profile", "followers"], "cursor", PAGE, 1079, None, {}))
    assert not RecR.store


# ---- full18e: no 98% shortcut for follow lists (Data Feeder capcheck 2026-11-08 19:48Z) ----
def test_short_by_one_percent_is_repaged():
    # 9,900 of a 10,000 header (1% short, 100 accounts) was never re-paged under full18d; now it must be
    r, items = runr(FakeServer(9900), 10000, key="f18e")
    lp = r.last_paging
    assert lp["repage"] is not None and lp["ended"] == "server_end_offset" and len(items) == 9900


def test_98pct_without_server_end_is_not_complete():
    """full18f (capcheck 02:53Z Nov 10): a list short of its header with no PH server end is never labelled complete and keeps
    its resume cursor; the old line labelled 98% of the header (or header-2 for follow lists) as complete."""
    async def short_offset(R_, pages, op, conn_path, var, step, total, cap, extra):
        R_.last_exhausted = False; R_.stop = True  # stopped before the chain could run
        return [{"id": f"u{i}"} for i in range(99)], 0, 5
    for op in ("ProfileCollectionsIndexPage", "ProfileUpvotesQuery"):  # follow lists use the chain only (ends at the server)
        paged = paging_v2.make_paged(short_offset, cur, Blocked)
        r = R(FakeServer(100))
        items, _, _ = asyncio.run(paged(r, [None], op, ["profile", "followers"], "cursor", PAGE, 100, None, {}))
        assert len(items) <= 100
        assert r.last_paging["ended"] not in ("complete", "server_end", "server_end_offset"), (op, r.last_paging["ended"])
        assert not r.last_exhausted
