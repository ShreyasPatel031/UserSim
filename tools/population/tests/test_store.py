import json, os, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import store

IDS = store.Ids("testsalt")


def _reads(rows):
    df = pd.DataFrame(rows)
    df["source"] = "t"
    return df


def test_ids_stable_and_case_insensitive():
    assert IDS("Alice") == IDS("@alice") and IDS("alice") != IDS("bob") and IDS("alice").startswith("p_")
    assert store.Ids("other")("alice") != IDS("alice")


def test_upvote_bounds_from_order():
    # newest first: B (launched Oct 1) above A (launched Oct 20) -> B cast after A's launch
    r = _reads([dict(username="u", position=1, post_id="B", launched_at="2026-10-01T00:00:00-07:00", fetched_at="2026-11-01T10:00:00Z"),
                dict(username="u", position=2, post_id="A", launched_at="2026-10-20T00:00:00-07:00", fetched_at="2026-11-01T10:00:00Z")])
    ev = store.upvote_events(r, IDS).set_index("target_id")
    assert ev.loc["B", "ts_lo"] == pd.Timestamp("2026-10-20T07:00:00Z")
    assert ev.loc["A", "ts_lo"] == pd.Timestamp("2026-10-20T07:00:00Z")
    assert ev.loc["B", "ts_hi"] == pd.Timestamp("2026-11-01T10:00:00Z")


def test_first_seen_tightening():
    old = "2026-09-01T00:00:00-07:00"
    rows = [dict(username="u", position=1, post_id="A", launched_at=old, fetched_at="2026-11-01T10:00:00Z"),
            dict(username="u", position=1, post_id="N", launched_at=old, fetched_at="2026-11-02T10:00:00Z"),
            dict(username="u", position=2, post_id="A", launched_at=old, fetched_at="2026-11-02T10:00:00Z")]
    ev = store.upvote_events(_reads(rows), IDS).set_index("target_id")
    assert ev.loc["N", "ts_lo"] == pd.Timestamp("2026-11-01T10:00:00Z")  # absent in day-1 read that showed older A
    assert ev.loc["N", "ts_hi"] == pd.Timestamp("2026-11-02T10:00:00Z")
    assert ev.loc["A", "ts_hi"] == pd.Timestamp("2026-11-01T10:00:00Z")  # first seen, not last
    assert len(ev) == 2


def test_parse_page_json():
    page = {"props": {"apollo": {"user": {"votedPosts": {"edges": [{"node": {"id": "1"}}, {"node": {"id": "2"}}],
                                                         "pageInfo": {"hasNextPage": True, "endCursor": "MjA"}}}}}}
    p = store.parse_page_json(page)
    assert [n["id"] for n in p["upvote"]["nodes"]] == ["1", "2"] and p["upvote"]["end_cursor"] == "MjA"


def _write(d, tab, rows):
    with open(os.path.join(d, f"{tab}.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _page(u, n, ids, more, f="2026-11-04T10:00:00Z"):
    return dict(username=u, tab="upvotes", page_no=n, status=200, fetched_at=f, post_ids=ids, has_more=more)


def test_validate_pilot_clean_and_faults(tmp_path):
    d = str(tmp_path)
    _write(d, "upvotes", [_page("u", 1, ["1", "2"], True), _page("u", 2, ["3"], False)])
    _write(d, "activity", [dict(username="u", tab="activity", page_no=1, status=200, fetched_at="2026-11-04T10:00:00Z",
                                items=[{"kind": "comment", "created_at": "2026-11-01T00:00:00Z"}])])
    ok, rep = store.validate_pilot(d, profiles={"u": 3})
    assert ok, rep
    assert rep["upvotes"]["complete_people_seen_vs_total_med"] == 1.0
    # planted faults: page gap, duplicate item, future comment time
    _write(d, "upvotes", [_page("u", 1, ["1", "2"], True), _page("u", 3, ["2"], False)])
    _write(d, "activity", [dict(username="u", tab="activity", page_no=1, status=200, fetched_at="2026-11-04T10:00:00Z",
                                items=[{"kind": "comment", "created_at": "2026-11-05T00:00:00Z"}])])
    ok, rep = store.validate_pilot(d)
    assert not ok and rep["upvotes"]["page_gaps"] == 1 and rep["upvotes"]["dup_items"] == 1 and rep["activity"]["bad_times"] == 1


def test_pilot_reads_roundtrip(tmp_path):
    d = str(tmp_path)
    p1 = _page("u", 1, ["1", "2"], True); p1["launched_at"] = ["2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"]
    p2 = _page("u", 2, ["3"], False); p2["launched_at"] = ["2026-10-05T00:00:00Z"]
    _write(d, "upvotes", [p1, p2])
    ev = store.upvote_events(store.pilot_upvote_reads(d), IDS).set_index("target_id")
    assert ev.loc["1", "ts_lo"] == pd.Timestamp("2026-10-05T00:00:00Z")  # page 2 item is older but launched later


def test_revote_flagged_not_failed():
    rows = [dict(username="u", position=1, post_id="A", launched_at="2026-09-01T00:00:00Z", fetched_at="2026-11-01T10:00:00Z"),
            dict(username="u", position=1, post_id="A", launched_at="2026-09-01T00:00:00Z", fetched_at="2026-11-03T10:00:00Z"),
            dict(username="u", position=2, post_id="N", launched_at="2026-11-02T08:00:00Z", fetched_at="2026-11-03T10:00:00Z")]
    ev = store.upvote_events(_reads(rows), IDS).set_index("target_id")
    assert ev.loc["A", "ts_quality"] == "order_conflict" and pd.isna(ev.loc["A", "ts_lo"])
    assert ev.loc["N", "ts_quality"] == "bounded"
