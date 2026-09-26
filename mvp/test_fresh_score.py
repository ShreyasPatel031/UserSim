"""Honest 60-site score: latest fresh signup only. No live browsers."""

from __future__ import annotations

import unittest


class FreshScoreTests(unittest.TestCase):
    def test_score_ignores_hosts_outside_the_60_and_sticky_failures(self) -> None:
        from mvp.repro_signup import fresh_pass_hosts

        products = ["notion.so", "linear.app", "asana.com"]
        doc = {
            "hosts": {
                "codepen.io": {
                    "reproducible": True,
                    "attempts": [{"ok": True, "reason": "signed_up"}],
                },
                "notion.so": {
                    "reproducible": True,
                    "attempts": [
                        {"ok": True, "reason": "signed_up"},
                        {"ok": False, "reason": "captcha_unsolved"},
                    ],
                },
                "linear.app": {
                    "attempts": [{"ok": True, "reason": "signed_up"}],
                },
                "asana.com": {
                    "attempts": [{"ok": True, "reason": "already_signed_in"}],
                },
            }
        }
        self.assertEqual(fresh_pass_hosts(doc, products), ["linear.app"])

    def test_storage_rejudge_matches_the_three_false_negatives(self) -> None:
        from mvp.auto_signup import _storage_state_looks_authed

        bitwarden = {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://vault.bitwarden.com",
                    "localStorage": [{"name": "global_account_accounts", "value": "{}"}],
                }
            ],
        }
        todoist = {
            "cookies": [
                {
                    "name": "tduser",
                    "domain": ".todoist.com",
                    "httpOnly": True,
                    "value": "x" * 40,
                }
            ],
            "origins": [],
        }
        ticktick = {
            "cookies": [
                {
                    "name": "t",
                    "domain": ".ticktick.com",
                    "httpOnly": True,
                    "value": "x" * 120,
                }
            ],
            "origins": [
                {
                    "origin": "https://ticktick.com",
                    "localStorage": [{"name": "someone/tags", "value": "[]"}],
                }
            ],
        }
        anonymous = {
            "cookies": [
                {
                    "name": "_pinterest_sess",
                    "domain": ".pinterest.com",
                    "httpOnly": True,
                    "value": "x" * 80,
                }
            ],
            "origins": [],
        }
        self.assertTrue(_storage_state_looks_authed(bitwarden, "bitwarden.com"))
        self.assertTrue(_storage_state_looks_authed(todoist, "todoist.com"))
        self.assertTrue(_storage_state_looks_authed(ticktick, "ticktick.com"))
        self.assertFalse(_storage_state_looks_authed(anonymous, "pinterest.com"))
        short_t = {
            "cookies": [
                {"name": "t", "domain": ".ticktick.com", "httpOnly": True, "value": "short"}
            ],
            "origins": [],
        }
        self.assertFalse(_storage_state_looks_authed(short_t, "ticktick.com"))


if __name__ == "__main__":
    unittest.main()
