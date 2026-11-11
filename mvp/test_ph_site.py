"""Tests for the public /ph and /try pages: redaction whitelist, SSRF guard, signed run tokens, rate limits."""
import asyncio
import json
import os

import pytest

from mvp.ph_site import live, safe_fetch, try_sim


def test_product_whitelist_drops_people():
    r = {"id": 1, "name": "Prod", "tagline": "t", "slug": "prod", "topics": {"edges": [{"node": {"name": "SaaS"}}]},
         "makers": [{"username": "someone", "name": "Some One"}], "user": {"username": "hunter1"},
         "website": "https://x/r?utm=1"}
    p = live._product(r)
    assert set(p) == {"id", "name", "tagline", "slug", "topics"}
    s = json.dumps(p)
    assert "someone" not in s and "hunter1" not in s and "Some One" not in s
    assert p["topics"] == ["SaaS"]


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
