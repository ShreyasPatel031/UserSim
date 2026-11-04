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
