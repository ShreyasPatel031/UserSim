"""Tests for the public /ph and /try pages: redaction whitelist, SSRF guard, signed run tokens, rate limits."""
import asyncio
import json
import os

import pytest

from mvp.ph_site import live, safe_fetch, try_sim

os.environ.setdefault("TRY_SIGNING_KEY", "test-key-" + "x" * 40)


@pytest.fixture(autouse=True)
def _not_on_vercel(monkeypatch):
    # Tests must never touch the shared counters or run store, whatever the environment they run in.
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)


def test_product_whitelist_drops_people():
    r = {"id": 1, "name": "Prod", "tagline": "t", "slug": "prod", "topics": {"edges": [{"node": {"name": "SaaS"}}]},
         "makers": [{"username": "someone", "name": "Some One"}], "user": {"username": "hunter1"},
         "website": "https://x/r?utm=1"}
    p = live._product(r)
    assert set(p) == {"id", "name", "tagline", "slug", "topics", "thumb"}
    assert p["thumb"] is None
    s = json.dumps(p)
    assert "someone" not in s and "hunter1" not in s and "Some One" not in s
    assert p["topics"] == ["SaaS"]


def test_thumb_only_ph_cdn():
    assert live._thumb({"url": "https://ph-files.imgix.net/abc-1.png?w=1"}).startswith("https://ph-files.imgix.net/abc-1.png?")
    for bad in ("https://evil.example/x.png", "http://ph-files.imgix.net/a.png", "javascript:alert(1)",
                "https://ph-files.imgix.net.evil.com/a.png", "https://ph-files.imgix.net/a\"onerror=x.png", None, 5):
        assert live._thumb(bad) is None


def test_topics_from_stringified_api_detail():
    assert live._topics("{'nodes': [{'slug': 'marketing', 'name': 'Marketing'}]}") == ["Marketing"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/", "http://169.254.169.254/latest",
                                 "http://localhost:8000", "http://10.0.0.5", "https://www.producthunt.com/posts/x",
                                 "http://metadata.google.internal/", "https://user:pw@example.com", "http://example.com:2375/",
                                 "gopher://example.com"])
def test_ssrf_blocked(url):
    with pytest.raises(safe_fetch.FetchError):
        asyncio.run(safe_fetch.check_url(url))


def test_ip_filter():
    assert not safe_fetch._ip_ok("192.168.1.1") and not safe_fetch._ip_ok("::1") and not safe_fetch._ip_ok("100.64.1.1")
    assert not safe_fetch._ip_ok("::ffff:127.0.0.1")
    assert safe_fetch._ip_ok("8.8.8.8")


def test_extract_strips_scripts():
    ex = safe_fetch.extract("<title>X</title><script>evil()</script><p>Hello <b>world</b></p>")
    assert ex["title"] == "X" and "evil" not in ex["text"] and "Hello world" in ex["text"]


def test_token_roundtrip_and_tamper():
    tok = try_sim.sign({"a": {"name": "n"}})
    assert try_sim.verify(tok)["a"]["name"] == "n"
    a, b = tok.split(".")
    with pytest.raises(PermissionError):
        try_sim.verify(a[:-2] + ("AA" if a[-2:] != "AA" else "BB") + "." + b)


def test_local_rate_limit(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.delenv("VERCEL", raising=False); monkeypatch.delenv("VERCEL_ENV", raising=False)
    try_sim._mem.clear()
    for _ in range(try_sim.CAPS["per_ip_hour"]):
        try_sim.take_slot("1.2.3.4")
    with pytest.raises(PermissionError):
        try_sim.take_slot("1.2.3.4")
    try_sim.take_slot("5.6.7.8")


def test_hits():
    act = {str(i): {"rank": i, "votes": 100 - i} for i in range(1, 21)}
    pred = {str(i): 21 - i for i in range(1, 21)}
    assert live.hits(pred, act, 10) == 0
    assert live.hits({str(i): i for i in range(1, 21)}, act, 3) == 3


def test_e5_summary_shows_roles_tiers_only():
    import numpy as np
    from mvp.ph_site import person_e5
    n = 300
    roles = np.zeros((n, 9), np.uint8)
    roles[:150, 0] = 1          # 150 devs
    roles[150:155, 3] = 1       # 5 founders: too few to show on their own
    B = {"pct99_tree": np.zeros(n, np.float32), "roles": roles,
         "role_names": np.array(["dev", "design", "market", "founder", "product", "data_ai", "sales", "student", "invest"]),
         "n_uses": np.full(n, 6, dtype=np.int32), "n": n}
    score = np.linspace(-1, 1, n)
    score[150:155] = 5           # the rare founders score highest
    out = person_e5.summarize(B, score)
    for p in out["people"]:
        assert set(p) == {"roles", "tier", "likely", "strength", "shared_by"}
        assert p["roles"] != ["founder"]   # a 5-person description is never shown
    assert all(s["likely"] >= 20 for s in out["segments"])


def test_pinned_fetch_uses_validated_ip(monkeypatch):
    """The connection goes to the IP we validated, with the original Host header (no second DNS lookup)."""
    import http.server
    import threading
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["host"] = self.headers.get("Host")
            body = b"<title>T</title><p>" + b"x" * 200 + b"</p>"
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=nope")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    calls = []

    async def fake_resolve(host):
        calls.append(host)
        return ["127.0.0.1"]

    monkeypatch.setattr(safe_fetch, "_resolve", fake_resolve)
    monkeypatch.setattr(safe_fetch, "_behind_proxy", lambda: False)
    monkeypatch.setattr(safe_fetch, "_static_checks", lambda u: (__import__("urllib.parse").parse.urlsplit(
        u.replace("example.test", f"example.test:{port}")), "example.test"))
    status, hdrs, raw = asyncio.run(safe_fetch._get_pinned("http://example.test/"))
    srv.shutdown()
    assert status == 200 and seen["host"] == f"example.test:{port}" and calls == ["example.test"]
    assert "x" * 50 in safe_fetch._decode(raw, "text/html; charset=nope", "")   # unknown charset -> utf-8, no crash


def test_ipv6_tunnels_blocked():
    for ip in ("64:ff9b::7f00:1", "2002:7f00:1::1", "::ffff:10.0.0.1", "fd00::1", "fe80::1"):
        assert not safe_fetch._ip_ok(ip)
    assert safe_fetch._ip_ok("2606:4700::1111")


def test_signing_fails_closed(monkeypatch):
    monkeypatch.delenv("TRY_SIGNING_KEY", raising=False)
    with pytest.raises(try_sim.NotConfigured):
        try_sim.sign({"a": 1})


def test_run_steps_are_one_use(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    tok = try_sim.new_run({"name": "n", "topics": []})
    assert try_sim.use_run(tok, "reactions")["name"] == "n"
    with pytest.raises(PermissionError):
        try_sim.use_run(tok, "reactions")
    try_sim.use_run(tok, "people")
    with pytest.raises(PermissionError):
        try_sim.use_run(tok, "people")


def test_local_limits_ignored_on_vercel(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.setenv("VERCEL", "1")
    assert not try_sim._local_limits()


def test_client_ip_keys(monkeypatch):
    from types import SimpleNamespace
    from mvp.ph_site.routes import _client_ip
    monkeypatch.setenv("VERCEL", "1")
    req = lambda h, peer="9.9.9.9": SimpleNamespace(headers=h, client=SimpleNamespace(host=peer))
    assert _client_ip(req({"x-vercel-forwarded-for": "1.2.3.4", "x-forwarded-for": "6.6.6.6"})) == "1.2.3.4"
    assert _client_ip(req({"x-vercel-forwarded-for": "2001:db8:1:2:aaaa::1"})) == "2001:db8:1:2::/64"
    assert _client_ip(req({"x-vercel-forwarded-for": "2001:db8:1:2:bbbb::9"})) == "2001:db8:1:2::/64"
    monkeypatch.delenv("VERCEL")
    assert _client_ip(req({"x-forwarded-for": "6.6.6.6"})) == "9.9.9.9"   # spoofable header ignored off Vercel


def test_decode_non_text_codecs_and_bad_gzip():
    for cs in ("base64", "rot13", "hex", "zlib", "nope"):
        assert "hi" in safe_fetch._decode(b"hi there", f"text/html; charset={cs}", "")
    with pytest.raises(safe_fetch.FetchError):
        safe_fetch._decode(b"not gzip at all", "text/html", "gzip")


def test_ipv4_compatible_and_siit_blocked():
    assert not safe_fetch._ip_ok("::7f00:1")          # ::127.0.0.1 (IPv4-compatible)
    assert not safe_fetch._ip_ok("::ffff:0:7f00:1")   # SIIT


def test_refund_after_failed_fetch(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    try_sim._mem.clear()

    async def ok(u):
        return u

    async def boom(u):
        raise safe_fetch.FetchError("down")

    monkeypatch.setattr(safe_fetch, "check_url", ok)
    monkeypatch.setattr(safe_fetch, "fetch_product", boom)
    for _ in range(try_sim.CAPS["per_ip_hour"] + 2):   # failures before any model call never use up the hour
        with pytest.raises(safe_fetch.FetchError):
            asyncio.run(try_sim.step_page("https://example.com", "7.7.7.7"))
    assert len(try_sim._mem.get(try_sim._ip_hash("7.7.7.7"), [])) == 0


def test_exp_final_votes_read(monkeypatch):
    doc = {"written_at": "w", "data_up_to": "d", "method": "votes",
           "forecast": [{"id": "1", "pred_rank": 1, "exp_final_votes": 412.6}, {"id": "2", "pred_rank": 2, "exp_final_votes": None}]}
    monkeypatch.setattr(live.gcs, "read_json", lambda path, ttl=0: doc)
    f = live._forecast_file("2026-11-12", "R2")
    assert f["exp_votes"] == {"1": 413}
    doc["forecast"] = [{"id": "1", "pred_rank": 1}]
    assert live._forecast_file("2026-11-12", "R1")["exp_votes"] is None


def test_prereveal_confidence(monkeypatch):
    pc = {"n_days": 6, "note": "replay", "by_point": {"P2": {"pick1": {"in_top3": {"rate": 100.0, "hits": 6, "n": 6}},
                                                             "pick4": {"in_top3": None, "in_top5": {"rate": 50.0, "hits": 3, "n": 6}}}},
          "by_agreement": {"agree": {"picks1_3_in_top3": {"rate": 87.2}, "picks1_5_in_top5": {"rate": 88.7}},
                           "disagree": {"picks1_3_in_top3": {"rate": 63.6}, "picks1_5_in_top5": {"rate": 65.7}}}}
    monkeypatch.setattr(live.gcs, "read_json", lambda path, ttl=0: pc)
    f = {"ranks": {"a": 1, "b": 4, "c": 7}, "agree": {"a": True, "b": False}}
    out = live._prereveal_confidence("P2", f)
    assert out["a"]["hits"] == 6 and out["a"]["what"] == "top 3" and out["a"]["agree_rate"] == 87.2
    assert out["b"]["what"] == "top 5" and out["b"]["agree_rate"] == 65.7 and "c" not in out


def test_lock_state_read(monkeypatch):
    lk = {"label_top3": "2 locked, 1 open", "label_top10": "9 of 10 (vote order)", "label_top5": "top 5 locked", "read_at": "2026-11-12T13:00:00Z", "rule": "r", "point": "R1"}
    real = live.gcs.read_json
    monkeypatch.setattr(live.gcs, "read_json", lambda path, ttl=0: lk if "/lock/" in path else real(path, ttl))
    monkeypatch.setattr(live, "actuals", lambda d: {"final": False, "as_of": None, "revealed": False, "ranks": {}})
    monkeypatch.setattr(live, "_lineup", lambda d: {})
    monkeypatch.setattr(live, "forecasts", lambda d: {})
    monkeypatch.setattr(live, "current_board", lambda d: {"as_of": None, "as_of_pt": "", "ranks": {}, "votes_hidden": True})
    v = live.day_view("2026-11-12")
    assert v["board"]["lock"]["label_top3"] == "2 locked, 1 open" and v["board"]["lock"]["label_top10"] and v["board"]["lock"]["read_pt"] == "05:00 PT"


def test_final_only_from_official_rank_after_3am(monkeypatch):
    rows = [{"_header": True},
            {"id": "a", "dailyRank": "1", "votesCount": "300", "featuredAt": "2026-11-10T08:01:00Z", "fetched_at": "2026-11-11T21:00:00Z"},
            # featured at exactly 00:00 PT Nov 11 -> belongs to Nov 11, not Nov 10
            {"id": "b", "dailyRank": "1", "votesCount": "900", "featuredAt": "2026-11-11T08:00:00Z", "launch_day_PT": "2026-11-10", "fetched_at": "2026-11-11T21:00:00Z"},
            # read before 03:00 PT next day -> not final
            {"id": "c", "dailyRank": "2", "votesCount": "200", "featuredAt": "2026-11-10T08:01:00Z", "fetched_at": "2026-11-11T09:00:00Z"}]
    monkeypatch.setattr(live.gcs, "list_names", lambda prefix, ttl=0: [("raw/ph_at_launch/monthly_reread/2026-11/2026-11-11.jsonl", "")] if "monthly_reread" in prefix else [])
    monkeypatch.setattr(live.gcs, "read_jsonl", lambda path, ttl=0: rows)
    ranks, at = live._monthly_reread("2026-11-10")
    assert set(ranks) == {"a"}


def test_step_text_validates_before_spending(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    try_sim._mem.clear()
    with pytest.raises(ValueError):
        asyncio.run(try_sim.step_text("Name", "Tag", "too short", "8.8.8.8"))
    assert not try_sim._mem.get(try_sim._ip_hash("8.8.8.8"))   # rejected input never took a slot


def test_page_retries_site_root(monkeypatch):
    monkeypatch.setenv("TRY_LOCAL_LIMITS", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    calls = []

    async def ok(u):
        return u

    async def fetch(u):
        calls.append(u)
        if u.endswith("/docs/x"):
            raise safe_fetch.FetchError("403")
        raise safe_fetch.FetchError("root also down")   # stop before any model call

    monkeypatch.setattr(safe_fetch, "check_url", ok)
    monkeypatch.setattr(safe_fetch, "fetch_product", fetch)
    with pytest.raises(safe_fetch.FetchError):
        asyncio.run(try_sim.step_page("https://example.com/docs/x", "9.9.9.9"))
    assert calls == ["https://example.com/docs/x", "https://example.com/"]


def test_difficulty_label(monkeypatch):
    conf = {"label": "clear_leader", "stable": True, "applies_to": "clean shadow model", "text": "Clear leader today.",
            "validated_rates": {"days": 69, "p1_top3": 0.855, "p1_count": "59 of 69"}}
    sb = {"by_label": {"clear_leader": {"days": 3, "p1_top3_count": "2 of 3"}}}
    monkeypatch.setattr(live.gcs, "read_json", lambda path, ttl=0: conf if "/confidence/" in path else sb if "confidence_scoreboard" in path else None)
    assert live._difficulty("2026-11-12") is None            # clean-model label never attached to the published ranking
    conf["applies_to"] = "published"
    d = live._difficulty("2026-11-12")
    assert d["label"] == "clear_leader" and d["forward"]["days"] == 3
    conf.pop("stable")
    assert live._difficulty("2026-11-12") is None


def test_asks_rank_pick_and_note():
    import numpy as np
    from mvp.ph_site import try_sim
    X = np.eye(4, dtype=np.float32)
    # candidate 2 has the highest likelihood and the others tie: it is picked
    assert try_sim._rank_pick(["a", "b"], [], np.zeros((0, 4), np.float32), X, [1, 1, 5, 1]) == 2
    page, pasted = try_sim._asks_note(False), try_sim._asks_note(True)
    assert "2 in 5" in page and "about 1 in 4 of these concerns" in page
    assert "1 in 2" in pasted and "about 1 in 3 of these concerns" in pasted
    assert "no accuracy figure" in try_sim._asks_note(True, 60, "earlier_method") and "1 in 3" not in try_sim._asks_note(True, 60, "earlier_method")
    assert "common concerns" in try_sim._asks_note(False, None, "common")
    assert try_sim.STEP_USES["asks"] == 1
    assert "under 40 words" in try_sim._asks_note(True, 25) and "under 40 words" not in try_sim._asks_note(True, 60)
    R = {"emb": np.array([[1, 0], [0.9, 0.1], [0, 1]], np.float32),
         "rows": [{"slug_stem": "acme-2", "themes": []}, {"slug_stem": "other", "themes": ["objection: too pricey", "praise: nice"]},
                  {"slug_stem": "third", "themes": ["question: is there an API?"]}]}
    nb, s1 = try_sim._b20_neighbours(R, np.array([1, 0], np.float32), "Acme")
    assert nb == [1, 2] and abs(s1 - 0.9) < 1e-6           # the product's own earlier launch (acme-2) is excluded
    assert try_sim._b20_points(R, nb) == "[1] too pricey\n[2] is there an API?"


def test_ph_steady_state_freshness(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from mvp.ph_site import live, gcs
    names = [(f"raw/ph_at_launch/d/snapshots/20261112T{t}PT_api.jsonl", "") for t in ("0245", "0300", "0555", "0600")]
    monkeypatch.setattr(gcs, "list_names", lambda prefix, ttl=0: names if "snapshots" in prefix else [])
    assert live._capture_gaps("2026-11-12") == [{"from_pt": "03:00 PT", "to_pt": "05:55 PT", "minutes": 175}]
    today = live.today_pt()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    f = live._freshness(today, {"0005": {}}, {"as_of": old, "as_of_pt": "05:00 PT"}, final=False)
    assert f["board_stale"] and "not updated since 05:00 PT" in f["board_stale_label"]
    assert f["capture_gaps"][-1]["to_pt"] is None
    fresh = live._freshness(today, {}, {"as_of": datetime.now(timezone.utc).isoformat(), "as_of_pt": "x"}, final=False)
    assert not fresh["board_stale"]
    past = live._freshness("2026-11-01", {"0005": {}, "P1": {}}, {}, final=True)
    assert "P2" in past["missing_points"] and "0005" not in past["missing_points"] and not past["board_stale"]


def test_forecast_0005_markdown_fallback(monkeypatch):
    from mvp.ph_site import live, gcs
    md = "| Predicted rank | Product | Tagline |\n|---|---|---|\n| 1 | Beta | b |\n| 2 | Alpha | a |\n| 3 | Gamma | c |\n"
    lineup = [{"id": 11, "name": "Alpha"}, {"id": 22, "name": "Beta"}, {"id": 33, "name": "Gamma"}]
    monkeypatch.setattr(gcs, "read_bytes", lambda n, ttl=0: md.encode() if n.endswith(".md") else None)
    monkeypatch.setattr(gcs, "read_json", lambda n, ttl=0: lineup if n.endswith("today_0005.json") else None)
    monkeypatch.setattr(gcs, "list_names", lambda prefix, ttl=0: [])
    f = live._forecast_0005_md("2026-11-12")
    assert f["ranks"] == {"22": 1, "11": 2, "33": 3}
    lineup.append({"id": 44, "name": "Delta"}); lineup.append({"id": 55, "name": "Eps"}); lineup.append({"id": 66, "name": "Z"})
    lineup.append({"id": 77, "name": "Y"}); lineup.append({"id": 88, "name": "X"}); lineup.append({"id": 99, "name": "W"})
    assert live._forecast_0005_md("2026-11-12") is None      # too few names matched: no partial order shown


def test_launch_step_returns_input_note(monkeypatch):
    from mvp.ph_site import try_sim, gcs
    lb = {"vocab": {}, "intercept": 0.0, "topics_order": [], "dense_mean": [0, 0, 0], "dense_sd": [1, 1, 1],
          "dense_coef": [0, 0, 0], "score_percentile_cuts": list(range(-50, 50)),
          "bands": [{"decile": i + 1, "daily_rank_p10_p50_p90": [1, 5, 20], "votes_p10_p50_p90": [10, 50, 200],
                    "share_top3": 0.1, "share_top10": 0.3, "n": 100} for i in range(10)],
          "heldout_accuracy": {"days": 200, "top3": 29, "top5": 40, "top10": 60, "within_day_spearman": 0.2},
          "trained_on": {"launches": 1000, "days": ["2026-01-01", "2026-11-10"]}}
    monkeypatch.setattr(gcs, "read_json", lambda n, ttl=0: lb if n.endswith("launch_band.json") else None)
    monkeypatch.setattr(try_sim, "use_run", lambda tok, step: {"name": "X", "tagline": "y", "ph_description": "z " * 50,
                                                                "topics": [], "source": "pasted"})
    out = try_sim.step_launch("t")
    assert out["input_note"] and "0.35" in out["input_note"] and out["coverage"] is None


def test_why_is_sanitised(monkeypatch):
    from mvp.ph_site import live, gcs
    f = {"as_of": "2026-11-13T08:10:00+00:00", "min_group": 20, "shadow": True,
         "items": {"held_backers": {"label": "Backers", "unit": "people", "note": "n1"},
                   "tiers": {"label": "Tiers", "unit": "share by tier", "note": "n1"}},
         "notes": {"n1": "Descriptive."},
         "launches": {"1": {"held_backers": {"value": 120, "n_people": 120, "coverage": {"team_members_named": 2}, "note": "n1"},
                            "tiers": {"value": {"this launch": {"0": 0.5, "x": "bob"}}, "n_people": 40},
                            "secret": {"value": 3, "n_people": 50}},
                      "2": {"held_backers": {"value": 7, "n_people": 7, "username": "bob"}},
                      "999": {"held_backers": {"value": 500, "n_people": 500}}}}
    monkeypatch.setattr(gcs, "read_json", lambda n, ttl=0: f if n == "results/web/why/2026-11-13_0005.json" else None)
    monkeypatch.delenv("PH_WHY_PREFIX", raising=False)
    w = live.why("2026-11-13", "0005", {"1", "2"})
    assert set(w["launches"]) == {"1"}                      # under-20 group and unknown launch dropped
    assert set(w["launches"]["1"]) == {"held_backers", "tiers"} and "bob" not in str(w)
    assert w["launches"]["1"]["tiers"]["value"] == {"this launch": {"0": 0.5}}
    assert w["items"]["held_backers"]["note"] == "Descriptive." and w["shadow"] is True
    assert live.why("2026-11-13", "P1", {"1"}) is None
    monkeypatch.setenv("PH_WHY_PREFIX", "tmp/e5/why_shadow"); monkeypatch.setenv("VERCEL", "1")
    assert live._why_prefix() == "results/web/why"         # the preview override is ignored on the deployed site
