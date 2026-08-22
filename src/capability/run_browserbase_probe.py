"""Try Browserbase + Browser Use configs on uniqlo until one gets past step 1."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser_use import Agent, ChatOpenAI

from capability import CAPABLE_AGENT_PREAMBLE, MAX_ACTIONS, OUT_DIR, USER_AGENT, VIEWPORT
from capability.browser_use_runner import _history_to_actions
from capability.browserbase_client import close_session, create_session
from capability.mistral_config import MISTRAL_API_BASE, mistral_api_key
from capability.tasks import load_tasks


@dataclass(frozen=True)
class Variant:
    name: str
    preflight: bool = False
    use_vision: bool = False
    cdp_timeout_s: float = 120.0
    cross_origin_iframes: bool = False
    enable_default_extensions: bool = False
    minimum_wait_page_load_time: float = 1.5
    wait_for_network_idle_page_load_time: float = 1.5
    wait_between_actions: float = 0.5
    keep_alive: bool = True


VARIANTS = [
    Variant("dom-skip-preflight"),
    Variant("dom-slow-wait", minimum_wait_page_load_time=3.0, wait_for_network_idle_page_load_time=3.0),
    Variant("dom-no-iframes-ext-off", cross_origin_iframes=False, enable_default_extensions=False),
    Variant("vision-skip-preflight", use_vision=True),
]


@dataclass
class ProbeResult:
    variant: str
    actions: int
    final_url: str
    error_hint: str
    session_url: str
    ok: bool


async def _run_variant(task: dict, v: Variant, *, max_steps: int) -> ProbeResult:
    os.environ["BROWSER_USE_CDP_TIMEOUT_S"] = str(v.cdp_timeout_s)
    os.environ["BROWSER_USE_ACTION_TIMEOUT_S"] = "240"

    bb = create_session(keep_alive=v.keep_alive)
    session_url = bb.session_url
    try:
        from browser_use.browser.profile import BrowserProfile

        profile = BrowserProfile(
            cdp_url=bb.connect_url,
            is_local=False,
            viewport=VIEWPORT,
            user_agent=USER_AGENT,
            disable_security=True,
            cross_origin_iframes=v.cross_origin_iframes,
            enable_default_extensions=v.enable_default_extensions,
            minimum_wait_page_load_time=v.minimum_wait_page_load_time,
            wait_for_network_idle_page_load_time=v.wait_for_network_idle_page_load_time,
            wait_between_actions=v.wait_between_actions,
            captcha_solver=False,
        )
        llm = ChatOpenAI(
            model=os.environ.get("MISTRAL_MODEL", "mistral-small-2603"),
            api_key=mistral_api_key(),
            base_url=MISTRAL_API_BASE,
            temperature=0,
        )
        agent_task = (
            f"{CAPABLE_AGENT_PREAMBLE}\n\n"
            f"Open {task['start_url']} if not already there.\n"
            f"Task: {task['task']}\n"
            f"Satisfy every constraint. Stop only when fully done."
        )
        agent = Agent(
            task=agent_task,
            llm=llm,
            browser_profile=profile,
            use_vision=v.use_vision,
            max_actions_per_step=2,
            calculate_cost=True,
        )
        history = await agent.run(max_steps=max_steps)
        actions = _history_to_actions(history)
        final_url = ""
        try:
            final_url = history.urls()[-1] if hasattr(history, "urls") and history.urls() else ""
        except Exception:
            final_url = actions[-1].get("url") or "" if actions else ""
        err = ""
        for a in actions:
            r = str(a.get("result") or "")
            if "error" in r.lower() or "failed" in r.lower():
                err = r[:200]
                break
        ok = len(actions) >= 2 and "access denied" not in err.lower()
        return ProbeResult(v.name, len(actions), final_url, err, session_url, ok)
    except Exception as exc:  # noqa: BLE001
        return ProbeResult(v.name, 0, "", str(exc)[:200], session_url, False)
    finally:
        close_session(bb.id)


async def _main_async(eval_index: int, max_steps: int) -> list[ProbeResult]:
    task = load_tasks([eval_index])[0]
    results: list[ProbeResult] = []
    for v in VARIANTS:
        print(f"\n=== {v.name} ===", flush=True)
        r = await _run_variant(task, v, max_steps=max_steps)
        results.append(r)
        print(
            f"  actions={r.actions} ok={r.ok} url={r.final_url[:60]!r} err={r.error_hint[:80]!r}",
            flush=True,
        )
        print(f"  session: {r.session_url}", flush=True)
        if r.ok:
            print("  -> stopping early (first working variant)", flush=True)
            break
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-index", type=int, default=19)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "browserbase_probe_results.json")
    args = ap.parse_args()

    os.environ.setdefault("USE_BROWSERBASE", "1")
    results = asyncio.run(_main_async(args.eval_index, args.max_steps))
    payload = {"eval_index": args.eval_index, "results": [asdict(r) for r in results]}
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {args.out}", flush=True)
    return 0 if any(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
