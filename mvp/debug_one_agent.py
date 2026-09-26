"""Single agent, single task debug run with per-step capture.

  python -m mvp.debug_one_agent https://kolanut.ai "Identify at-risk customer accounts" [--local] [--headed]

Default browser is ONE Browserbase session (same flags as the study run);
--local uses local Chrome (headless unless --headed). Per step it saves: the
action chosen, the URLs of every open tab before and after the action, the
accessibility tree size, and a screenshot, to
/workspace/logs/kolanut_debug/<stamp>/ (MVP_DEBUG_OUT overrides the root).
Signup on the wall uses the same signup_and_resume the study uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _tabs(page: Any) -> list[str]:
    try:
        return [str(p.url) for p in page.context.pages]
    except Exception:
        return []

_FIXED_DUMP_JS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 100) continue;
    const kids = [];
    for (const k of el.querySelectorAll('*')) {
      const kc = getComputedStyle(k); const kr = k.getBoundingClientRect();
      if (kr.width < 4 || kr.height < 4) continue;
      const clicky = kc.cursor === 'pointer' || /^(A|BUTTON|INPUT|SELECT)$/.test(k.tagName) || k.getAttribute('role') || k.onclick;
      if (!clicky) continue;
      kids.push({tag: k.tagName, role: k.getAttribute('role'), aria: k.getAttribute('aria-label'), title: k.getAttribute('title'),
                 cls: (k.className && k.className.baseVal !== undefined ? k.className.baseVal : k.className || '').slice(0, 80),
                 text: (k.innerText || '').trim().slice(0, 50), x: Math.round(kr.x), y: Math.round(kr.y), w: Math.round(kr.width), h: Math.round(kr.height)});
      if (kids.length > 40) break;
    }
    out.push({tag: el.tagName, role: el.getAttribute('role'), aria_modal: el.getAttribute('aria-modal'), cls: String(el.className).slice(0, 100),
              z: cs.zIndex, box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)], kids});
  }
  return out;
}"""


async def _flow(page: Any, url: str, task: str, out: Path, persona: dict) -> dict:
    from mvp import a11y_agent as A

    steps: list[dict] = []
    events: list[str] = []
    shot_no = [0]

    async def shot(tag: str) -> str:
        shot_no[0] += 1
        p = out / f"{shot_no[0]:03d}-{tag}.png"
        try:
            await page.screenshot(path=str(p), timeout=8000)
        except Exception as exc:  # noqa: BLE001
            return f"screenshot failed: {exc!r}"[:200]
        return str(p)

    try:
        page.context.on("page", lambda pg: events.append(f"{time.strftime('%H:%M:%S')} new tab opened url={pg.url}"))
    except Exception:
        pass

    real_act = A._act

    async def traced_act(pg: Any, action: dict) -> str:
        rec: dict[str, Any] = {
            "act": action.get("act"), "name": action.get("name"), "role": action.get("role"),
            "href": action.get("href"), "x": action.get("x"), "y": action.get("y"),
            "tabs_before": _tabs(pg), "t": time.strftime("%H:%M:%S"),
        }
        rec["shot_before"] = await shot("before")
        how = ""
        try:
            how = await real_act(pg, action)
            return how
        finally:
            rec["how"] = how
            # No extra wait by default: a sleep here hides timing bugs (a new
            # tab that opens late). MVP_DEBUG_ACT_SLEEP_S adds one on purpose.
            await asyncio.sleep(float(os.environ.get("MVP_DEBUG_ACT_SLEEP_S", "0") or 0))
            rec["tabs_right_after_act"] = _tabs(pg)
            rec["page_url_after"] = str(pg.url)
            steps.append(rec)
            print(f"[debug] act={rec['act']} name={rec['name']!r} role={rec['role']} href={rec['href']} how={how} "
                  f"tabs {rec['tabs_before']} -> {rec['tabs_right_after_act']}", flush=True)

    A._act = traced_act  # type: ignore[assignment]

    real_model = A._model_action
    decisions: list[dict] = []

    async def traced_model(**kw: Any) -> Any:
        got = await real_model(**kw)
        read = kw.get("read") or {}
        decisions.append({
            "t": time.strftime("%H:%M:%S"), "url": read.get("url"), "dialog": read.get("dialog"),
            "nodes_to_model": len(read.get("nodes") or []), "nodes_all": len(kw.get("all_nodes") or []),
            "ax": A.format_ax(read.get("nodes") or []), "history": list(kw.get("history") or [])[-4:],
            "decision": got,
        })
        (out / "decisions.json").write_text(json.dumps(decisions, indent=1, default=str))
        return got

    A._model_action = traced_model  # type: ignore[assignment]

    from mvp import signup_in_session as S

    real_signup = S.signup_in_session
    signup_full: dict[str, Any] = {}

    async def traced_signup(*a: Any, **kw: Any) -> dict:
        res = await real_signup(*a, **kw)
        signup_full.update(res if isinstance(res, dict) else {})
        await shot("signup-end")
        if os.environ.get("MVP_DEBUG_DUMP_DOM"):
            try:
                pg = a[0] if a else kw.get("page")
                await asyncio.sleep(3)
                read = await A._fresh_read(pg, pg.url)
                (out / "post_signup_read.json").write_text(json.dumps(read, indent=1, default=str))
                fixed = await pg.evaluate(_FIXED_DUMP_JS)
                (out / "post_signup_fixed.json").write_text(json.dumps(fixed, indent=1, default=str))
                print(f"[debug] dumped post-signup read + {len(fixed)} fixed layers", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[debug] dom dump failed: {exc!r}", flush=True)
        (out / "signup.json").write_text(json.dumps(signup_full, indent=1, default=str))
        return res

    S.signup_in_session = traced_signup  # type: ignore[assignment]

    rows: list[dict] = []

    async def on_step(row: dict) -> None:
        if "changed" not in row or row.get("decision_source") == "signup":
            return
        rec = steps[-1] if steps else {}
        rec.update({
            "step": row.get("step"), "action": row.get("action"), "changed": row.get("changed"),
            "url_after_read": row.get("url"), "tabs_after_step": _tabs(page),
            "ax_nodes_after": len(str(row.get("accessibility_tree") or "").splitlines()),
            "thought": row.get("thought"),
        })
        rec["shot_after"] = await shot(f"after-step{row.get('step')}")
        rows.append(rec)
        print(f"[debug] step {row.get('step')} {row.get('action')!r} changed={row.get('changed')} url={row.get('url')} "
              f"ax_lines={rec['ax_nodes_after']}", flush=True)
        (out / "steps.json").write_text(json.dumps(steps, indent=1, default=str))

    t0 = time.monotonic()
    deadline = t0 + float(os.environ.get("MVP_DEBUG_BUDGET_S", "600"))
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2500)
    await shot("opened")
    first = await A.complete_task_on_page(page, task=task, url=url, deadline=deadline, agent_id="debug", on_step=on_step)
    print(f"[debug] first stop={first.get('stop_reason')} signup_url={first.get('signup_url')}", flush=True)
    su = None
    outcome = first
    if first.get("stop_reason") == "needs_account":
        su, outcome = await A.signup_and_resume(
            page, task=task, url=url, persona=persona, outcome=first, deadline=deadline, agent_id="debug",
            on_step=on_step,
        )
        print(f"[debug] signup ok={(su or {}).get('ok')} reason={(su or {}).get('reason')} final={(su or {}).get('final_url')}", flush=True)
    await shot("final")
    (out / "steps.json").write_text(json.dumps(steps, indent=1, default=str))
    A._act = real_act  # type: ignore[assignment]
    A._model_action = real_model  # type: ignore[assignment]
    S.signup_in_session = real_signup  # type: ignore[assignment]
    return {
        "site": url, "task": task, "first_stop": first.get("stop_reason"), "signup_url": first.get("signup_url"),
        "signup": {k: signup_full.get(k) for k in ("ok", "reason", "email", "inbox", "elapsed_s", "final_url", "evidence")},
        "signup_steps": signup_full.get("steps"),
        "signup_last_page": signup_full.get("last_page"),
        "stop_reason": outcome.get("stop_reason"), "final_url": str(page.url), "final_tabs": _tabs(page),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "actions": [f"{r.get('action')} changed={r.get('changed')}" for r in outcome.get("trace") or [] if isinstance(r, dict)],
        "tab_events": events, "steps": steps,
    }


async def main(url: str, task: str, local: bool, headed: bool) -> dict:
    host = (urlparse(url).hostname or "site").removeprefix("www.")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    root = Path(os.environ.get("MVP_DEBUG_OUT", f"/workspace/logs/{host.split('.')[0]}_debug"))
    out = root / stamp
    out.mkdir(parents=True, exist_ok=True)
    persona = {"name": "Sam Rivera"}
    if local:
        from patchright.async_api import async_playwright

        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                tempfile.mkdtemp(prefix="dbg-"), channel="chrome", headless=not headed,
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                res = await _flow(page, url, task, out, persona)
            finally:
                await ctx.close()
        res["browser"] = "local chrome"
    else:
        from playwright.async_api import async_playwright

        from capability.browserbase_client import close_session, create_session

        bb = await asyncio.to_thread(
            lambda: create_session(proxies=False, keep_alive=False, solve_captchas=False,
                                   advanced_stealth=False, owner="signup")
        )
        print(f"[debug] browserbase session {bb.id}", flush=True)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(bb.connect_url)
                try:
                    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                    await page.set_viewport_size({"width": 1440, "height": 900})
                    res = await _flow(page, url, task, out, persona)
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        finally:
            await asyncio.to_thread(close_session, bb.id)
            print(f"[debug] session {bb.id} released", flush=True)
        res["browser"] = f"browserbase {bb.id}"
    (out / "result.json").write_text(json.dumps(res, indent=1, default=str))
    print(f"[debug] saved {out}/result.json", flush=True)
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    r = asyncio.run(main(args[0], args[1], "--local" in sys.argv, "--headed" in sys.argv))
    print(json.dumps({k: v for k, v in r.items() if k not in ("signup_steps", "steps")}, indent=1, default=str))
