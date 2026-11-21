import datetime as dt
import make_lists as m


def test_off_is_unchanged():
    mon, tue = dt.date(2026, 11, 2), dt.date(2026, 11, 3)
    assert m.following_list(["n"], ["a", "b"], mon, False, ["x"]) == ["a", "b", "n"]
    assert m.following_list(["n"], ["a", "b"], tue, False, ["x"]) == ["n"]


def test_rota_covers_pool_weekly_and_active_daily():
    pool = [f"u{i}" for i in range(2000)] + ["[REDACTED]"]
    act = pool[:300]
    seen, d0 = {}, dt.date(2026, 11, 3)
    for i in range(7):
        d = d0 + dt.timedelta(days=i)
        fol = m.following_list([], act, d, True, pool)
        assert set(act) <= set(fol)
        for u in set(fol) - set(act):
            seen[u] = seen.get(u, 0) + 1
    assert set(seen) == set(pool[300:2000]) and set(seen.values()) == {1}
    assert "[REDACTED]" not in seen


def test_bucket_is_stable():
    assert m.rota_bucket("Alice") == m.rota_bucket("alice ") == m.rota_bucket("alice")


def test_rota_active_mondays_variant():
    pool = [f"u{i}" for i in range(100)]
    tue = dt.date(2026, 11, 3)
    fol = m.following_list([], pool[:10], tue, True, pool, active_daily=False)
    assert not (set(fol) & set(pool[:10])) and fol == m.rota_today(pool, pool[:10], tue)
