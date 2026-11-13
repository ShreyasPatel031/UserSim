"""A newer pull must never drop anything an older pull of the same person saw (Shreyas, Nov 13)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import union_merge as U


def rec(fin, ups, fol, extra=None):
    d = {"run": {"finished_utc": fin, "paging": {"followers": {"ended": "server_end"}}},
         "header": {"upvotes": len(ups), "followers": len(fol)},
         "upvotes": {"header": len(ups), "count": len(ups), "items": [{"post_id": p} for p in ups]},
         "followers": {"header": len(fol), "count": len(fol), "items": [{"ph_user_id": u} for u in fol]}}
    d.update(extra or {})
    return d


def test_nothing_from_older_pull_is_dropped():
    old = rec("2026-11-10T00:00:00Z", ["a", "b"], ["u1", "u2", "u3"], {"about": {"bio": "x"}, "legacy_field": 1})
    new = rec("2026-11-13T00:00:00Z", ["b", "c"], ["u1"])
    m = U.union(new, old)
    assert U.lost(old, m) == (0, 0) and U.lost(new, m) == (0, 0)
    # the newest pull's own lists are untouched; older-only items sit beside them, marked
    assert [x["post_id"] for x in m["upvotes"]["items"]] == ["b", "c"]
    assert [x["post_id"] for x in m["upvotes"]["items_earlier"]] == ["a"]
    assert m["upvotes"]["items_earlier"][0]["_carried_from"] == "2026-11-10T00:00:00Z"
    assert {x["ph_user_id"] for x in m["followers"]["items_earlier"]} == {"u2", "u3"}
    assert m["pull_history"] == ["2026-11-10T00:00:00Z", "2026-11-13T00:00:00Z"]


def test_order_and_idempotence():
    old = rec("2026-11-10T00:00:00Z", ["a"], ["u1"])
    new = rec("2026-11-13T00:00:00Z", ["b"], [])
    j = lambda x: json.dumps(x, sort_keys=True)
    m = U.union(new, old)
    assert j(U.union(old, new)) == j(m)  # the later pull is always the base, whatever the argument order
    assert j(U.union(m, old)) == j(m) and j(U.union(m, m)) == j(m)
    m2 = U.union(rec("2026-11-14T00:00:00Z", [], []), m)  # three pulls deep: still nothing lost
    assert U.lost(old, m2) == (0, 0) and U.lost(new, m2) == (0, 0)


def test_empty_items_earlier_on_older_record_is_kept():
    old = rec("2026-11-10T00:00:00Z", ["a"], [])
    old["upvotes"]["items_earlier"] = []
    new = rec("2026-11-13T00:00:00Z", ["a"], [])
    assert U.lost(old, U.union(new, old)) == (0, 0)
