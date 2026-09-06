"""Unit tests for conditional Browserbase antibot escalation (no live BB)."""

from __future__ import annotations

from mvp.auto_signup import (
    BLOCK_REASONS,
    _cheap_bb_flags,
    _next_antibot_flags,
    _plan_fallback_ladder,
)


def test_cheap_default_is_off():
    flags = _cheap_bb_flags()
    assert flags == {
        "proxies": False,
        "solve_captchas": False,
        "advanced_stealth": False,
    }


def test_captcha_ladder():
    cur = _cheap_bb_flags()
    n1 = _next_antibot_flags(cur, "captcha")
    assert n1 == {
        "proxies": False,
        "solve_captchas": True,
        "advanced_stealth": False,
    }
    n2 = _next_antibot_flags(n1, "captcha_unsolved")
    assert n2["proxies"] is True
    n3 = _next_antibot_flags(n2, "captcha")
    assert n3["advanced_stealth"] is True
    assert _next_antibot_flags(n3, "captcha") is None
    # Default MVP_SIGNUP_ANTIBOT_MAX_ATTEMPTS=4 covers:
    # attempt0 cheap → 1 captcha → 2 proxies → 3 Verified.
    steps = [cur, n1, n2, n3]
    assert len(steps) == 4
    assert steps[-1]["advanced_stealth"] is True


def test_rate_limit_enables_proxies_and_captcha():
    cur = _cheap_bb_flags()
    n1 = _next_antibot_flags(cur, "rate_limited")
    assert n1 == {
        "proxies": True,
        "solve_captchas": True,
        "advanced_stealth": False,
    }
    assert _next_antibot_flags(n1, "ip_block")["advanced_stealth"] is True


def test_bot_block_jumps_to_full():
    n = _next_antibot_flags(_cheap_bb_flags(), "bot_block")
    assert n == {
        "proxies": True,
        "solve_captchas": True,
        "advanced_stealth": True,
    }
    assert _next_antibot_flags(n, "fingerprint") is None


def test_fallback_never_adds_quota():
    desired = {
        "proxies": True,
        "solve_captchas": True,
        "advanced_stealth": True,
    }
    ladder = _plan_fallback_ladder(desired)
    assert ladder[0] == desired
    for item in ladder:
        assert not (item["proxies"] and not desired["proxies"])
        assert not (item["solve_captchas"] and not desired["solve_captchas"])
        assert not (item["advanced_stealth"] and not desired["advanced_stealth"])
    assert ladder[-1] == {
        "proxies": False,
        "solve_captchas": False,
        "advanced_stealth": False,
    }


def test_rate_limited_is_block_reason():
    assert "rate_limited" in BLOCK_REASONS


if __name__ == "__main__":
    test_cheap_default_is_off()
    test_captcha_ladder()
    test_rate_limit_enables_proxies_and_captcha()
    test_bot_block_jumps_to_full()
    test_fallback_never_adds_quota()
    test_rate_limited_is_block_reason()
    print("ok")
