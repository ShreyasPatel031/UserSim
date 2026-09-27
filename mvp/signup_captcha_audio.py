"""Free reCAPTCHA v2 fallback for in-run signup: audio challenge + Gemini transcription.

Used only when a captcha actually blocks the signup form and before any paid
solver. Returns {"ok", "method", "detail"}. Google often refuses the audio
challenge for automated traffic ("Your computer or network may be sending
automated queries"); that is reported as ``audio_refused``.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any


async def _transcribe(audio: bytes, mime: str = "audio/mp3") -> str:
    import httpx

    from auth import vertex_credentials
    from capability.gemini_config import _endpoint, _extract_text

    payload = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}},
            {"text": "Transcribe the spoken English words in this clip exactly. Reply with the words only, lowercase, no punctuation."},
        ]}],
        "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}},
    }
    creds = await asyncio.to_thread(vertex_credentials)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _endpoint("gemini-2.5-flash"),
            headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return _extract_text(resp.json()).strip().lower()


def _frame(page: Any, needle: str) -> Any:
    for fr in page.frames:
        if needle in (fr.url or ""):
            return fr
    return None


async def solve_recaptcha_audio(page: Any, tries: int = 3) -> dict[str, Any]:
    anchor = _frame(page, "recaptcha/api2/anchor") or _frame(page, "recaptcha/enterprise/anchor")
    if anchor is None:
        return {"ok": False, "method": "audio", "detail": "no recaptcha anchor frame"}
    try:
        await anchor.click("#recaptcha-anchor", timeout=5000)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "method": "audio", "detail": f"anchor click: {type(exc).__name__}"}
    await page.wait_for_timeout(2500)

    async def checked() -> bool:
        try:
            return (await anchor.get_attribute("#recaptcha-anchor", "aria-checked", timeout=2000)) == "true"
        except Exception:
            return False

    if await checked():
        return {"ok": True, "method": "checkbox", "detail": "no challenge"}
    for attempt in range(tries):
        bframe = _frame(page, "recaptcha/api2/bframe") or _frame(page, "recaptcha/enterprise/bframe")
        if bframe is None:
            await page.wait_for_timeout(1500)
            continue
        try:
            if await bframe.locator("#recaptcha-audio-button").count() and attempt == 0:
                await bframe.click("#recaptcha-audio-button", timeout=5000)
                await page.wait_for_timeout(2500)
        except Exception:
            pass
        body = ""
        try:
            body = (await bframe.inner_text("body", timeout=3000)).lower()
        except Exception:
            pass
        if "automated queries" in body or "try again later" in body:
            return {"ok": False, "method": "audio_refused", "detail": "Google refused the audio challenge"}
        src = ""
        for sel, attr in (("#audio-source", "src"), (".rc-audiochallenge-tdownload-link", "href")):
            try:
                if await bframe.locator(sel).count():
                    src = await bframe.get_attribute(sel, attr, timeout=3000) or ""
                    if src:
                        break
            except Exception:
                pass
        if not src:
            return {"ok": False, "method": "audio", "detail": "no audio source"}
        try:
            resp = await page.request.get(src, timeout=20000)
            audio = await resp.body()
            text = await _transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "method": "audio", "detail": f"transcribe: {exc!r}"[:160]}
        try:
            await bframe.fill("#audio-response", text, timeout=4000)
            await bframe.click("#recaptcha-verify-button", timeout=4000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "method": "audio", "detail": f"submit: {type(exc).__name__}"}
        await page.wait_for_timeout(3000)
        if await checked():
            return {"ok": True, "method": "gemini_audio", "detail": f"attempt {attempt + 1}"}
        try:
            await bframe.click("#recaptcha-reload-button", timeout=3000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass
    return {"ok": False, "method": "audio", "detail": "transcription not accepted"}
