"""One signup per site per study, everyone else starts signed in (mvp/sim_mcp/signup_gate.py). No browser, no network:
studies are built with the real create_matrix_study, the gate is driven through sessions._cell_session."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from mvp.sim_mcp import report as R
from mvp.sim_mcp import sessions as S
from mvp.sim_mcp import signup_gate as G

SITES = ["https://tally.so", "https://fillout.com", "https://typeform.com"]
TASKS = [{"prompt": "Sign up for a free account and verify your email"}, {"prompt": "Create a simple contact form"},
         {"prompt": "Design a visually engaging survey"}, {"prompt": "Set up conditional logic for questions"},
         {"prompt": "Export form submissions to CSV"}, {"prompt": "Find a pre-built form template"}]
PERSONAS = [{"name": f"P{i}", "bio": f"persona {i} who runs a small business"} for i in range(1, 7)]


def _study():
    with mock.patch.object(S, "resolves_non_public", return_value=False), mock.patch.object(S, "probe_reachable"):
        return S.create_matrix_study(product_url=SITES[0], competitors=SITES[1:], personas=PERSONAS, tasks=TASKS,
                                     owner="tok:abc")


class Base(unittest.TestCase):
    def setUp(self):
        G.GATES.clear()
        self.saved: set[str] = set()  # domains with a LIVE saved state
        for p in (mock.patch.object(G, "active", return_value=True),
                  mock.patch("mvp.sim_mcp.site_states.load", lambda d: {"domain": d} if d in self.saved else None),
                  mock.patch.object(S, "_check_capacity")):
            p.start()
            self.addCleanup(p.stop)
        self.study = _study()
        from mvp.study import STUDIES

        STUDIES[self.study.id] = self.study
        self.addCleanup(STUDIES.pop, self.study.id, None)

    def cells(self, site, *, task=None, persona=None):
        return [r["agent_id"] for r in self.study.live_sessions.values() if r["site_url"].startswith(site)
                and (task is None or r["task_prompt"].startswith(TASKS[task]["prompt"]))
                and (persona is None or r["persona_id"] == f"p{persona}")]

    def start(self, cid):
        """'run' | 'held' | 'blocked' — what the server does when a client starts this cell."""
        try:
            S._cell_session(self.study.id, cid, "client", "tok:abc")
        except S.SessionError as exc:
            msg = str(exc)
            if msg.startswith("busy"):
                return "held"
            if "blocked at signup" in msg:
                return "blocked"
            raise
        return "run"

    def end(self, cid, signed_in: bool):
        row = self.study.live_sessions[cid]
        row["status"] = "complete"
        if signed_in:
            row["saved_account_written"] = {"domain": "x"}
        return G.cell_ended(self.study, row, signed_in_saved=signed_in)


class GateTests(Base):
    def test_live_state_everyone_starts_signed_in(self):
        self.saved.add("tally.so")
        signup_cell = self.cells("https://tally.so", task=0, persona=2)[0]
        self.assertEqual(self.start(signup_cell), "run")
        row = self.study.live_sessions[signup_cell]
        self.assertEqual(row["gate"], "signed_in")
        self.assertTrue(row["post_signup_only"])  # the signup task's other personas do the post-signup part
        other = self.cells("https://tally.so", task=1, persona=1)[0]
        self.assertEqual(self.start(other), "run")
        self.assertNotIn("post_signup_only", self.study.live_sessions[other])

    def test_one_signup_then_everyone_from_it(self):
        signup = self.cells("https://tally.so", task=0, persona=1)[0]
        others = [c for c in self.cells("https://tally.so") if c != signup]
        self.assertEqual(self.start(others[3]), "held")  # a non-signup cell asked first: held
        self.assertEqual(self.start(signup), "run")
        self.assertEqual(self.study.live_sessions[signup]["gate"], "signup")
        self.assertTrue(all(self.start(c) == "held" for c in others[:5]))
        self.assertEqual(self.start(self.cells("https://fillout.com", task=1, persona=1)[0]), "held")  # its own gate
        self.end(signup, signed_in=True)
        self.assertTrue(all(self.start(c) == "run" for c in others))
        rows = [self.study.live_sessions[c] for c in others]
        self.assertTrue(all(r["gate"] == "signed_in" for r in rows))
        self.assertEqual(sum(1 for r in rows if r.get("post_signup_only")), 5)  # the other 5 personas' signup cells

    def test_failed_signup_retries_with_next_persona_then_blocks(self):
        first = self.cells("https://typeform.com", task=0, persona=1)[0]
        second = self.cells("https://typeform.com", task=0, persona=2)[0]
        self.assertEqual(self.start(first), "run")
        self.assertEqual(self.end(first, signed_in=False), [])
        self.assertEqual(self.start(self.cells("https://typeform.com", task=1, persona=1)[0]), "held")
        self.assertEqual(self.start(second), "run")
        ended = self.end(second, signed_in=False)
        self.assertEqual(len(ended), 34)  # 36 cells on the site minus the two signup runs
        row = self.study.live_sessions[ended[0]]
        self.assertEqual(row["status"], "skipped")
        self.assertIn("typeform.com blocked at signup", row["blocked_at_signup"])
        self.assertEqual(self.start(ended[0]), "blocked")
        # tally is unaffected
        self.assertEqual(self.start(self.cells("https://tally.so", task=0, persona=1)[0]), "run")

    def test_a_failed_open_requeues_and_the_signup_cell_may_start_again(self):
        signup = self.cells("https://tally.so", task=0, persona=1)[0]
        self.assertEqual(self.start(signup), "run")
        self.study.live_sessions[signup]["status"] = "queued"  # start_session requeues a cell whose browser failed
        self.assertEqual(self.start(signup), "run")

    def test_takeover_when_the_designated_cell_is_never_started(self):
        other = self.cells("https://tally.so", task=2, persona=4)[0]
        self.assertEqual(self.start(other), "held")
        G.GATES[(self.study.id, "tally.so")]["held_since"] = time.time() - G.TAKEOVER_S - 1
        self.assertEqual(self.start(other), "run")
        self.assertEqual(G.GATES[(self.study.id, "tally.so")]["signup_cell"], other)

    def test_any_signup_task_cell_may_take_the_signup_role(self):
        p3 = self.cells("https://tally.so", task=0, persona=3)[0]
        self.assertEqual(self.start(p3), "run")
        self.assertEqual(self.start(self.cells("https://tally.so", task=0, persona=1)[0]), "held")

    def test_stale_signup_run_counts_as_failed(self):
        signup = self.cells("https://tally.so", task=0, persona=1)[0]
        self.start(signup)
        self.study.live_sessions[signup]["status"] = "complete"  # ended without reporting (client died)
        G.GATES[(self.study.id, "tally.so")]["started"] = time.time() - S.budget_s() - 400
        self.assertEqual(self.start(self.cells("https://tally.so", task=0, persona=2)[0]), "run")
        self.assertEqual(G.GATES[(self.study.id, "tally.so")]["attempts"], 1)

    def test_dead_saved_state_reopens_the_signup(self):
        self.saved.add("tally.so")
        self.assertEqual(self.start(self.cells("https://tally.so", task=1, persona=1)[0]), "run")
        G.state_died(self.study, "https://tally.so")
        self.assertEqual(G.GATES[(self.study.id, "tally.so")]["status"], "pending")
        self.assertEqual(self.start(self.cells("https://tally.so", task=2, persona=1)[0]), "held")

    def test_inactive_gate_changes_nothing(self):
        with mock.patch.object(G, "active", return_value=False):
            self.assertEqual(self.start(self.cells("https://tally.so", task=3, persona=5)[0]), "run")


class ReportTests(unittest.TestCase):
    def test_post_signup_cells_are_judged_on_onboarding_and_skip_the_signup_proof(self):
        row = {"task_prompt": "Sign up for a free account and verify your email", "post_signup_only": True}
        self.assertIn("signup step is done", R.judge_task(row))
        self.assertEqual(R.judge_task({"task_prompt": "x"}), "x")
        with mock.patch.object(R, "_shot_ok", return_value=True):
            checks = R.proof_checks({"id": "s", "driver": S.DRIVER}, {**row, "trace": [], "agent_id": "a"}, "ok")["checks"]
        self.assertNotIn("signup_verified", [c["name"] for c in checks])

    def test_blocked_cells_are_a_site_finding(self):
        row = {"agent_id": "t2__p1__competitor_2", "site_label": "Typeform", "status": "skipped",
               "blocked_at_signup": "typeform.com blocked at signup: 2 signup run(s)"}
        res = R.skipped_result(row)
        self.assertEqual(res["driver_outcome"], "blocked_at_signup")
        self.assertIn("not a run failure", res["feedback"])
        rep = R.build_study_report({"id": "s", "status": "complete", "live_sessions": [row], "agent_results": [res]})
        self.assertIn("Typeform", rep["blocked_at_signup"])
        self.assertIn("Typeform: blocked at signup", R.study_report_markdown(rep))


class DryRunTests(Base):
    """A whole 108-cell study through the gate, the way the runner drives it (signup cells first, everyone else
    retried until admitted): tally signs up at once, fillout on the second persona, typeform never."""

    def test_full_study(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import mcp_study_runner_lib as lib

        cells = [{"cell_id": r["agent_id"], "site": r["site_url"], "task": r["task_prompt"]}
                 for r in self.study.live_sessions.values()]
        order = [c["cell_id"] for c in lib.signup_first(cells)]
        outcome = {"tally.so": [True], "fillout.com": [False, True], "typeform.com": [False, False]}
        ran, held_polls, blocked = [], 0, []
        pending = list(order)
        for _ in range(20):  # poll rounds
            nxt = []
            for cid in pending:
                res = self.start(cid)
                if res == "held":
                    held_polls += 1
                    nxt.append(cid)
                elif res == "blocked":
                    blocked.append(cid)
                else:
                    row = self.study.live_sessions[cid]
                    dom = G._domain(row["site_url"])
                    if row["gate"] == "signup":
                        ended = self.end(cid, signed_in=outcome[dom].pop(0))
                        blocked += ended
                    else:
                        self.end(cid, signed_in=True)
                    ran.append(cid)
            pending = [c for c in nxt if self.study.live_sessions[c]["status"] == "queued"]
            if not pending:
                break
        rows = self.study.live_sessions
        by = lambda dom, key: sum(1 for c in ran if G._domain(rows[c]["site_url"]) == dom and rows[c].get("gate") == key)  # noqa: E731
        self.assertEqual((by("tally.so", "signup"), by("tally.so", "signed_in")), (1, 35))
        self.assertEqual((by("fillout.com", "signup"), by("fillout.com", "signed_in")), (2, 34))
        self.assertEqual(by("typeform.com", "signup"), 2)
        self.assertEqual(len({c for c in blocked if G._domain(rows[c]["site_url"]) == "typeform.com"}), 34)
        self.assertEqual(sum(1 for c in ran if rows[c].get("post_signup_only")), 5 + 4)  # tally 5, fillout 4
        self.assertEqual(len(ran) + 34, 108)
        print(f"\n[dry run] cells run {len(ran)}, held polls {held_polls}, typeform blocked {34}; "
              f"signed-in starts tally 35 / fillout 34")


if __name__ == "__main__":
    unittest.main()
