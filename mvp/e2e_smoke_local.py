#!/usr/bin/env python3
"""STRICT local smoke e2e — must FAIL on stuck screens.

Smoke mode (1 user × 1 task × product). Uses gemini-2.5-flash-lite.

SITE-AGNOSTIC BY CONTRACT. Every check derives from --url at runtime: the
expected host comes from the URL you pass, gate/consent detection is
brand-neutral, and no assertion is stronger or weaker for one domain than
another. There is no per-site mode or preset. Point it at anything:

  --url https://example.com/            (default: E2E_PRODUCT_URL)

Sites differ in how they fail — consent walls, signed-in bootstraps,
hang-after-open — so vary --url to widen coverage. The test itself does not
change when you do.

Hard fails if:
  1. No real site screenshot within a few seconds of tasks
  2. Screen is a cookie / consent wall (or blank) when agent claims progress
  3. After step ≥ 1: no live iframe mounted, when the backend offered a
     live_view_url (latched via MutationObserver — the stage unmounts the
     iframe as soon as the session stops browsing, which races short runs)
  4. Prev/Next step pills do not change the visible stage pixels
  5. Previous vs new frames are stuck (flash-lite progress judge)

Usage:
  E2E_BASE=http://127.0.0.1:3000 PYTHONPATH=src:. python mvp/e2e_smoke_local.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mvp.e2e_ui_run import (  # noqa: E402
    FETCH_PROBE,
    JUDGE_MODEL,
    LIVE_OBSERVER,
    _hostname,
    _log,
    http_json,
    judge_progress,
    judge_screenshot,
)

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))

OUT_DIR = Path(os.environ.get("E2E_SMOKE_OUT", ROOT / "results" / "e2e_smoke_local"))
# Defaults only — never branched on. Override with --url / --task or the env
# vars. No code path may test `args.url == PRODUCT` to change behaviour.
PRODUCT = os.environ.get("E2E_PRODUCT_URL", "https://useagency.dev/")
TASK = os.environ.get(
    "E2E_SMOKE_TASK",
    "Skim the homepage and say the main promise in one sentence",
)


def _download(base: str, url: str) -> bytes | None:
    if not url:
        return None
    if url.startswith("data:image"):
        import base64

        try:
            return base64.b64decode(url.split(",", 1)[1])
        except Exception:
            return None
    if url.startswith("/"):
        url = base.rstrip("/") + url
    try:
        with urllib.request.urlopen(url, timeout=45) as resp:
            raw = resp.read()
        return raw if raw and len(raw) > 200 else None
    except Exception:
        return None


def _png_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _image_stats(png: bytes) -> dict:
    """Grayscale spread of a frame. Flat spread == nothing was drawn."""
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("L")
    px = list(im.getdata())
    if not px:
        return {"mean": 0.0, "stdev": 0.0, "unique": 0}
    mean = sum(px) / len(px)
    var = sum((v - mean) ** 2 for v in px) / len(px)
    return {"mean": round(mean, 2), "stdev": round(var**0.5, 2), "unique": len(set(px))}


def _looks_blank(png: bytes) -> bool:
    """A mounted-but-unpainted Browserbase iframe is a flat #0a0a0a rectangle.

    Checking only that the <iframe> exists rewards mounting, not painting, so a
    stage that swapped a real screenshot for a dead black box scored as live.
    """
    try:
        st = _image_stats(png)
    except Exception:
        return False
    return st["stdev"] < 6.0 or st["unique"] < 12


def _poll_study(base: str, study_id: str) -> tuple[dict | None, str]:
    """Fetch study state without letting a transient blip kill the run.

    A raised urlopen error used to propagate out of run(), so the report was
    replaced by {"pass": false, "error": ...} and every finding collected up to
    that point was thrown away.
    """
    try:
        return http_json(base, f"/api/studies/{study_id}", timeout=45), ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


async def _live_frame_png(page) -> bytes | None:
    """Screenshot just the live iframe box, if one is mounted."""
    try:
        loc = page.locator("iframe.stage-live-frame")
        if not await loc.count():
            return None
        return await loc.first.screenshot(type="png")
    except Exception:
        return None


def _stage_js() -> str:
    return """() => {
      const sec = document.getElementById('stage-section');
      const img = document.querySelector('#stage-body img.trace-screenshot');
      const iframe = document.querySelector('iframe.stage-live-frame');
      const waiting = document.querySelector('#stage-body .stage-waiting');
      const pills = [...document.querySelectorAll('.step-pill')].map((b) => ({
        text: (b.textContent || '').trim(),
        active: b.classList.contains('active'),
        disabled: b.disabled,
      }));
      const prev = document.querySelector('.step-nav[data-shot-delta="-1"]');
      const next = document.querySelector('.step-nav[data-shot-delta="1"]');
      const caption = (document.querySelector('#stage-body figcaption')?.innerText || '').slice(0, 200);
      const thoughts = (document.querySelector('.stage-thought-list')?.innerText || '').slice(0, 400);
      return {
        stageOk: Boolean(sec && !sec.hidden),
        imgOk: Boolean(img && img.complete && img.naturalWidth > 40),
        imgSrc: img?.getAttribute('src') || img?.dataset?.shotSrc || '',
        liveOk: Boolean(iframe && (iframe.src || iframe.getAttribute('src'))),
        liveSrc: (iframe && (iframe.src || iframe.getAttribute('src'))) || '',
        waiting: Boolean(waiting),
        caption,
        thoughts,
        pills,
        prevDisabled: Boolean(prev?.disabled),
        nextDisabled: Boolean(next?.disabled),
        pillCount: pills.length,
      };
    }"""


def _looks_like_blocker(text: str) -> bool:
    t = (text or "").lower()
    needles = (
        "before you continue",
        "reject all",
        "accept all",
        "cookie",
        "consent",
        "we value your privacy",
        "manage options",
        "privacy preferences",
        "verify you are human",
        "sign in to continue",
    )
    return any(n in t for n in needles)


def judge_usable_page(png: bytes, *, label: str, expected_host: str) -> dict:
    """Fail cookie walls / blank / prep — not just 'is this the hostname'."""
    base = judge_screenshot(png, label=label, expected_host=expected_host)
    prompt_extra = f"""Also answer strictly for this agent screenshot on `{expected_host}`:

FAIL if you see a cookie/consent wall, "Before you continue", Accept all / Reject all,
a login gate that blocks the page, a blank/spinner, or UserSim chrome only.

PASS only if the main product page content is usable (nav, hero, readable copy).

Return JSON only:
{{
  "is_cookie_or_consent_wall": true/false,
  "is_login_gate_blocking": true/false,
  "page_is_usable_for_browsing": true/false,
  "blocker_text_guess": "short or empty",
  "reason": "one short sentence"
}}
"""
    from mvp.e2e_ui_run import gemini_vision_json

    extra = gemini_vision_json(prompt_extra, png)
    base["blocker"] = extra
    blocked = bool(
        extra.get("is_cookie_or_consent_wall")
        or extra.get("is_login_gate_blocking")
        or not extra.get("page_is_usable_for_browsing")
    )
    base["pass"] = bool(base.get("pass")) and not blocked
    if blocked and not base.get("reason"):
        base["reason"] = extra.get("reason") or "page blocked / not usable"
    elif blocked:
        base["reason"] = f"{base.get('reason')} | {extra.get('reason')}"
    return base


async def run(args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*"):
        if old.is_file():
            old.unlink()

    t0 = time.time()
    report: dict = {
        "base": args.base,
        "product_url": args.url,
        "judge_model": JUDGE_MODEL,
        "mode": "smoke",
        "fails": [],
        "checks": {},
        "pass": False,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.add_init_script(FETCH_PROBE)
        await page.add_init_script(LIVE_OBSERVER)

        _log(f"→ smoke open {args.base}")
        await page.goto(args.base, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector("#study-form #submit-btn", timeout=30_000)

        # Force Smoke ON for cheap local runs.
        smoke = page.locator("#test-mode-input")
        row = page.locator("#local-smoke-row")
        if await row.count():
            await row.evaluate("el => { el.hidden = false }")
        if await smoke.count() and not await smoke.is_checked():
            await smoke.check()
        if not await smoke.count() or not await smoke.is_checked():
            report["fails"].append("smoke checkbox not available/checked")
        report["checks"]["smoke_on"] = bool(await smoke.count() and await smoke.is_checked())

        await page.fill('input[name="url"]', args.url)
        details = page.locator("details.url-more")
        if await details.count():
            await details.first.evaluate("el => { el.open = true }")
        await page.fill('textarea[name="competitors"]', "")
        await page.fill('textarea[name="tasks"]', args.task)
        await page.fill(
            'textarea[name="customers"]',
            "One person only: a creative marketer evaluating the product.",
        )

        _log("→ click Run (SMOKE)")
        await page.click("#submit-btn")

        await page.wait_for_selector("#tasks-list li.task-row", timeout=args.brief_timeout_s * 1000)
        t_tasks = time.time()
        (OUT_DIR / "00_tasks.png").write_bytes(
            await page.locator("#tasks-panel").screenshot(type="png")
        )

        # SLA: real screen quickly after tasks.
        after_tasks_s = None
        deadline = t_tasks + args.after_tasks_s
        while time.time() < deadline + 6:
            st = await page.evaluate(_stage_js())
            if st.get("imgOk") or st.get("liveOk"):
                after_tasks_s = round(time.time() - t_tasks, 2)
                break
            await page.wait_for_timeout(150)
        report["checks"]["after_tasks_s"] = after_tasks_s
        if after_tasks_s is None:
            report["fails"].append("no screenshot or live after tasks")
        elif after_tasks_s > args.after_tasks_s:
            report["fails"].append(
                f"first screen {after_tasks_s}s after tasks (need ≤{args.after_tasks_s}s)"
            )
        _log(f"  first screen {after_tasks_s}s after tasks")

        study_id = None
        for _ in range(60):
            study_id = await page.evaluate("() => window.__e2e && window.__e2e.studyId")
            if study_id:
                break
            await page.wait_for_timeout(250)
        report["study_id"] = study_id
        _log(f"  study_id={study_id}")
        if not study_id:
            report["fails"].append("no study id")
            report["elapsed_s"] = round(time.time() - t0, 1)
            (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2))
            return report

        host = _hostname(args.url)
        raw0 = None
        step0 = None
        for _ in range(40):
            snap = http_json(args.base, f"/api/studies/{study_id}", timeout=45)
            live = snap.get("live_sessions") or {}
            items = list(live.values()) if isinstance(live, dict) else list(live or [])
            for sess in items:
                for step in sess.get("trace") or []:
                    if not isinstance(step, dict):
                        continue
                    if step.get("step") != 0 and step.get("step") is not None:
                        continue
                    url = step.get("screenshot_data_url") or step.get("screenshot_url") or ""
                    if not url:
                        continue
                    raw0 = _download(args.base, url)
                    if raw0:
                        step0 = step
                        break
                if raw0:
                    break
            if raw0:
                break
            await page.wait_for_timeout(500)

        if not raw0:
            report["fails"].append("missing landing PNG")
        else:
            (OUT_DIR / "step0.png").write_bytes(raw0)
            j0 = judge_usable_page(raw0, label="step0", expected_host=host)
            report["checks"]["step0_judge"] = j0
            _log(f"  step0 judge={j0.get('pass')} {j0.get('reason')}")
            if not j0.get("pass"):
                report["fails"].append(f"step0 not usable real site: {j0.get('reason')}")

        # Follow until step ≥ 1 or timeout — REQUIRE live + progressing pixels.
        saw_live = False
        # Mounted is not painted. Track them separately so a black box cannot
        # score as a working live view.
        live_painted = False
        blank_live = 0
        saw_progress = False
        # Judge site pixels against site pixels only. Falling back to a
        # #stage-section screenshot (UserSim chrome, captions, thought ticker)
        # made a frozen page look like progress, because the chrome changed.
        prev_site_raw = raw0
        # Did the backend ever actually offer a live view? If Browserbase is not
        # configured no live_view_url is ever emitted, and demanding the iframe
        # would be a guaranteed failure that says nothing about the UI.
        live_offered = False
        # Liveness, not existence. A frozen Browserbase embed keeps its src and
        # keeps painting the same pixels forever, so "the iframe was mounted"
        # says nothing about whether the agent is still moving.
        live_hashes: set[str] = set()
        live_first_seen_t: float | None = None
        live_last_change_t: float | None = None
        live_moved = False
        live_max_static_gap = 0.0
        # Fold-proof accounting. The server may drop visually-identical frames
        # so they never become numbered steps, which hides a frozen agent from
        # the progress judge. Thoughts/pulses keep flowing when that happens, so
        # thought-growth far outpacing step-growth is the tell.
        thought_texts: set[str] = set()
        fold_markers = 0
        # Hang guard: steps must keep arriving while the study says it is running.
        last_step_t = time.time()
        stall_reported = False
        follow_deadline = time.time() + args.steps_timeout_s
        seen: set[int] = {0} if step0 is not None else set()
        api_errors = 0
        last_api_error = ""
        snap: dict = {}
        while time.time() < follow_deadline:
            fresh, api_err = _poll_study(args.base, study_id)
            if fresh is None:
                api_errors += 1
                last_api_error = api_err
                if api_errors >= 4:
                    report["fails"].append(
                        f"study API unreachable {api_errors}x while polling "
                        f"(last error: {last_api_error}) — server died mid-run"
                    )
                    break
                await page.wait_for_timeout(1500)
                continue
            api_errors = 0
            snap = fresh
            live = snap.get("live_sessions") or {}
            items = list(live.values()) if isinstance(live, dict) else list(live or [])
            sess = items[0] if items else {}
            if any(
                isinstance(s, dict) and s.get("live_view_url") for s in items
            ):
                live_offered = True
            # Latch continuously: the stage unmounts the iframe the moment the
            # session stops browsing, so a short smoke run can finish between
            # two polls and look like live never mounted at all.
            if await page.evaluate("() => Boolean(window.__e2eLive && window.__e2eLive.seen)"):
                saw_live = True

            for t in sess.get("live_thoughts") or []:
                if not isinstance(t, dict):
                    continue
                txt = str(t.get("text") or "").strip()
                if not txt:
                    continue
                if txt not in thought_texts:
                    thought_texts.add(txt)
                    if re.search(
                        r"no visual change|waiting —|identical|nothing changed|no change",
                        txt,
                        re.I,
                    ):
                        fold_markers += 1

            # Sample the live view on every poll and require its pixels to move.
            sample = await _live_frame_png(page)
            now = time.time()
            if sample:
                if live_first_seen_t is None:
                    live_first_seen_t = now
                    live_last_change_t = now
                if _looks_blank(sample):
                    blank_live += 1
                else:
                    live_painted = True
                h = _png_hash(sample)
                if h not in live_hashes:
                    live_hashes.add(h)
                    live_last_change_t = now
                    if len(live_hashes) > 1:
                        live_moved = True

            # Longest static gap, not a boolean. Gating this on `not live_moved`
            # meant one early pixel change disabled the freeze check for the
            # rest of the run — the same sticky-exemption bug this suite flags
            # elsewhere. An agent that moves once and then hangs must still fail.
            if (
                live_first_seen_t is not None
                and live_last_change_t is not None
                and str(snap.get("status") or "") in {"running", "pending", "queued", ""}
            ):
                live_max_static_gap = max(live_max_static_gap, now - live_last_change_t)
            if (
                live_first_seen_t is not None
                and live_last_change_t is not None
                and now - live_last_change_t > args.live_motion_s
                and str(snap.get("status") or "") in {"running", "pending", "queued", ""}
            ):
                report["fails"].append(
                    f"live screen frozen — no pixel change for "
                    f"{round(now - live_last_change_t)}s while status="
                    f"{snap.get('status')!r} phase={snap.get('phase')!r}"
                )
                break

            # No new numbered step for this long, while still 'running'.
            if (
                not stall_reported
                and now - last_step_t > args.stall_s
                and str(snap.get("status") or "") in {"running", "pending", "queued", ""}
            ):
                stall_reported = True
                thoughts = (sess.get("live_thoughts") or [])[-1:]
                report["fails"].append(
                    f"agent hung — no new step for {round(now - last_step_t)}s at "
                    f"steps {sorted(seen)}, last_action={sess.get('last_action')!r}, "
                    f"last_thought={(thoughts[0] or {}).get('text') if thoughts else None!r}"
                )
                break

            for step in sess.get("trace") or []:
                if not isinstance(step, dict):
                    continue
                if not isinstance(step.get("step"), int):
                    continue
                n = int(step["step"])
                if n in seen or n < 1:
                    continue
                seen.add(n)
                last_step_t = time.time()
                raw = _download(
                    args.base,
                    step.get("screenshot_data_url") or step.get("screenshot_url") or "",
                )
                st = await page.evaluate(_stage_js())
                ui_png = await page.locator("#stage-section").screenshot(type="png")
                (OUT_DIR / f"step{n}_ui.png").write_bytes(ui_png)
                if st.get("liveOk") or await page.evaluate(
                    "() => Boolean(window.__e2eLive && window.__e2eLive.seen)"
                ):
                    saw_live = True
                live_png = await _live_frame_png(page)
                if live_png:
                    (OUT_DIR / f"step{n}_live.png").write_bytes(live_png)
                    if _looks_blank(live_png):
                        blank_live += 1
                    else:
                        live_painted = True
                if raw:
                    (OUT_DIR / f"step{n}.png").write_bytes(raw)
                if prev_site_raw and raw:
                    prog = judge_progress(
                        prev_site_raw,
                        raw,
                        label=f"step{n-1}→{n}",
                        persona="smoke user",
                        task=args.task,
                        action=str(step.get("action") or ""),
                        expected_host=host,
                    )
                    report["checks"][f"progress_{n}"] = prog
                    _log(
                        f"  step {n} progress={prog.get('pass')} "
                        f"same={prog.get('screens_look_the_same')} {prog.get('reason')}"
                    )
                    if prog.get("pass"):
                        saw_progress = True
                    else:
                        report["fails"].append(
                            f"step {n}: not progressing — {prog.get('reason')}"
                        )
                    prev_site_raw = raw
                elif not raw:
                    # No site pixels for this step is itself the bug; say so
                    # instead of silently judging UserSim chrome.
                    report["fails"].append(
                        f"step {n}: no site screenshot to judge (screenshot_url missing or 404)"
                    )
                # Cookie wall check on the new frame bytes.
                if raw:
                    ju = judge_usable_page(raw, label=f"step{n}", expected_host=host)
                    report["checks"][f"usable_{n}"] = ju
                    if not ju.get("pass"):
                        report["fails"].append(
                            f"step {n}: unusable/blocked page — {ju.get('reason')}"
                        )
            if snap.get("status") in {"complete", "error", "abandoned"}:
                break
            # No early exit. Breaking as soon as one step landed meant an agent
            # that froze at "1 steps" for the rest of the run still passed.
            await page.wait_for_timeout(1500)

        if await page.evaluate("() => Boolean(window.__e2eLive && window.__e2eLive.seen)"):
            saw_live = True
        final_live = await _live_frame_png(page)
        if final_live and not _looks_blank(final_live):
            live_painted = True
        report["checks"]["live_offered_by_api"] = live_offered
        report["checks"]["saw_live_mounted"] = saw_live
        report["checks"]["live_painted"] = live_painted
        report["checks"]["blank_live_samples"] = blank_live
        report["checks"]["api_poll_errors"] = last_api_error or None
        report["checks"]["live_moved"] = live_moved
        report["checks"]["live_distinct_frames"] = len(live_hashes)
        report["checks"]["live_max_static_gap_s"] = round(live_max_static_gap, 1)
        if live_offered and not saw_live:
            report["fails"].append(
                "backend offered live_view_url but the stage never mounted the live iframe"
            )
        elif live_offered and saw_live and not live_painted:
            report["fails"].append(
                f"live iframe mounted but never painted ({blank_live} blank samples) — "
                "the stage replaced the site screenshot with a dead frame"
            )
        elif live_offered and saw_live and live_painted and not live_moved:
            report["fails"].append(
                f"live screen never moved — {len(live_hashes)} distinct frame(s) across "
                "the whole run; the embed was mounted and painted but static"
            )
        elif not live_offered:
            _log("  live view not offered by backend (no Browserbase) — live check skipped")
        if not saw_progress:
            report["fails"].append("never saw visual progress vs previous frame")

        # The study must actually finish. A run that dies with "Connection
        # interrupted" used to pass because one step had already landed.
        final_status = str(snap.get("status") or "")
        report["checks"]["final_status"] = final_status
        if final_status != "complete":
            report["fails"].append(
                f"study did not complete (status={final_status!r}, phase={snap.get('phase')!r})"
            )

        # Folding is only honest if the dropped frames were genuinely redundant.
        # If the agent kept thinking while the step rail barely grew, steps were
        # suppressed rather than earned.
        report["checks"]["distinct_thoughts"] = len(thought_texts)
        report["checks"]["fold_markers"] = fold_markers
        steps_landed = len([n for n in seen if isinstance(n, int)])
        report["checks"]["thought_to_step_ratio"] = (
            round(len(thought_texts) / steps_landed, 2) if steps_landed else None
        )
        if fold_markers >= args.max_folds:
            report["fails"].append(
                f"{fold_markers} no-visual-change pulses — the agent stalled and the "
                "frames were folded out of the step rail instead of being reported"
            )
        if steps_landed and len(thought_texts) >= args.fold_ratio * steps_landed:
            report["fails"].append(
                f"{len(thought_texts)} thoughts but only {steps_landed} numbered steps "
                f"(ratio {round(len(thought_texts)/steps_landed, 1)}x) — steps are being "
                "suppressed, not earned"
            )

        # And the agent must have moved more than once.
        shot_steps_seen = sorted(n for n in seen if isinstance(n, int))
        report["checks"]["steps_seen"] = shot_steps_seen
        if len(shot_steps_seen) < args.min_steps:
            report["fails"].append(
                f"agent only reached steps {shot_steps_seen} "
                f"(need ≥{args.min_steps} screenshot-backed steps — it stalled)"
            )

        # Surface the visible error banner instead of scoring around it.
        ui_err = await page.evaluate(
            """() => ({
                 phase: (document.getElementById('phase-label')?.innerText || '').trim(),
                 hint: (document.getElementById('progress-hint')?.innerText || '').trim(),
               })"""
        )
        report["checks"]["ui_error_state"] = ui_err
        if str(ui_err.get("phase", "")).lower() in {"paused", "failed"}:
            report["fails"].append(
                f"UI ended in an error state: phase={ui_err.get('phase')!r} "
                f"hint={ui_err.get('hint')!r}"
            )

        # Step pill navigation must change pixels when ≥2 shots exist.
        st = await page.evaluate(_stage_js())
        report["checks"]["pills"] = st.get("pills")
        if int(st.get("pillCount") or 0) >= 2:
            before = await page.locator("#stage-body").screenshot(type="png")
            (OUT_DIR / "nav_before.png").write_bytes(before)
            # Click first pill (step 0), then Next / last pill.
            await page.evaluate(
                """() => {
                  const pills = [...document.querySelectorAll('.step-pill')];
                  if (pills[0]) pills[0].click();
                }"""
            )
            await page.wait_for_timeout(400)
            mid = await page.locator("#stage-body").screenshot(type="png")
            (OUT_DIR / "nav_mid.png").write_bytes(mid)
            await page.evaluate(
                """() => {
                  const next = document.querySelector('.step-nav[data-shot-delta="1"]');
                  if (next && !next.disabled) next.click();
                  else {
                    const pills = [...document.querySelectorAll('.step-pill')];
                    pills[pills.length - 1]?.click();
                  }
                }"""
            )
            await page.wait_for_timeout(500)
            after = await page.locator("#stage-body").screenshot(type="png")
            (OUT_DIR / "nav_after.png").write_bytes(after)
            same = _png_hash(mid) == _png_hash(after)
            report["checks"]["step_nav_changed"] = not same
            _log(f"  step nav changed={not same}")
            if same:
                # Flash-lite confirmation so we don't fail on tiny chrome jitter only —
                # but identical SHA is already a hard fail.
                report["fails"].append(
                    "Prev/Next (or step pills) did not change the stage pixels"
                )
            else:
                nav_prog = judge_progress(
                    mid,
                    after,
                    label="step-nav",
                    persona="smoke user",
                    task="user clicked Next step pill",
                    action="navigate step history",
                    expected_host=host,
                )
                report["checks"]["step_nav_judge"] = nav_prog
                if nav_prog.get("screens_look_the_same"):
                    report["fails"].append(
                        f"step nav looks same to flash-lite: {nav_prog.get('reason')}"
                    )
        else:
            # If agent claimed multiple steps in API but UI has <2 pills, that's a bug.
            # Only count screenshot-backed steps: the UI builds pills from
            # stepsWithScreenshots(), so a step with no screenshot legitimately
            # has no pill and must not be reported as broken nav.
            api_steps = set()
            shot_steps = set()
            fresh, _err = _poll_study(args.base, study_id)
            if fresh is not None:
                snap = fresh
            live = snap.get("live_sessions") or {}
            items = list(live.values()) if isinstance(live, dict) else list(live or [])
            for sess in items:
                for step in sess.get("trace") or []:
                    if not isinstance(step, dict) or not isinstance(step.get("step"), int):
                        continue
                    if step.get("progress_only"):
                        continue
                    api_steps.add(int(step["step"]))
                    if step.get("screenshot_url") or step.get("screenshot_data_url"):
                        shot_steps.add(int(step["step"]))
            report["checks"]["api_step_numbers"] = sorted(api_steps)
            report["checks"]["api_screenshot_step_numbers"] = sorted(shot_steps)
            if len(shot_steps) >= 2:
                report["fails"].append(
                    f"API has screenshot steps {sorted(shot_steps)} but UI only has "
                    f"{st.get('pillCount')} pills — nav broken"
                )
            elif len(api_steps) >= 2:
                report["fails"].append(
                    f"API has steps {sorted(api_steps)} but only {sorted(shot_steps)} "
                    "carry a screenshot — steps are losing their frames"
                )

        # Caption / thoughts smell of stuck opening.
        st = await page.evaluate(_stage_js())
        blob = f"{st.get('caption') or ''}\n{st.get('thoughts') or ''}"
        if _looks_like_blocker(blob):
            report["fails"].append(f"UI text still shows consent/blocker: {blob[:160]!r}")
        (OUT_DIR / "final_stage.png").write_bytes(
            await page.locator("#stage-section").screenshot(type="png")
        )
        await browser.close()

    report["elapsed_s"] = round(time.time() - t0, 1)
    report["pass"] = not report["fails"]
    (OUT_DIR / "result.json").write_text(json.dumps(report, indent=2, default=str))
    _log(f"Wrote {OUT_DIR / 'result.json'} pass={report['pass']} fails={report['fails']}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="STRICT local smoke e2e")
    ap.add_argument("--base", default=os.environ.get("E2E_BASE", "http://127.0.0.1:3000"))
    ap.add_argument("--url", default=PRODUCT)
    ap.add_argument("--task", default=TASK)
    ap.add_argument("--brief-timeout-s", type=int, default=120)
    # A public URL must paint fast. This is a product requirement, not a knob to
    # loosen when it fails: warm runs already hit ~1.2s, so >2s is a real
    # regression (the Browserbase warm lost its race with the brief).
    ap.add_argument("--after-tasks-s", type=float, default=2.0)
    ap.add_argument("--steps-timeout-s", type=int, default=240)
    ap.add_argument(
        "--stall-s",
        type=float,
        default=45.0,
        help="fail if no new numbered step arrives for this long while running",
    )
    ap.add_argument(
        "--live-motion-s",
        type=float,
        default=30.0,
        help="fail if the live iframe never changes a pixel for this long",
    )
    ap.add_argument(
        "--max-folds",
        type=int,
        default=2,
        help="fail if this many no-visual-change pulses are seen (folded stalls)",
    )
    ap.add_argument(
        "--fold-ratio",
        type=float,
        default=6.0,
        help="fail if distinct thoughts exceed this multiple of numbered steps",
    )
    ap.add_argument(
        "--min-steps",
        type=int,
        default=2,
        help="minimum screenshot-backed steps the agent must reach (stall guard)",
    )
    ap.add_argument("--headed", action="store_true", default=os.environ.get("E2E_HEADED") == "1")
    args = ap.parse_args()
    import asyncio

    try:
        result = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL: {exc}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Merge onto whatever the run already wrote instead of clobbering it —
        # a crash at minute 2 must not erase the findings from minute 1.
        partial: dict = {}
        prior = OUT_DIR / "result.json"
        if prior.is_file():
            try:
                loaded = json.loads(prior.read_text())
                if isinstance(loaded, dict):
                    partial = loaded
            except Exception:
                partial = {}
        partial["pass"] = False
        partial["error"] = str(exc)
        partial.setdefault("fails", []).append(f"run aborted: {exc}")
        prior.write_text(json.dumps(partial, indent=2, default=str))
        return 1
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
