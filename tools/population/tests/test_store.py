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


def test_verify_x_drop(tmp_path):
    d = str(tmp_path)
    pid = IDS("alice")
    _write(d, "persons", [dict(person_id=pid, platform="x")])
    ev = dict(person_id=pid, platform="x", kind="post", target_id="1", ts_lo="2026-10-01T00:00:00Z", ts_hi="2026-10-01T00:00:00Z",
              ts_quality="exact", first_seen_at="2026-11-03T00:00:00Z", fetched_at="2026-11-03T00:00:00Z", source="s", extra={})
    _write(d, "events", [ev])
    assert store.verify_x_drop(d, {pid})[0]
    assert not store.verify_x_drop(d, {IDS("bob")})[0]  # wrong key -> no join -> fail
    _write(d, "events", [ev, ev])
    assert not store.verify_x_drop(d, {pid})[0]          # duplicate


def test_api_comments_dedupe_and_unresolved(tmp_path):
    m = tmp_path / "map.jsonl"
    m.write_text(json.dumps({"user_id": "1", "username": "alice", "last_seen": "x"}) + "\n")
    live = tmp_path / "live.jsonl"
    row = dict(snapshot_at="2026-11-03T23:00:00Z", post_id="P", comment_id="C1", commenter_user_id="1",
               createdAt="2026-11-03T08:00:00Z", parentId=None, votesCount=1)
    live.write_text(json.dumps(row) + "\n" + json.dumps({**row, "snapshot_at": "2026-11-03T23:15:00Z", "votesCount": 3}) + "\n"
                    + json.dumps({**row, "comment_id": "C2", "commenter_user_id": "9"}) + "\n")
    ev = store.api_comment_events([str(live)], IDS, str(m)).set_index(pd.Index(["C1", "C2"]))
    assert len(ev) == 2
    assert ev.loc["C1", "person_id"] == IDS("alice")
    assert ev.loc["C1", "first_seen_at"] == pd.Timestamp("2026-11-03T23:00:00Z")
    assert json.loads(ev.loc["C1", "extra"])["votes"] == 3
    assert json.loads(ev.loc["C2", "extra"])["unresolved"] and ev.loc["C2", "person_id"] == IDS("9", "producthunt_uid")


def test_full_pull_loader(tmp_path):
    import full_pull
    d = {"profile": "https://www.producthunt.com/@alice", "run": {"finished_utc": "2026-11-04T01:00:00Z"},
         "header": {"upvotes": 2, "followers": 100},
         "activity": {"count": 1, "items": [{"type": "left a comment", "url": "https://www.producthunt.com/products/x?comment=55",
                                             "datetime": "2026-11-03T03:00:00-08:00"}]},
         "upvotes": {"count": 2, "items": [{"url": "https://www.producthunt.com/products/x", "post_id": "9"},
                                           {"url": "https://www.producthunt.com/products/y/launches/y-2"}]},
         "followers": {"header": 100, "count": 1, "note": "partial: first 1 loaded", "items": [{"handle": "@bob"}]},
         "forums": {"count": 0, "items": [], "note": "site lists 0 threads (manual saw 20)"}}
    p = tmp_path / "alice.json"; p.write_text(json.dumps(d))
    tabs, ev = full_pull.load_full(str(p), IDS)
    t = tabs.set_index("tab")
    assert bool(t.loc["upvotes", "complete"]) and not bool(t.loc["followers", "complete"]) and bool(t.loc["forums", "complete"])
    assert not bool(t.loc["reviews", "complete"])  # tab absent from the pull
    c = ev[ev.kind == "comment"].iloc[0]
    assert c.ts_quality == "exact" and json.loads(c.extra)["comment_id"] == "55" and c.person_id == IDS("alice")
    assert set(ev[ev.kind == "upvote"].target_id) == {"9", "launch:y-2"}
    f = ev[ev.kind == "follows"].iloc[0]
    assert f.person_id == IDS("bob") and f.target_id == IDS("alice")


def test_activity_comment_launch_time_and_target(tmp_path):
    import full_pull
    d = {"profile": "https://www.producthunt.com/@alice", "run": {"finished_utc": "2026-11-04T12:00:00Z"}, "header": {},
         "activity": {"count": 2, "items": [
             {"type": "left a comment", "url": "https://www.producthunt.com/products/x?comment=1",
              "on_url": "https://www.producthunt.com/products/x/launches/x-2", "datetime": "2026-11-04T00:01:00-08:00"},
             {"type": "left a comment", "url": "https://www.producthunt.com/products/y?comment=2",
              "on_launch_url": "https://www.producthunt.com/products/y?launch=y-3", "datetime": "2026-11-03T05:06:07-08:00"}]}}
    p = tmp_path / "alice.json"; p.write_text(json.dumps(d))
    _, ev = full_pull.load_full(str(p), IDS)
    ev = ev.set_index(ev.extra.map(lambda x: json.loads(x)["comment_id"]))
    assert ev.loc["1", "ts_quality"] == "bounded" and ev.loc["1", "ts_hi"] == pd.Timestamp("2026-11-04T12:00:00Z")
    assert ev.loc["1", "target_id"] == "launch:x-2" and ev.loc["2", "target_id"] == "launch:y-3"
    assert ev.loc["2", "ts_quality"] == "exact"


def test_f1fix_unknown_and_filled(tmp_path):
    import full_pull
    d = {"profile": "https://www.producthunt.com/@alice", "run": {"finished_utc": "2026-11-04T12:00:00Z"}, "header": {},
         "activity": {"count": 3, "items": [
             {"type": "left a comment", "comment_id": "1", "datetime": None, "comment_time_unknown": True,
              "datetime_launch_stamp": "2026-11-03T00:01:00-08:00", "on_url": "https://www.producthunt.com/products/x/launches/x-2"},
             {"type": "left a comment", "comment_id": "2", "datetime": None, "comment_time_unknown": True,
              "on_url": "https://www.producthunt.com/products/y/launches/y-9"},
             {"type": "left a comment", "comment_id": "3", "datetime": "2026-11-03T00:01:00-08:00",
              "datetime_source": "comment.createdAt (thread capture)"}]}}
    p = tmp_path / "alice_f1fix.json"; p.write_text(json.dumps(d))
    filled = {"alice|2": {"created_at": "2026-10-01T10:00:00Z", "method": "api_comment_id", "post_id": "777"}}
    _, ev = full_pull.load_full(str(p), IDS, filled=filled)
    ev = ev.set_index(ev.extra.map(lambda x: json.loads(x)["comment_id"]))
    assert ev.loc["1", "ts_quality"] == "unknown" and pd.isna(ev.loc["1", "ts_lo"])
    assert ev.loc["2", "ts_quality"] == "exact" and ev.loc["2", "target_id"] == "777"
    assert ev.loc["3", "ts_quality"] == "exact"   # restamped from the comment's own createdAt: trusted even at 00:01


def test_light_pull_recognised(tmp_path):
    import full_pull
    d = {"profile": "https://www.producthunt.com/@carol", "mode": "light", "run": {"finished_utc": "2026-11-04T21:00:00Z"},
         "header": {"upvotes": 2, "followers": 9},
         "upvotes": {"header": 2, "count": 2, "items": [{"url": "https://www.producthunt.com/products/x", "post_id": "5"},
                                                        {"url": "https://www.producthunt.com/products/y", "post_id": "6"}]}}
    p = tmp_path / "carol.json"; p.write_text(json.dumps(d))
    tabs, ev = full_pull.load_full(str(p), IDS)
    assert list(tabs.tab) == ["upvotes"] and tabs.pull_type.iloc[0] == "light" and bool(tabs.complete.iloc[0])
    assert set(ev.target_id) == {"5", "6"} and (ev.person_id == IDS("carol")).all()
