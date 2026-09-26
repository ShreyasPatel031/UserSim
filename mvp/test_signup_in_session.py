"""Unit tests for the in-run signup hook (no browser, no network)."""

from __future__ import annotations

import unittest

from mvp.a11y_agent import account_wall, goal_visible, task_needs_account
from mvp.signup_inbox import rank_links
from mvp.signup_in_session import _OAUTH, _visible_elements


class TaskNeedsAccount(unittest.TestCase):
    def test_account_tasks(self) -> None:
        for task in ("Create an issue", "Make a board", "Add a card to a list", "Create a new project",
                     "Create a new page in your workspace"):
            self.assertTrue(task_needs_account(task), task)

    def test_logged_out_tasks(self) -> None:
        for task in ("Find the pricing page", "Find how to create a new issue", "Draw a simple box",
                     "Read the changelog", "Open keyboard shortcuts help"):
            self.assertFalse(task_needs_account(task), task)


class AccountWall(unittest.TestCase):
    def test_marketing_page_with_signup_for_account_task(self) -> None:
        read = {"url": "https://linear.app/", "text": "Linear plan and build", "nodes": [
            {"role": "link", "name": "Log in", "href": "/login"},
            {"role": "link", "name": "Sign up", "href": "/signup"},
            {"role": "link", "name": "Pricing", "href": "/pricing"},
        ]}
        wall = account_wall("Create an issue", read)
        self.assertIsNotNone(wall)
        self.assertEqual(wall["signup_url"], "/signup")

    def test_auth_page(self) -> None:
        read = {"url": "https://trello.com/login", "text": "", "nodes": []}
        self.assertIsNotNone(account_wall("Make a board", read))

    def test_logged_out_task_never_walls(self) -> None:
        read = {"url": "https://linear.app/login", "text": "Log in email password", "nodes": []}
        self.assertIsNone(account_wall("Find the pricing page", read))

    def test_signed_in_app_is_not_a_wall(self) -> None:
        read = {"url": "https://linear.app/acme/team/ACM/active", "text": "Inbox My issues", "nodes": [
            {"role": "button", "name": "New issue"}, {"role": "link", "name": "Inbox"}]}
        self.assertIsNone(account_wall("Create an issue", read))


class SignedInGoal(unittest.TestCase):
    def test_docs_page_is_not_done_when_signed_in(self) -> None:
        read = {"url": "https://linear.app/docs/creating-issues", "text": "Creating issues", "signed_in": True}
        self.assertFalse(goal_visible("Create an issue", read))

    def test_issue_page_is_done_when_signed_in(self) -> None:
        read = {"url": "https://linear.app/acme/issue/ACM-5/signup-smoke", "text": "", "signed_in": True}
        self.assertTrue(goal_visible("Create an issue", read))


class SignupHelpers(unittest.TestCase):
    def test_oauth_buttons_hidden(self) -> None:
        snap = {"elements": [
            {"i": 0, "role": "button", "name": "Continue with Google"},
            {"i": 1, "role": "button", "name": "Continue with email"},
            {"i": 2, "role": "button", "name": "Sign up with Microsoft"},
            {"i": 3, "role": "textbox", "name": "Email"},
        ]}
        names = [e["name"] for e in _visible_elements(snap)]
        self.assertEqual(names, ["Continue with email", "Email"])
        self.assertTrue(_OAUTH.search("SAML SSO"))

    def test_rank_links_prefers_verify(self) -> None:
        links = ["https://linear.app", "https://twitter.com/linear",
                 "https://linear.app/auth/email/x@y.com/abcdefghijklmnop"]
        self.assertEqual(rank_links(links, "linear.app")[0], links[2])


if __name__ == "__main__":
    unittest.main()
