"""Tests for the public /ph and /try pages: redaction whitelist, SSRF guard, signed run tokens, rate limits."""
import asyncio
import json
import os

import pytest

from mvp.ph_site import live, safe_fetch, try_sim

os.environ.setdefault("TRY_SIGNING_KEY", "test-key-" + "x" * 40)


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
