"""Capture real browser frames for a task (land + one interaction).

Used when Browserbase is unavailable. Runs local Playwright in parallel across
tasks. On serverless hosts without Chromium, falls back to a remote landing
screenshot so the UI is never blank text-only.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

OnFrame = Callable[[dict[str, Any]], Awaitable[None] | None]


async def _emit(on_frame: OnFrame | None, frame: dict[str, Any]) -> None:
    if not on_frame or not frame.get("screenshot_url"):
        return
    maybe = on_frame(frame)
    if maybe is not None and hasattr(maybe, "__await__"):
        await maybe


async def _remote_landing_shot(url: str) -> str | None:
    """Best-effort public screenshot service → data URL."""
    endpoints = [
        f"https://image.thum.io/get/width/1440/crop/900/noanimate/{url}",
        f"https://api.microlink.io/?url={url}&screenshot=true&meta=false&embed=screenshot.url",
    ]
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        # thum.io returns image bytes directly
        try:
            resp = await client.get(endpoints[0])
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                b64 = base64.b64encode(resp.content).decode("ascii")
                ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                return f"data:{ctype};base64,{b64}"
        except Exception:
            pass
        # microlink returns JSON with screenshot URL
        try:
            resp = await client.get(endpoints[1])
            if resp.status_code == 200:
                data = resp.json()
                shot = ((data.get("data") or {}).get("screenshot") or {}).get("url")
                if shot:
                    img = await client.get(shot)
                    if img.status_code == 200:
                        b64 = base64.b64encode(img.content).decode("ascii")
                        ctype = img.headers.get("content-type", "image/png").split(";")[0]
                        return f"data:{ctype};base64,{b64}"
        except Exception:
            pass
    return None


async def capture_task_evidence(
    *,
    url: str,
    task_prompt: str,
    on_frame: OnFrame | None = None,
) -> dict[str, Any]:
    """Return frames with data-URL screenshots + page text for feedback."""
    try:
        return await _playwright_evidence(url=url, task_prompt=task_prompt, on_frame=on_frame)
    except Exception as exc:  # noqa: BLE001
        shot = await _remote_landing_shot(url)
        frame = {
            "step": 1,
            "action": "Landing screenshot (remote capture — live browser unavailable)",
            "observation": url,
            "screenshot_url": shot,
            "boxes": [],
            "outcome": "neutral",
        }
        await _emit(on_frame, frame)
        return {
            "url": url,
            "title": "",
            "body_text": "",
            "links": [],
            "frames": [frame] if shot else [],
            "screenshot_url": shot,
            "backend": "remote_screenshot",
            "error": str(exc)[:240],
        }


async def _playwright_evidence(
    *,
    url: str,
    task_prompt: str,
    on_frame: OnFrame | None = None,
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    frames: list[dict[str, Any]] = []

    async def paint_boxes(page, highlight_index=None):
        return await page.evaluate(
            """(hl) => {
      document.querySelectorAll('[data-usersim-box]').forEach(n => n.remove());
      const sels = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]';
      const els = Array.from(document.querySelectorAll(sels));
      const items = [];
      let i = 0;
      for (const el of els) {
        const r = el.getBoundingClientRect();
        if (r.width < 10 || r.height < 10) continue;
        if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        i += 1;
        if (i > 36) break;
        const label = ((el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name') || el.tagName) + '').trim().slice(0, 80);
        items.push({index: i, label, tag: el.tagName.toLowerCase(), href: el.href || null});
        const box = document.createElement('div');
        box.setAttribute('data-usersim-box', '1');
        const isHl = hl != null && Number(hl) === i;
        box.style.cssText = [
          'position:fixed',
          `left:${r.left}px`,
          `top:${r.top}px`,
          `width:${r.width}px`,
          `height:${r.height}px`,
          `border:${isHl ? 3 : 2}px solid ${isHl ? '#16a34a' : '#ef4444'}`,
          'box-sizing:border-box',
          'z-index:2147483646',
          'pointer-events:none',
          `background:${isHl ? 'rgba(22,163,74,.18)' : 'rgba(239,68,68,.06)'}`,
        ].join(';');
        const badge = document.createElement('div');
        badge.textContent = String(i);
        badge.style.cssText = [
          'position:absolute','top:-2px','left:-2px',
          `background:${isHl ? '#16a34a' : '#ef4444'}`,'color:#fff',
          'font:700 11px/14px ui-sans-serif,system-ui,sans-serif',
          'padding:1px 5px','border-radius:2px',
        ].join(';');
        box.appendChild(badge);
        document.documentElement.appendChild(box);
      }
      return items;
    }""",
            highlight_index,
        )

    async def shot(page) -> str:
        raw = await page.screenshot(type="jpeg", quality=62, full_page=False)
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")

    async def try_act(page, items):
        words = [w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", task_prompt or "")][:8]
        for item in items:
            if item.get("tag") in ("input", "textarea"):
                lab = (item.get("label") or "").lower()
                if any(k in lab for k in ("search", "query", "find", "ask", "type")) or item.get("tag") == "input":
                    try:
                        await page.evaluate(
                            """(idx) => {
                          const els = Array.from(document.querySelectorAll('a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]'));
                          let i = 0;
                          for (const el of els) {
                            const r = el.getBoundingClientRect();
                            if (r.width < 10 || r.height < 10) continue;
                            if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
                            i += 1;
                            if (i === idx) { el.setAttribute('data-usersim-target', String(idx)); el.focus(); }
                          }
                        }""",
                            item["index"],
                        )
                        target = page.locator(f"[data-usersim-target='{item['index']}']").first
                        await target.click(timeout=2500)
                        await target.fill(" ".join(words[:4]) or "demo", timeout=2500)
                        await page.keyboard.press("Enter")
                        return item["index"], f"Typed into box {item['index']} ({item.get('label') or 'input'})"
                    except Exception:
                        pass
        for item in items:
            lab = (item.get("label") or "").lower()
            if words and any(w in lab for w in words):
                try:
                    await page.evaluate(
                        """(idx) => {
                          const els = Array.from(document.querySelectorAll('a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]'));
                          let i = 0;
                          for (const el of els) {
                            const r = el.getBoundingClientRect();
                            if (r.width < 10 || r.height < 10) continue;
                            if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
                            i += 1;
                            if (i === idx) el.click();
                          }
                        }""",
                        item["index"],
                    )
                    return item["index"], f"Clicked box {item['index']} ({item.get('label') or item.get('tag')})"
                except Exception:
                    continue
        for item in items[:8]:
            if item.get("tag") in ("a", "button") or item.get("href"):
                try:
                    await page.evaluate(
                        """(idx) => {
                          const els = Array.from(document.querySelectorAll('a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]'));
                          let i = 0;
                          for (const el of els) {
                            const r = el.getBoundingClientRect();
                            if (r.width < 10 || r.height < 10) continue;
                            if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
                            i += 1;
                            if (i === idx) el.click();
                          }
                        }""",
                        item["index"],
                    )
                    return item["index"], f"Clicked box {item['index']} ({item.get('label') or item.get('tag')})"
                except Exception:
                    continue
        return None, "No safe click target found"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=os.environ.get("MVP_BROWSER_HEADLESS", "0").lower()
            in {"1", "true", "yes"},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(1800)
            items = await paint_boxes(page)
            land = {
                "step": 1,
                "action": "Landed on page — red numbered boxes = clickable elements",
                "observation": (await page.title()) or page.url,
                "screenshot_url": await shot(page),
                "boxes": items,
                "outcome": "easy",
            }
            frames.append(land)
            await _emit(on_frame, land)

            clicked, action = await try_act(page, items)
            await page.wait_for_timeout(2000)
            items2 = await paint_boxes(page, clicked)
            act = {
                "step": 2,
                "action": action + (" — green box = last interaction" if clicked else ""),
                "observation": page.url,
                "screenshot_url": await shot(page),
                "boxes": items2,
                "highlight_index": clicked,
                "outcome": "easy" if clicked else "neutral",
            }
            frames.append(act)
            await _emit(on_frame, act)

            body = (await page.locator("body").inner_text())[:12000]
            links = await page.locator("a[href]").evaluate_all(
                "els => els.slice(0, 60).map(a => ({text: (a.innerText || '').trim().slice(0, 160), href: a.href}))"
            )
            return {
                "url": page.url,
                "title": await page.title(),
                "body_text": body,
                "links": links,
                "frames": frames,
                "screenshot_url": frames[-1]["screenshot_url"],
                "backend": "playwright",
            }
        finally:
            await browser.close()
