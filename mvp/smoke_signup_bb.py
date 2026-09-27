"""Smoke-test in-session signups on Browserbase: N parallel agents per site.

    python -m mvp.smoke_signup_bb --out DIR --n 3 --timeout 150 \
        https://www.zo.computer/ https://zapier.com/sign-up https://app.n8n.cloud/register

Each agent opens one Browserbase session (released in ``finally``), runs
``signup_in_session`` with the study's spacing and captcha grace, and writes
its result and final screenshot to DIR. Prints a per-site summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PERSONAS = [
    {"name": "Maya Chen", "occupation": "operations manager"},
    {"name": "Luis Ortega", "occupation": "freelance developer"},
    {"name": "Priya Nair", "occupation": "marketing lead"},
    {"name": "Tom Becker", "occupation": "small business owner"},
    {"name": "Aisha Bello", "occupation": "data analyst"},
    {"name": "Ken Mori", "occupation": "product designer"},
]


async def one(url: str, idx: int, timeout_s: float, out: Path, study_id: str) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    from capability.browserbase_client import close_session, create_session
    from mvp import captcha_spend
    from mvp.a11y_agent import _stagger_signup
    from mvp.signup_in_session import _site, signup_in_session

    site = _site(url)
    captcha_spend.allow_study_host(site)
    name = f"{site.split('.')[0]}_{idx}"
    t0 = time.time()
    res: dict[str, Any] = {"site": site, "agent": name}
    bb = await asyncio.to_thread(
        lambda: create_session(
            proxies=False, keep_alive=False, solve_captchas=False, advanced_stealth=False,
            owner="signup", study_id=study_id,
        )
    )
    res["bb"] = bb.id
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(bb.connect_url)
            try:
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.set_viewport_size({"width": 1440, "height": 900})
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                waited = await _stagger_signup(site)
                r = await signup_in_session(
                    page, url, PERSONAS[idx % len(PERSONAS)], signup_url=url, timeout_s=timeout_s
                )
                res.update(
                    ok=r.get("ok"), reason=r.get("reason"), email=r.get("email"),
                    elapsed_s=r.get("elapsed_s"), final_url=r.get("final_url"),
                    evidence=r.get("evidence"), captcha=r.get("captcha"),
                    capsolver_usd=r.get("capsolver_usd"), steps=r.get("steps"),
                    last_page=r.get("last_page"), spacing_wait_s=round(waited, 1),
                )
                try:
                    await page.screenshot(path=str(out / f"{name}.png"), timeout=15000)
                except Exception as exc:  # noqa: BLE001
                    res["shot_error"] = repr(exc)[:120]
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        res.update(ok=False, reason=f"harness: {exc!r}"[:200])
    finally:
        await asyncio.to_thread(close_session, bb.id)
    res["wall_s"] = round(time.time() - t0, 1)
    (out / f"{name}.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"[smoke] {name}: ok={res.get('ok')} reason={res.get('reason')} {res['wall_s']}s email={res.get('email')}", flush=True)
    return res


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--out", default="/workspace/logs/zo_rerun/smoke")
    args = ap.parse_args()
    from mvp.executor import ensure_default_executor

    ensure_default_executor()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    study_id = "smoke-" + time.strftime("%H%M%S")
    jobs = [one(u, i, args.timeout, out, study_id) for u in args.urls for i in range(args.n)]
    results = await asyncio.gather(*jobs)
    by: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by.setdefault(r["site"], []).append(r)
    for site, rows in by.items():
        ok = sum(1 for r in rows if r.get("ok"))
        print(f"[smoke] {site}: {ok}/{len(rows)} ok; reasons={[r.get('reason') for r in rows]}", flush=True)
    (out / "summary.json").write_text(json.dumps({s: [{k: r.get(k) for k in ('agent', 'ok', 'reason', 'email', 'elapsed_s', 'final_url', 'capsolver_usd')} for r in rows] for s, rows in by.items()}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
