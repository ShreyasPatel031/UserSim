"""Secret Manager loader: file fallback, hot reload metadata (no values exposed)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from mvp import secrets_store as S


class SecretsStoreTests(unittest.TestCase):
    def setUp(self):
        S.reset_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {"USERSIM_SECRETS_OFF": "1", "USERSIM_ENV_FILE": os.path.join(self.tmp.name, "env")},
            clear=False,
        )
        self.env.start()
        self._bg = mock.patch.object(S, "_maybe_refresh", lambda: None)
        self._bg.start()

    def tearDown(self):
        self._bg.stop()
        self.env.stop()
        self.tmp.cleanup()
        S.reset_for_tests()

    def test_file_fallback_sets_env_and_snapshot(self):
        path = os.environ["USERSIM_ENV_FILE"]
        with open(path, "w") as f:
            f.write("PH_TOKEN=from-file\n")
        S.refresh_now()
        self.assertEqual(os.environ.get("PH_TOKEN"), "from-file")
        snap = S.snapshot()
        self.assertTrue(snap["secrets"]["PH_TOKEN"]["present"])
        self.assertEqual(snap["secrets"]["PH_TOKEN"]["source"], "file")
        self.assertNotIn("from-file", str(snap))

    def test_gsm_wins_over_file_when_enabled(self):
        path = os.environ["USERSIM_ENV_FILE"]
        with open(path, "w") as f:
            f.write("PH_TOKEN=from-file\n")

        def fake_gsm(var: str) -> str | None:
            return "from-gsm" if var == "PH_TOKEN" else None

        with mock.patch.dict(os.environ, {"USERSIM_SECRETS_OFF": "0"}, clear=False):
            with mock.patch("mvp.secrets_store._fetch_gsm", side_effect=fake_gsm):
                S.refresh_now()
            self.assertEqual(os.environ.get("PH_TOKEN"), "from-gsm")
            self.assertEqual(S.snapshot()["secrets"]["PH_TOKEN"]["source"], "secret_manager")
