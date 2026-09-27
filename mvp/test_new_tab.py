"""A link that opens a new tab (target=_blank) is followed in the agent's tab."""

from __future__ import annotations

import asyncio
import unittest

from mvp.a11y_agent import _follow_new_tab, _new_tab_wait_ms, _open_tabs


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

    async def wait_for_url(self, pred, timeout=0):
        # A new tab commits its first response a beat after it opens.
        for _ in range(int(timeout / 50) or 1):
            if pred(self.url):
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("url never committed")


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


class LateNewTabTest(unittest.TestCase):
    """kolanut.ai: "Get Started" is <a target=_blank href=engagement.kolanut.ai/signup>.

    On Browserbase the new tab shows up (and gets its URL) only after its first
    response commits, after the loop had already looked; the step was logged
    as "click Get Started changed nothing on kolanut.ai".
    """

    def test_tab_that_opens_late_is_followed(self):
        async def run():
            ctx = _Ctx()
            page = _Tab(ctx, "https://www.kolanut.ai/")
            before = _open_tabs(page)

            async def open_later():
                await asyncio.sleep(0.6)
                _Tab(ctx, "https://engagement.kolanut.ai/signup")

            opener = asyncio.ensure_future(open_later())
            self.assertEqual(await _follow_new_tab(page, before), "")  # old behaviour: looked too early
            got = await _follow_new_tab(page, before, wait_ms=3000)
            await opener
            return page, ctx, got

        page, ctx, got = asyncio.run(run())
        self.assertEqual(got, "https://engagement.kolanut.ai/signup")
        self.assertEqual(page.url, "https://engagement.kolanut.ai/signup")
        self.assertEqual(ctx.pages, [page])

    def test_tab_still_on_about_blank_waits_for_its_url(self):
        async def run():
            ctx = _Ctx()
            page = _Tab(ctx, "https://www.kolanut.ai/")
            before = _open_tabs(page)
            popup = _Tab(ctx, "about:blank")

            async def commit():
                await asyncio.sleep(0.4)
                popup.url = "https://engagement.kolanut.ai/signup"

            committer = asyncio.ensure_future(commit())
            got = await _follow_new_tab(page, before)
            await committer
            return page, popup, got

        page, popup, got = asyncio.run(run())
        self.assertEqual(got, "https://engagement.kolanut.ai/signup")
        self.assertEqual(page.url, "https://engagement.kolanut.ai/signup")
        self.assertTrue(popup.closed)

    def test_wait_is_long_only_for_links_that_leave_the_page(self):
        here = "https://www.kolanut.ai/"
        self.assertEqual(_new_tab_wait_ms({"href": "https://engagement.kolanut.ai/signup"}, here), 4000)
        # A <button> inside <a target=_blank>: the tree has no href, the live DOM does.
        self.assertEqual(
            _new_tab_wait_ms({"_live_href": "https://engagement.kolanut.ai/signup", "_live_target": "_blank"}, here), 5000
        )
        self.assertEqual(_new_tab_wait_ms({"name": "Open menu"}, here), 1000)
        self.assertEqual(_new_tab_wait_ms({"href": "https://www.kolanut.ai/#features"}, here), 1000)


if __name__ == "__main__":
    unittest.main()
