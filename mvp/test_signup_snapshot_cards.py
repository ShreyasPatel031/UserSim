"""Signup page read lists <div onClick> choice cards (real Chrome; skipped without it).

kolanut.ai onboarding step 3 ("What do you want to improve first?") is a grid
of clickable divs; Next stays disabled until one is picked. The read listed
only Back and Next, the model kept inventing element numbers, and signup ended
"stuck" on engagement.kolanut.ai/onboarding.
"""

from __future__ import annotations

import asyncio
import unittest

from mvp.signup_in_session import _SNAPSHOT_JS, _do, _fmt_elements

HTML = """<html><body><h1>What do you want to improve first?</h1>
<div style="display:grid">
 <div style="cursor:pointer" onclick="document.getElementById('n').disabled=false">
   <h3>Onboarding &amp; activation</h3><p>Get new users to their first win faster</p></div>
 <div style="cursor:pointer" onclick="document.getElementById('n').disabled=false">
   <h3>Retention &amp; saves</h3><p>Spot at-risk accounts and win them back</p></div>
</div><button>Back</button><button id="n" disabled>Next</button></body></html>"""


async def _run():
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            snap = await page.evaluate(_SNAPSHOT_JS)
            els = {e["i"]: e for e in snap["elements"]}
            cards = [e for e in snap["elements"] if e["role"] == "clickable"]
            done = await _do(page, {"do": "click", "i": cards[0]["i"]}, {}, els) if cards else ""
            return snap, cards, done, await page.locator("#n").is_disabled()
        finally:
            await browser.close()


class ChoiceCardTest(unittest.TestCase):
    def test_cards_are_listed_once_and_clickable(self) -> None:
        try:
            snap, cards, done, disabled = asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no local Chrome: {exc!r}"[:120])
        text = _fmt_elements(snap["elements"])
        self.assertEqual([c["name"][:24] for c in cards], ["Onboarding & activation ", "Retention & saves Spot a"])
        self.assertNotIn('clickable "Onboarding & activation"\n', text)  # inner <h3> not listed again
        self.assertTrue(done.startswith("click clickable"))
        self.assertFalse(disabled)


if __name__ == "__main__":
    unittest.main()
