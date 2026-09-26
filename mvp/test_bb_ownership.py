"""Unit tests for Browserbase session ownership tagging / selective release."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class SessionMetadataTests(unittest.TestCase):
    def test_session_user_metadata_defaults(self) -> None:
        from capability.browserbase_client import BB_OWNER_E2E, session_user_metadata

        self.assertEqual(session_user_metadata(), {"owner": BB_OWNER_E2E})
        self.assertEqual(
            session_user_metadata(study_id="abc"),
            {"owner": "e2e", "study_id": "abc"},
        )
        self.assertEqual(
            session_user_metadata(owner="signup", study_id="s1"),
            {"owner": "signup", "study_id": "s1"},
        )

    def test_study_owner_honors_testfix(self) -> None:
        from capability.browserbase_client import study_session_owner

        with patch.dict("os.environ", {"MVP_BB_OWNER": "testfix"}, clear=False):
            self.assertEqual(study_session_owner(), "testfix")
        with patch.dict("os.environ", {"MVP_BB_OWNER": "gates"}, clear=False):
            self.assertEqual(study_session_owner(), "gates")
        with patch.dict("os.environ", {"MVP_BB_OWNER": "taskfix"}, clear=False):
            self.assertEqual(study_session_owner(), "taskfix")
        with patch.dict("os.environ", {"MVP_BB_OWNER": "integration"}, clear=False):
            self.assertEqual(study_session_owner(), "integration")
        with patch.dict("os.environ", {"MVP_BB_OWNER": ""}, clear=False):
            self.assertEqual(study_session_owner(), "e2e")


class KillFilterTests(unittest.TestCase):
    def _fake_sessions(self) -> list[MagicMock]:
        def _s(sid: str, owner: str | None, study: str | None = None) -> MagicMock:
            m = MagicMock()
            m.id = sid
            m.status = "RUNNING"
            meta = {}
            if owner is not None:
                meta["owner"] = owner
            if study is not None:
                meta["study_id"] = study
            m.user_metadata = meta or None
            return m

        return [
            _s("e2e-1", "e2e", "study-a"),
            _s("e2e-2", "e2e", "study-b"),
            _s("signup-1", "signup", "signup"),
            _s("untagged-1", None),
        ]

    def test_list_running_defaults_to_e2e_only_via_kill(self) -> None:
        from mvp.kill_switch import kill_all_browserbase

        sessions = self._fake_sessions()
        bb = MagicMock()
        bb.sessions.list.return_value = sessions
        released: list[str] = []

        def _release(sid: str) -> bool:
            released.append(sid)
            return True

        with (
            patch("mvp.kill_switch._bb_client", return_value=bb),
            patch("mvp.kill_switch.release_browserbase_session", side_effect=_release),
        ):
            # list_running with owner=e2e will call list(q=...); our mock returns
            # all sessions — client-side filter must still drop signup/untagged.
            result = kill_all_browserbase(owner="e2e")

        self.assertEqual(sorted(released), ["e2e-1", "e2e-2"])
        self.assertEqual(result["released"], 2)
        self.assertEqual(result["owner"], "e2e")
        skipped_ids = {row["id"] for row in result["skipped"]}
        # When BB q filter works, signup/untagged never appear in `running`.
        # Either way they must not be in released.
        self.assertNotIn("signup-1", released)
        self.assertNotIn("untagged-1", released)
        self.assertTrue("signup-1" not in released and "untagged-1" not in released)

    def test_kill_all_star_can_release_everything(self) -> None:
        from mvp.kill_switch import kill_all_browserbase

        sessions = self._fake_sessions()
        bb = MagicMock()
        bb.sessions.list.return_value = sessions
        released: list[str] = []

        with (
            patch("mvp.kill_switch._bb_client", return_value=bb),
            patch(
                "mvp.kill_switch.release_browserbase_session",
                side_effect=lambda sid: released.append(sid) or True,
            ),
        ):
            result = kill_all_browserbase(owner="*")

        self.assertEqual(sorted(released), ["e2e-1", "e2e-2", "signup-1", "untagged-1"])
        self.assertEqual(result["released"], 4)

    def test_study_id_scopes_release(self) -> None:
        from mvp.kill_switch import kill_all_browserbase

        sessions = self._fake_sessions()
        bb = MagicMock()
        bb.sessions.list.return_value = sessions
        released: list[str] = []

        with (
            patch("mvp.kill_switch._bb_client", return_value=bb),
            patch(
                "mvp.kill_switch.release_browserbase_session",
                side_effect=lambda sid: released.append(sid) or True,
            ),
        ):
            kill_all_browserbase(owner="e2e", study_id="study-a")

        self.assertEqual(released, ["e2e-1"])


if __name__ == "__main__":
    unittest.main()
