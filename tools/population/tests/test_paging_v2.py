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
    assert len(items) == 10 and r.last_exhausted and r.last_paging["ended"] == "server_end"


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



def test_repeated_chain_is_repaged_to_server_end_offset():
    s = UnstableServer(1079)
    r, items = run(s, "ProfileFollowersQuery", total=1079)
    lp = r.last_paging
    assert lp["repage"] and lp["repage"]["start_items"] < 0.98 * 1079 and lp["repage"]["start_dups"] > 0  # chain alone was short
    assert lp["ended"] == "server_end_offset" and len(items) >= 0.98 * 1079 and len({n["id"] for n in items}) == len(items)
    assert r.last_exhausted


def test_repage_with_hidden_accounts_closes_on_a_zero_new_pass():
    s = UnstableServer(900)  # header 1,079 but PH lists only 900 signed out
    r, items = run(s, "ProfileFollowersQuery", total=1079)
    lp = r.last_paging
    assert lp["ended"] == "server_end_offset" and lp["repage"]["new"][-2:] == [0, 0] and len(items) == 900


def test_repage_offset_ignored_is_a_failure_not_an_end():
    s = UnstableServer(1079, offset_limit=200)
    r, items = run(s, "ProfileFollowersQuery", total=1079)
    assert r.last_paging["ended"] in ("repage_offset_ignored", "repage_offset_runaway") and not r.last_exhausted


def test_repage_budget_is_a_failure():
    s = UnstableServer(1079)
    paged = paging_v2.make_paged(offset_paged, cur, Blocked)
    r = R(s); calls = {"n": 0}

    def over():
        calls["n"] += 1
        return calls["n"] > 60  # the chain (~54 pages) finishes, then the re-page runs out of budget
    r.over = over
    asyncio.run(paged(r, [None], "ProfileFollowersQuery", ["profile", "followers"], "cursor", PAGE, 1079, None, {}))
    assert r.last_paging["ended"] == "repage_budget" and not r.last_exhausted


def test_stable_short_chain_is_not_repaged():
    r, items = run(FakeServer(10), "ProfileFollowersQuery", total=17)
    assert r.last_paging["repage"] is None and r.last_paging["ended"] == "server_end"
