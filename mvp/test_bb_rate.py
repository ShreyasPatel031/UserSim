"""Browserbase create burst bucket: fake clock, priorities, 429 parsing, queue gate."""
from __future__ import annotations

import threading
import unittest
from unittest import mock

from capability.bb_rate import (
    BucketTimeout,
    CreateBucket,
    is_burst_limit,
    parse_retry_after,
)

BODY = (
    "Error code: 429 - {'statusCode': 429, 'error': 'Too Many Requests', 'message': "
    "\"You've exceeded your burst rate limit (25 requests per 1 minute). "
    "You can try again in 34 seconds.\"}"
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def bucket(clock: FakeClock, cap: int = 22) -> CreateBucket:
    return CreateBucket(cap, 60.0, clock=clock.now, sleep=clock.sleep, jitter=lambda: 1.0)


class BucketWindowTests(unittest.TestCase):
    def test_first_22_are_immediate_and_the_23rd_waits_for_the_oldest_to_age_out(self):
        c = FakeClock()
        b = bucket(c)
        for i in range(22):
            self.assertEqual(b.acquire(), 0.0)
            c.t += 0.5  # 22 creates spread over 11s
        self.assertEqual(b.recent(), 22)
        start = c.t
        waited = b.acquire()
        # Oldest grant was at 1000.0; it leaves the window at 1060.0.
        self.assertAlmostEqual(c.t, 1060.0, places=6)
        self.assertAlmostEqual(waited, 1060.0 - start, places=6)
        self.assertEqual(b.recent(), 22)

    def test_30_creates_never_exceed_22_in_any_rolling_minute(self):
        c = FakeClock()
        b = bucket(c)
        grants = []
        for _ in range(30):
            b.acquire()
            grants.append(c.t)
        for i, t in enumerate(grants):
            in_window = [g for g in grants if t - 60.0 < g <= t]
            self.assertLessEqual(len(in_window), 22, f"grant {i}")
        self.assertAlmostEqual(grants[-1] - grants[0], 60.0, places=6)
        self.assertAlmostEqual(b.stats["max_wait_s"], 60.0, places=6)

    def test_room_in_reports_when_n_tokens_are_free(self):
        c = FakeClock()
        b = bucket(c)
        for _ in range(20):
            b.acquire()
            c.t += 1.0
        # 20 used, 2 free now; 5 free once the 3 oldest (t=1000,1001,1002) expire.
        self.assertEqual(b.room_in(2), 0.0)
        self.assertAlmostEqual(b.room_in(5), 1062.0 - c.t, places=6)

    def test_deadline_raises_instead_of_waiting_past_it(self):
        c = FakeClock()
        b = bucket(c, cap=2)
        b.acquire()
        b.acquire()
        with self.assertRaises(BucketTimeout):
            b.acquire(deadline=c.t + 10.0)
        self.assertEqual(b.waiting(), 0)

    def test_cancel_stops_a_waiting_create_without_a_token(self):
        c = FakeClock()
        b = bucket(c, cap=1)
        b.acquire()
        ev = threading.Event()
        ev.set()
        with self.assertRaises(BucketTimeout):
            b.acquire(cancel=ev)
        self.assertEqual(b.recent(), 1)

    def test_on_wait_is_told_how_long(self):
        c = FakeClock()
        b = bucket(c, cap=1)
        b.acquire()
        seen = []
        b.acquire(on_wait=lambda s, why: seen.append((round(s), why)))
        self.assertEqual(seen[0], (60, "create budget"))


class BucketRateLimitTests(unittest.TestCase):
    def test_429_blocks_every_grant_until_retry_after_plus_jitter(self):
        c = FakeClock()
        b = bucket(c)
        b.acquire()
        resume = b.note_rate_limited(34.0)
        self.assertAlmostEqual(resume, c.t + 35.0)  # 34s + 1s jitter
        start = c.t
        waited = b.acquire()
        self.assertAlmostEqual(waited, 35.0, places=6)
        self.assertAlmostEqual(c.t - start, 35.0, places=6)
        self.assertEqual(b.stats["rate_limited"], 1)

    def test_a_rejected_create_gives_its_token_back(self):
        c = FakeClock()
        b = bucket(c)
        for _ in range(22):
            b.acquire()
        self.assertEqual(b.recent(), 22)
        b.note_rate_limited(5.0)
        self.assertEqual(b.recent(), 21)
        b.note_rate_limited(5.0, refund=False)
        self.assertEqual(b.recent(), 21)

    def test_unknown_retry_after_waits_half_a_window(self):
        c = FakeClock()
        b = bucket(c)
        self.assertAlmostEqual(b.note_rate_limited(None) - c.t, 31.0)


class BucketPriorityTests(unittest.TestCase):
    def test_product_waiter_is_served_before_an_earlier_rival(self):
        b = CreateBucket(1, 0.3, jitter=lambda: 0.0)
        b.acquire()  # window full for 0.3s
        order: list[str] = []
        started = threading.Event()

        def run(name: str, prio: int) -> None:
            if name == "rival":
                started.set()
            b.acquire(prio)
            order.append(name)

        rival = threading.Thread(target=run, args=("rival", 2))
        rival.start()
        started.wait(1)
        # Make sure the rival is queued first.
        for _ in range(100):
            if b.waiting() == 1:
                break
            threading.Event().wait(0.005)
        prod = threading.Thread(target=run, args=("product", 0))
        prod.start()
        for t in (rival, prod):
            t.join(3)
        self.assertEqual(order, ["product", "rival"])


class RetryAfterParsingTests(unittest.TestCase):
    def test_parses_browserbase_burst_body(self):
        self.assertEqual(parse_retry_after(BODY), 34.0)
        self.assertEqual(parse_retry_after(RuntimeError(BODY)), 34.0)

    def test_units_and_header(self):
        self.assertEqual(parse_retry_after("try again in 1 minute"), 60.0)
        self.assertEqual(parse_retry_after("try again in 500ms"), 0.5)
        self.assertEqual(parse_retry_after("Try again in 7.5 seconds."), 7.5)
        self.assertEqual(parse_retry_after('{"retry-after": 12}'), 12.0)
        self.assertIsNone(parse_retry_after("Error code: 500 internal"))

        class Resp:
            headers = {"retry-after": "9"}

        class Exc(Exception):
            response = Resp()

        self.assertEqual(parse_retry_after(Exc("429")), 9.0)

    def test_is_burst_limit(self):
        self.assertTrue(is_burst_limit(RuntimeError(BODY)))

        class E(Exception):
            status_code = 429

        self.assertTrue(is_burst_limit(E("x")))
        self.assertFalse(is_burst_limit(RuntimeError("Error code: 402 payment required")))


class CreateSessionRetriesThe429Tests(unittest.TestCase):
    def test_429_is_retried_as_the_same_create_not_dropped(self):
        from capability import bb_rate, browserbase_client as bc

        c = FakeClock()
        b = bucket(c)
        calls = []

        class Sess:
            id = "s1"
            connect_url = "wss://x"

        class FakeSessions:
            def create(self, **kw):
                calls.append(c.t)
                if len(calls) == 1:
                    raise RuntimeError(BODY)
                return Sess()

        class FakeBB:
            def __init__(self, *a, **kw):
                self.sessions = FakeSessions()

        with mock.patch.object(bc, "Browserbase", FakeBB), \
                mock.patch.object(bc, "create_bucket", lambda: b), \
                mock.patch.object(bc, "browserbase_api_key", lambda: "k"), \
                mock.patch.object(bc, "browserbase_project_id", lambda: "p"):
            got = bc.create_session(wait_s=300, solve_captchas=False, advanced_stealth=False)
            bc.close_session(got.id)
        self.assertEqual(got.id, "s1")
        self.assertEqual(len(calls), 2)
        # Second request only after the server's 34s (+1s jitter).
        self.assertGreaterEqual(calls[1] - calls[0], 35.0)
        self.assertEqual(b.stats["rate_limited"], 1)
        self.assertIsNotNone(bb_rate)


class QueueCountsRecentCreatesTests(unittest.TestCase):
    def test_burst_state_blocks_when_recent_creates_leave_too_little_room(self):
        from mvp import browser_slots

        c = FakeClock()
        b = bucket(c)
        for _ in range(20):
            b.acquire()
        with mock.patch("capability.bb_rate.create_bucket", lambda: b):
            st = browser_slots.burst_state(24, {"n": 0, "recent_ages_s": []})
            self.assertFalse(st["ok"])
            self.assertEqual(st["want"], 16)
            self.assertEqual(st["recent"], 20)
            self.assertAlmostEqual(st["eta_s"], 60.0, places=6)
            c.t += 61
            self.assertTrue(browser_slots.burst_state(24, {"n": 0})["ok"])

    def test_remote_creates_from_another_server_count_too(self):
        from mvp import browser_slots

        c = FakeClock()
        b = bucket(c)
        with mock.patch("capability.bb_rate.create_bucket", lambda: b):
            ages = [5.0 + i for i in range(20)]  # 20 sessions opened 5-24s ago elsewhere
            st = browser_slots.burst_state(24, {"n": 20, "recent_ages_s": ages})
            self.assertFalse(st["ok"])
            # Need 16 free of 22: the 14 oldest must age out; the 14th oldest is 11s old.
            self.assertAlmostEqual(st["eta_s"], 49.0, places=6)


if __name__ == "__main__":
    unittest.main()
