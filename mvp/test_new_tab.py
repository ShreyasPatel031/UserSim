"""A link that opens a new tab (target=_blank) is followed in the agent's tab."""

from __future__ import annotations

import asyncio
import unittest

from mvp.a11y_agent import _follow_new_tab, _open_tabs


class _Tab:
    def __init__(self, ctx, url):
        self.ctx, self.url, self.closed, self.visited = ctx, url, False, []
        ctx.pages.append(self)

    @property
    def context(self):
        return self.ctx

    async def wait_for_load_state(self, *_a, **_kw):
        pass

    async def wait_for_timeout(self, _ms):
        pass

    async def close(self):
        self.closed = True
        self.ctx.pages.remove(self)

    async def goto(self, url, **_kw):
        self.visited.append(url)
        self.url = url


class _Ctx:
    def __init__(self):
        self.pages: list[_Tab] = []


class FollowNewTabTest(unittest.TestCase):
    def test_new_tab_link_opens_in_the_agent_tab(self):
        ctx = _Ctx()
        page = _Tab(ctx, "https://app.example/")
        before = _open_tabs(page)
        popup = _Tab(ctx, "https://plus.app.example/pricing")
        followed = asyncio.run(_follow_new_tab(page, before))
        self.assertEqual(followed, "https://plus.app.example/pricing")
        self.assertEqual(page.url, "https://plus.app.example/pricing")
        self.assertTrue(popup.closed)
        self.assertEqual(ctx.pages, [page])

    def test_no_new_tab_does_nothing(self):
        ctx = _Ctx()
        page = _Tab(ctx, "https://app.example/")
        self.assertEqual(asyncio.run(_follow_new_tab(page, _open_tabs(page))), "")
        self.assertEqual(page.visited, [])

    def test_third_party_sign_in_popup_is_not_followed(self):
        ctx = _Ctx()
        page = _Tab(ctx, "https://app.example/signup")
        before = _open_tabs(page)
        _Tab(ctx, "https://accounts.google.com/o/oauth2/auth?client_id=x")
        self.assertEqual(asyncio.run(_follow_new_tab(page, before)), "")
        self.assertEqual(page.url, "https://app.example/signup")

    def test_a_github_repo_link_is_followed(self):
        ctx = _Ctx()
        page = _Tab(ctx, "https://app.example/")
        before = _open_tabs(page)
        _Tab(ctx, "https://github.com/example/app")
        self.assertEqual(asyncio.run(_follow_new_tab(page, before)), "https://github.com/example/app")


if __name__ == "__main__":
    unittest.main()
