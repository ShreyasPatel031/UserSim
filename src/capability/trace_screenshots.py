"""Save per-step bbox screenshots for capability traces (replay + live runs)."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from capability import VIEWPORT

INTERACTIVE_JS = """
() => {
  const sel = 'a, button, input, select, textarea, [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])';
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(sel)) {
    if (seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (r.bottom < 0 || r.top > window.innerHeight) continue;
    if (r.right < 0 || r.left > window.innerWidth) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    out.push({
      x: r.x, y: r.y, w: r.width, h: r.height,
      tag: (el.tagName || '').toLowerCase(),
    });
  }
  return out.slice(0, 120);
}
"""


@dataclass
class ReplayAction:
    kind: str
    url: str | None = None
    ax_name: str | None = None
    href: str | None = None
    xpath: str | None = None
    click_x: float | None = None
    click_y: float | None = None
    click_w: float | None = None
    click_h: float | None = None


def screenshots_dir(trace_dir: Path) -> Path:
    d = trace_dir / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_bbox_png(trace_dir: Path, step: int, png_bytes: bytes) -> Path:
    path = screenshots_dir(trace_dir) / f"bbox_{step}.png"
    path.write_bytes(png_bytes)
    return path


def save_step_png(trace_dir: Path, step: int, png_bytes: bytes) -> Path:
    path = screenshots_dir(trace_dir) / f"step_{step}.png"
    path.write_bytes(png_bytes)
    return path


def save_bbox_from_base64(trace_dir: Path, step: int, b64: str) -> Path | None:
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    return save_bbox_png(trace_dir, step, raw)


def draw_bbox_overlay(
    screenshot_bytes: bytes,
    boxes: list[dict[str, Any]],
    *,
    highlight: tuple[float, float, float, float] | None = None,
) -> bytes:
    image = Image.open(io.BytesIO(screenshot_bytes)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = _load_font(11)
    colors = {
        "a": "#96CEB4",
        "button": "#FF6B6B",
        "input": "#4ECDC4",
        "select": "#45B7D1",
        "textarea": "#FF8C42",
    }
    for i, box in enumerate(boxes, start=1):
        x, y, w, h = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
        tag = str(box.get("tag") or "default")
        color = colors.get(tag, "#DDA0DD")
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
        label = str(i)
        tw, th = draw.textbbox((0, 0), label, font=font)[2:]
        label_y = max(0, y - th - 2)
        label_bottom = max(label_y + th + 2, label_y + 1)
        draw.rectangle([x, label_y, x + tw + 4, label_bottom], fill=color)
        draw.text((x + 2, label_y), label, fill="#111", font=font)
    if highlight:
        hx, hy, hw, hh = highlight
        draw.rectangle([hx, hy, hx + hw, hy + hh], outline="#FF0000", width=4)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def parse_replay_actions(history_text: str) -> list[ReplayAction]:
    """Parse navigate/click steps from browser-use history.txt."""
    actions: list[ReplayAction] = []
    click_meta = re.findall(r"metadata=\{'click_x': ([\d.]+), 'click_y': ([\d.]+)\}", history_text)
    click_idx = 0

    for m in re.finditer(
        r"\{'(navigate|click|done|input|wait|scroll)': \{([^}]*)\}(?:, 'interacted_element': (?:None|DOMInteractedElement\(([^)]*)\)))?",
        history_text,
    ):
        kind = m.group(1)
        if kind == "done":
            continue
        body = m.group(2) or ""
        interacted = m.group(3) or ""
        act = ReplayAction(kind=kind)
        url_m = re.search(r"'url': '([^']+)'", body)
        if url_m:
            act.url = url_m.group(1)
        if kind == "click":
            ax = re.search(r"ax_name='([^']*)'", interacted)
            href = re.search(r"'href': '([^']*)'", interacted)
            xpath = re.search(r"x_path='([^']*)'", interacted)
            bounds = re.search(
                r"bounds=DOMRect\(x=([\d.]+), y=([\d.]+), width=([\d.]+), height=([\d.]+)\)",
                interacted,
            )
            if ax:
                act.ax_name = ax.group(1)
            if href:
                act.href = href.group(1)
            if xpath:
                act.xpath = xpath.group(1)
            if bounds:
                act.click_x = float(bounds.group(1))
                act.click_y = float(bounds.group(2))
                act.click_w = float(bounds.group(3))
                act.click_h = float(bounds.group(4))
            elif click_idx < len(click_meta):
                act.click_x = float(click_meta[click_idx][0])
                act.click_y = float(click_meta[click_idx][1])
            click_idx += 1
        actions.append(act)
    return actions


async def wait_for_dashboard(page: Any, timeout_ms: int = 45000) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    try:
        await page.wait_for_function(
            "() => document.body && document.body.innerText.trim().length > 80",
            timeout=15000,
        )
    except Exception:
        pass


async def capture_step_screenshots(page: Any, trace_dir: Path, step: int, highlight: ReplayAction | None) -> None:
    plain = await page.screenshot(type="png", full_page=False)
    save_step_png(trace_dir, step, plain)
    boxes = await page.evaluate(INTERACTIVE_JS)
    hl = None
    if highlight and highlight.click_x is not None and highlight.click_y is not None:
        bw = highlight.click_w or 32.0
        bh = highlight.click_h or 32.0
        hl = (highlight.click_x, highlight.click_y, bw, bh)
    bbox = draw_bbox_overlay(plain, boxes, highlight=hl)
    save_bbox_png(trace_dir, step, bbox)


async def replay_click(page: Any, action: ReplayAction) -> bool:
    if action.href:
        loc = page.locator(f'a[href="{action.href}"]')
        if await loc.count():
            await loc.first.click(timeout=10000)
            return True
    if action.ax_name:
        loc = page.get_by_role("link", name=action.ax_name, exact=False)
        if await loc.count():
            await loc.first.click(timeout=10000)
            return True
        loc = page.get_by_text(action.ax_name, exact=False)
        if await loc.count():
            await loc.first.click(timeout=10000)
            return True
    if action.xpath:
        loc = page.locator(f"xpath={action.xpath}")
        if await loc.count():
            await loc.first.click(timeout=10000)
            return True
    if action.click_x is not None and action.click_y is not None:
        await page.mouse.click(action.click_x, action.click_y)
        return True
    return False


async def replay_trace_screenshots(
    trace_dir: Path,
    *,
    storage_state: dict | None,
    start_url: str,
    viewport: dict = VIEWPORT,
) -> int:
    """Replay history actions with Playwright; write screenshots/bbox_N.png. Returns step count."""
    from playwright.async_api import async_playwright

    hist_path = trace_dir / "history.txt"
    if not hist_path.is_file():
        return 0
    actions = parse_replay_actions(hist_path.read_text(errors="replace"))
    if not actions:
        return 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx_kw: dict = {"viewport": viewport}
        if storage_state:
            ctx_kw["storage_state"] = storage_state
        context = await browser.new_context(**ctx_kw)
        page = await context.new_page()

        first_url = start_url
        for a in actions:
            if a.kind == "navigate" and a.url:
                first_url = a.url
                break
        await page.goto(first_url, wait_until="domcontentloaded", timeout=45000)
        await wait_for_dashboard(page)

        step = 1
        await capture_step_screenshots(page, trace_dir, step, None)

        for action in actions:
            if action.kind == "navigate" and action.url:
                norm = action.url.rstrip("/")
                if norm and norm != page.url.rstrip("/"):
                    await page.goto(action.url, wait_until="domcontentloaded", timeout=45000)
                    await wait_for_dashboard(page)
            elif action.kind == "click":
                step += 1
                await capture_step_screenshots(page, trace_dir, step, action)
                clicked = await replay_click(page, action)
                if clicked:
                    await wait_for_dashboard(page)

        step += 1
        await capture_step_screenshots(page, trace_dir, step, None)
        last_step = trace_dir / "screenshots" / f"step_{step}.png"
        if last_step.is_file():
            (trace_dir / "final.png").write_bytes(last_step.read_bytes())

        await context.close()
        await browser.close()
    return step
