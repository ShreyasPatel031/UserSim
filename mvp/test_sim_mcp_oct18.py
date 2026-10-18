"""Oct 18 e2e fixes: report proof for 1x1x1 studies, study_owner on saved studies, start_study schema."""

import asyncio
import json
import unittest

from mvp.sim_mcp import report as R
from mvp.sim_mcp import server as srv
from mvp.sim_mcp import sessions as S


def _saved_study(owner: str = "anon:abc") -> dict:
    proof = {"pass": True, "checks": [{"name": "real_action", "pass": True, "detail": "clicked"}]}
    row = {"agent_id": "t1__p1__product", "persona_bio": "b", "task_prompt": "t", "trace": [], "mcp_owner": owner,
           "mcp_proof": proof, "page_verdict": {"goal_reached": True, "reason": "ok"}}
    return {"id": "s1", "backend": "mcp", "status": "complete", "url": "https://x.test",
            "agent_results": [dict(row)], "live_sessions": [dict(row)], "summary": {"mcp_proof": {"runs": 1, "passed": 1}}}


class Oct18Tests(unittest.TestCase):
    def test_one_cell_study_report_shows_proof_pass(self):
        rep = R.build_report(_saved_study())
        self.assertTrue(rep["proof"]["pass"])
        self.assertIn("- Proof: PASS", R.report_markdown(rep))

    def test_owner_of_study_loaded_from_disk(self):
        d = _saved_study("anon:abc")
        self.assertEqual(S.study_owner(d), "anon:abc")
        self.assertTrue(S.owns_study(d, "anon:abc"))
        # Same caller from another IP of its NAT/relay pool: still its study.
        self.assertTrue(S.owns_study(d, "anon:other"))
        self.assertFalse(S.owns_study(d, "tokfingerprint"))
        d["live_sessions"] = {"a": {"mcp_owner": "tok"}}
        self.assertEqual(S.study_owner(d), "tok")
        self.assertFalse(S.owns_study(d, "anon:abc"))
        self.assertFalse(S.owns_study(d, "tok2"))

    def test_session_survives_client_ip_change_without_token(self):
        from types import SimpleNamespace
        sim = SimpleNamespace(id="sid1", owner="anon:ip1")
        S.SESSIONS["sid1"] = sim
        try:
            self.assertIs(S.get_session("sid1", "anon:ip2"), sim)
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "tokenfp")
            sim.owner = "tokenfp"
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "anon:ip1")
            with self.assertRaises(S.SessionError):
                S.get_session("sid1", "othertoken")
            self.assertIs(S.get_session("sid1", "tokenfp"), sim)
        finally:
            S.SESSIONS.pop("sid1", None)

    def test_start_study_schema_names_required_fields(self):
        tools = asyncio.run(srv.mcp.list_tools())
        sch = next(t for t in tools if t.name == "usersim_start_study").inputSchema
        defs = sch.get("$defs") or {}
        self.assertEqual(defs["StudyPersona"]["required"], ["bio"])
        self.assertEqual(defs["StudyTask"]["required"], ["prompt"])
        self.assertIn("description", sch["properties"]["personas"])
        self.assertEqual(set(sch["required"]), {"product_url", "personas", "tasks"})
        self.assertIn("Example", json.dumps(sch))


if __name__ == "__main__":
    unittest.main()
