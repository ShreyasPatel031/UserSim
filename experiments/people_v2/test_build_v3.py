"""Tests for build_v3.py / validate_v3.py on a small synthetic dataset (no bucket, no network). Run: python -m pytest experiments/people_v2/test_build_v3.py
Needs pandas + pyarrow."""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import pathlib

import pandas as pd
import pytest

HERE = pathlib.Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B, V = _load("build_v3"), _load("validate_v3")
L = lambda k, u: {"kind": k, "url": u}  # noqa: E731


def _w(path, rows):
    with gzip.open(path, "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _prof(h):
    return {"handle": h, "profile": {"name": h, "description": "d", "tweets": 1},
            "posts": [{"id": h + "1", "created_at": "2026-10-01T10:00:00Z", "text": "t"}]}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = tmp_path
    (r / "raw/ph_profiles2_refetch").mkdir(parents=True)
    (r / "ev").mkdir()
    (r / "t").mkdir()
    for f in ("ph_profiles", "ph_profiles2"):
        _w(r / f"raw/{f}.jsonl.gz", [])
    # alice: poisoned legacy row repaired by the re-fetch; own link alive. dana: dead own link, live matching field.
    # fay: dead own link, live field with a different name. gus: dead own link, field not looked up. holly: field only. erin: two links.
    _w(r / "raw/ph_profiles_rest.jsonl.gz", [{"username": "alice", "user_id": "606339", "name": "Wispr Flow", "links": []}])
    mk = lambda u, n, tw, links: {"username": u, "status": 200, "user_id": str(100 + len(u)), "name": n, "joined": "2024",  # noqa: E731
                                  "fetched_at": "2026-11-02", "twitter": tw, "links": links}
    _w(r / "raw/ph_profiles2_refetch/profiles.jsonl.gz", [
        mk("alice", "Alice Ray", "alice_f", [L("twitter", "https://x.com/alice_x")]),
        mk("dana", "Dana Lee", "dana_live", [L("twitter", "https://x.com/dana_dead")]),
        mk("fay", "Fay Roe", "fay_live", [L("twitter", "https://x.com/fay_dead")]),
        mk("gus", "Gus Ito", "gus_field", [L("twitter", "https://x.com/gus_dead")]),
        mk("holly", "Holly Ng", "holly_f", []),
        mk("erin", "Erin Oh", None, [L("twitter", "https://x.com/b_first"), L("twitter", "https://x.com/a_second"),
                                     L("website", "https://x.com/acme_co")])])
    _w(r / "raw/x_people.jsonl.gz", [_prof(h) for h in ("alice_x", "dana_dead", "dana_live", "holly_f", "b_first")])
    (r / "raw/x_posts.jsonl.gz").write_bytes(gzip.compress(b""))
    users = ["alice", "dana", "fay", "gus", "holly", "erin"]
    pd.DataFrame({"person": users, "twitter": None, "about": [float("nan")] * 6, "joined": None, "upvotes_total": None,
                  "first_seen": "x"}).to_parquet(r / "t/people.parquet", index=False)
    pd.DataFrame({"person": users + ["zed"], "launch_id": 1, "date": "2026-10-01", "kind": "upvote",
                  "date_quality": "launch_day"}).to_parquet(r / "ev/p.parquet", index=False)
    xl = {"alice_x": {"exists": True, "name": "Alice Ray"}, "alice_f": {"exists": True, "name": "Alice Ray"},
          "dana_dead": {"exists": False, "name": None}, "dana_live": {"exists": True, "name": "Dana Lee"},
          "fay_dead": {"exists": False, "name": None}, "fay_live": {"exists": True, "name": "Zzz Qqq"},
          "gus_dead": {"exists": False, "name": None}}
    (r / "x_lookup.json").write_text(json.dumps(xl))
    monkeypatch.chdir(r)
    return r


def _build(root, out, **kw):
    B.MISSING.clear()
    B.main(str(root), out, **kw)
    d = root / out
    return {t: pd.read_parquet(d / f"{t}.parquet") for t in ("persons", "handles", "profiles", "events")}


def _x(H, person):
    h = H[(H.person_id == f"ph:{person}") & (H.platform == "x")]
    return {r.handle: (r.source, round(r.confidence, 2)) for r in h.itertuples()}


def test_fallback_is_off_by_default_even_with_a_lookup_file(root):
    T = _build(root, "off")
    assert _x(T["handles"], "dana") == {"dana_dead": ("ph_self_link", 0.95), "dana_live": ("ph_twitter_field", 0.2)}
    assert "ph_twitter_field_live_fallback" not in set(T["handles"].source)


def test_fallback_on_flips_only_the_qualifying_conflict(root):
    T = _build(root, "on", x_fallback=True)
    assert _x(T["handles"], "dana") == {"dana_dead": ("ph_self_link", 0.2), "dana_live": ("ph_twitter_field_live_fallback", 0.8)}
    assert _x(T["handles"], "alice")["alice_x"] == ("ph_self_link", 0.95)  # live own link kept
    assert _x(T["handles"], "fay")["fay_dead"] == ("ph_self_link", 0.95)  # field name does not match
    assert _x(T["handles"], "gus")["gus_dead"] == ("ph_self_link", 0.95)  # field not looked up
    xp = T["profiles"][T["profiles"].platform == "x"]
    assert "dana_live" in set(xp.handle) and "dana_dead" not in set(xp.handle)


def test_fallback_similarity_threshold(root):
    T = _build(root, "hi", x_fallback=True, x_fallback_sim=1.01)
    assert _x(T["handles"], "dana")["dana_dead"] == ("ph_self_link", 0.95)


def test_fallback_without_lookup_file_is_an_error_not_a_silent_skip(root):
    (root / "x_lookup.json").unlink()
    with pytest.raises(FileNotFoundError):
        _build(root, "err", x_fallback=True)


def test_field_only_handle_is_below_threshold_with_no_profile_or_posts(root):
    T = _build(root, "f")
    assert _x(T["handles"], "holly") == {"holly_f": ("ph_twitter_field", 0.6)}
    assert "holly_f" not in set(T["profiles"][T["profiles"].platform == "x"].handle)
    assert "ph:holly" not in set(T["events"][T["events"].platform == "x"].person_id)


def test_first_listed_link_is_primary_and_wrong_kind_links_are_not_handles(root):
    T = _build(root, "k")
    assert _x(T["handles"], "erin") == {"b_first": ("ph_self_link", 0.95), "a_second": ("ph_self_link_extra", 0.5)}


def test_poisoned_row_is_repaired_and_event_only_person_is_kept(root):
    T = _build(root, "p")
    P = T["persons"].set_index("person_id")
    assert P.loc["ph:alice", "display_name"] == "Alice Ray" and P.loc["ph:alice", "profile_parser"] == "refetch-2026-11"
    assert P.loc["ph:zed", "has_profile"] == False and P.loc["ph:zed", "in_events"] == True  # noqa: E712
    assert not (~T["events"].person_id.isin(set(P.index))).any()


def test_missing_v1_values_are_null_not_the_text_NaN(root):
    T = _build(root, "n")
    Pr = T["profiles"]
    assert not (Pr[["name", "bio", "location", "website", "extra"]] == "NaN").any().any()


@pytest.mark.parametrize("flag", [False, True])
def test_validator_passes_on_both_modes(root, flag):
    out = f"v{int(flag)}"
    _build(root, out, x_fallback=flag)
    rc = V.main(str(root / out), str(root / "raw/ph_profiles2_refetch*/profiles.jsonl.gz"), str(root / "ev/*.parquet"))
    assert rc == 0
