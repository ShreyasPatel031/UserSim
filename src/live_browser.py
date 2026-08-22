"""Playwright helpers: extract interactive candidates and execute actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


INTERACTIVE = (
    "a[href], button, input, textarea, select, "
    "[role='button'], [role='link'], [role='textbox'], [role='combobox'], "
    "[role='menuitem'], [role='tab'], [role='checkbox'], [role='radio'], "
    "[contenteditable='true'], [onclick]"
)


@dataclass
class Candidate:
    index: int  # 1-based
    tag: str
    text: str
    role: str
    name: str
    placeholder: str
    input_type: str
    href: str
    selector: str
    bbox: dict[str, float] | None

    def repr(self, max_len: int = 220) -> str:
        parts = [f"<{self.tag}>"]
        if self.role:
            parts.append(f"role={self.role}")
        if self.input_type:
            parts.append(f"type={self.input_type}")
        if self.name:
            parts.append(f"name={self.name[:80]}")
        if self.placeholder:
            parts.append(f"placeholder={self.placeholder[:80]}")
        if self.href:
            parts.append(f"href={self.href[:80]}")
        if self.text:
            parts.append(f"text={self.text[:100]}")
        return " ".join(parts)[:max_len]


def _clean(s: str | None, n: int = 120) -> str:
    if not s:
        return ""
    return " ".join(str(s).split())[:n]


def extract_candidates(page: Page, max_n: int = 50) -> list[Candidate]:
    """Visible interactive elements, top-left ordered, capped at max_n."""
    raw = None
    last_err: Exception | None = None
    for _ in range(3):
        try:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(300)
            raw = page.evaluate(
                """(sel) => {
          const nodes = Array.from(document.querySelectorAll(sel));
          const out = [];
          for (const el of nodes) {
            const r = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (r.width < 2 || r.height < 2) continue;
            if (style.visibility === 'hidden' || style.display === 'none') continue;
            if (style.opacity === '0') continue;
            if (r.bottom < 0 || r.right < 0 || r.top > window.innerHeight * 2) continue;
            const text = (el.innerText || el.value || el.getAttribute('aria-label') ||
                          el.getAttribute('title') || el.getAttribute('alt') || '').trim();
            const tag = el.tagName.toLowerCase();
            out.push({
              tag,
              text: text.slice(0, 160),
              role: el.getAttribute('role') || '',
              name: el.getAttribute('name') || el.getAttribute('aria-label') || '',
              placeholder: el.getAttribute('placeholder') || '',
              input_type: (el.getAttribute('type') || '').toLowerCase(),
              href: (el.getAttribute('href') || '').slice(0, 200),
              x: r.x, y: r.y, w: r.width, h: r.height,
            });
          }
          out.sort((a, b) => (a.y - b.y) || (a.x - b.x));
          return out;
        }""",
                INTERACTIVE,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            page.wait_for_timeout(800)
    if raw is None:
        raise RuntimeError(f"extract_candidates failed: {last_err}")

    cands: list[Candidate] = []
    for i, item in enumerate(raw[:max_n], start=1):
        # Prefer bounding-box click; also keep a rough CSS path via nth-match of tag+text
        tag = item["tag"]
        text = _clean(item.get("text"))
        # Unique-ish selector using position in filtered list
        selector = f"__bbox__:{item['x']:.1f}:{item['y']:.1f}:{item['w']:.1f}:{item['h']:.1f}"
        cands.append(
            Candidate(
                index=i,
                tag=tag,
                text=text,
                role=_clean(item.get("role"), 40),
                name=_clean(item.get("name"), 80),
                placeholder=_clean(item.get("placeholder"), 80),
                input_type=_clean(item.get("input_type"), 20),
                href=_clean(item.get("href"), 80),
                selector=selector,
                bbox={
                    "x": float(item["x"]),
                    "y": float(item["y"]),
                    "w": float(item["w"]),
                    "h": float(item["h"]),
                },
            )
        )
    return cands


def _click_bbox(page: Page, bbox: dict[str, float]) -> None:
    x = bbox["x"] + bbox["w"] / 2
    y = bbox["y"] + bbox["h"] / 2
    page.mouse.click(x, y)


def execute_action(
    page: Page,
    cand: Candidate | None,
    action: str,
    value: str | None,
    timeout_ms: int = 8000,
) -> dict[str, Any]:
    """Execute CLICK/TYPE/SELECT/STOP. Returns status dict."""
    action = (action or "").upper()
    if action == "STOP" or cand is None:
        return {"ok": True, "action": "STOP"}
    try:
        page.set_default_timeout(timeout_ms)
        if action == "CLICK":
            _click_bbox(page, cand.bbox or {"x": 0, "y": 0, "w": 1, "h": 1})
        elif action == "TYPE":
            _click_bbox(page, cand.bbox or {"x": 0, "y": 0, "w": 1, "h": 1})
            page.keyboard.press("Control+A")
            page.keyboard.type(value or "", delay=20)
        elif action == "SELECT":
            # Best-effort: click then type option text / press Enter
            _click_bbox(page, cand.bbox or {"x": 0, "y": 0, "w": 1, "h": 1})
            if value:
                page.keyboard.type(value, delay=20)
                page.keyboard.press("Enter")
        else:
            return {"ok": False, "error": f"unknown action {action}"}
        page.wait_for_timeout(800)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except PlaywrightTimeout:
            pass
        return {"ok": True, "action": action, "value": value}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300], "action": action}


def dismiss_cookies(page: Page) -> None:
    """Best-effort cookie/consent dismissal."""
    labels = [
        "Accept all",
        "Accept All",
        "Accept",
        "I Agree",
        "Got it",
        "OK",
        "Allow all",
        "Allow All",
        "Agree",
        "Close",
    ]
    for label in labels:
        try:
            loc = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I))
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                page.wait_for_timeout(400)
                return
        except Exception:  # noqa: BLE001
            continue
