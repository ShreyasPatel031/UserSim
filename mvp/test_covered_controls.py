"""Controls under a fixed overlay read as inert (real Chrome; skipped without it).

kolanut.ai's product-tour modal (a plain fixed <div>, not role=dialog) covered
the Customers page after signup. The agent kept choosing "Re-engage at-risk"
behind it: every click missed, and the run ended "repeated an action that
changed nothing".
"""

from __future__ import annotations

import asyncio
import unittest

from mvp.a11y_agent import _READ_JS

HTML = """<html><body style="margin:0">
<div style="padding-top:60px"><button>Re-engage at-risk</button><a href="/contacts">Customers</a>
<label><input type=checkbox style="opacity:0;position:absolute"><span>Agree</span></label></div>
<aside style="position:fixed;top:0;left:1300px;width:300px"><button>Re-engage drawer</button></aside>
<div id=ov style="position:fixed;inset:0;background:rgba(0,0,0,.4)"><div style="margin:100px auto;width:400px;background:#fff">
<button aria-label="Close" onclick="document.getElementById('ov').remove()">x</button><a href="/tour">Play video</a></div></div>
</body></html>"""


async def _run():
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.set_content(HTML)
            before = await page.evaluate(_READ_JS)
            await page.click("[aria-label=Close]")
            after = await page.evaluate(_READ_JS)
            return before, after
        finally:
            await browser.close()


class CoveredControlTest(unittest.TestCase):
    def test_overlay_marks_background_inert_until_closed(self) -> None:
        try:
            before, after = asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no local Chrome: {exc!r}"[:120])
        inert = {n["name"]: n["inert"] for n in before["nodes"]}
        self.assertTrue(inert["Re-engage at-risk"])
        self.assertTrue(inert["Customers"])
        self.assertFalse(inert["Close"])
        self.assertFalse(inert["Play video"])
        self.assertFalse(inert["checkbox field"])  # styled checkbox under its label stays usable
        self.assertFalse(any(n["inert"] for n in after["nodes"]))
        # A drawer slid off the right edge is not offered at all.
        self.assertNotIn("Re-engage drawer", {n["name"] for n in before["nodes"] + after["nodes"]})


if __name__ == "__main__":
    unittest.main()
