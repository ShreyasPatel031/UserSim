"""End-to-end persona study on a native iPhone app (BrowserStack real device).

One device session: sign in to the App Store and install the app once, then for
each persona delete + reinstall the app so every persona starts at first launch,
let the persona pursue its task, and finally write a report.

    python -m mvp.ios_study --app "Reframe: Drink Less & Thrive" \
        --bundle com.glucobit.cravingBuster.CravingBuster --personas 3
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from mvp.ios_agent import ROOT, Device, _client, run_goal
from mvp.ios_install import ensure_installed


def _gemini_json(prompt: str, max_tokens: int = 4096) -> Any:
    from google.genai import types

    resp = _client().models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
        ),
    )
    raw = (resp.text or "").strip()
    match = re.search(r"[\[{].*[\]}]", raw, re.S)
    return json.loads(match.group(0) if match else raw)


def make_personas(app: str, description: str, n: int) -> list[dict]:
    data = _gemini_json(
        f"Product: the iPhone app \"{app}\". {description}\n"
        f"Write {n} distinct realistic target users who might download it, and for each one a concrete "
        "first-session task a real person would try on day one (achievable in ~10 minutes, starting from "
        "first launch: onboarding included). Vary age, motivation, tech comfort, patience and price "
        "sensitivity.\nReturn JSON list of objects: "
        "{\"name\", \"age\", \"bio\" (2 sentences), \"motivation\", \"patience\" (low|medium|high), "
        "\"task\" (one sentence), \"success\" (what done looks like)}."
    )
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    return list(data)[:n]


def persona_email(i: int, app: str) -> str | None:
    from mvp.email_codes import _imap_creds

    base = os.environ.get("MVP_PERSONA_EMAIL_BASE")
    if not base:
        creds = _imap_creds()
        if not creds:
            return None
        base = creds[0]
    local, domain = base.split("@", 1)
    tag = re.sub(r"[^a-z0-9]", "", app.lower())[:10]
    return f"{local.split('+')[0]}+{tag}{time.strftime('%m%d%H%M')}p{i}@{domain}"


def persona_goal(p: dict, app: str, email: str | None = None) -> str:
    account = (
        f"If the app asks you to create an account, sign up with email {email} (a real inbox you can read) "
        "and a password like Usersim!2026x; when it emails a code, use request_email_code. "
        if email else
        "If the app asks you to create an account, prefer 'Sign in with Apple'. "
    )
    return (
        f"You ARE this person, using the iPhone app \"{app}\" for the first time:\n"
        f"{p.get('name')}, {p.get('age')}. {p.get('bio')} Motivation: {p.get('motivation')}. "
        f"Patience: {p.get('patience')}.\n"
        f"TASK: {p.get('task')}\nSUCCESS LOOKS LIKE: {p.get('success')}\n"
        "Behave like this real person: read what is on screen, answer onboarding questions truthfully as "
        "this persona, skip what you would skip. " + account +
        "If Apple asks for its password use {{APPLE_PASSWORD}}. "
        "When you hit a paywall, note the price/trial, then look for a way to continue without paying "
        "(close X, 'not now', 'maybe later'); if there is none, that is the end: reply give_up with the "
        "reason. Never purchase or start a subscription. Reply done once the task is accomplished, or "
        "give_up when this person would quit — in the note, say in this person's words what worked, what "
        "confused or annoyed them, and where they would drop off."
    )


def summarize(app: str, persona: dict, result: Any) -> dict:
    steps = [
        f"{s['step']}. {s['action']} {s.get('target', '')} — {s.get('thought', '')[:200]}"
        for s in result.steps
    ]
    return _gemini_json(
        f"A simulated user tested the iPhone app \"{app}\".\nPersona: {json.dumps(persona)}\n"
        f"Outcome: {result.outcome}. Final note: {result.note}\nPaywall screens seen: {len(result.paywall)}\n"
        "Steps:\n" + "\n".join(steps[-45:]) +
        "\nReturn JSON: {\"completed\": bool, \"reached\": \"furthest point reached\", "
        "\"friction\": [up to 4 short specific issues], \"positives\": [up to 3], "
        "\"paywall\": \"where/what the paywall asked, or none\", \"quote\": \"one sentence in persona voice\"}",
        max_tokens=1500,
    )


def write_report(out: Path, app: str, rows: list[dict], overall: dict) -> Path:
    md = [f"# {app} — UserSim iPhone study", "",
          f"Real iPhone on BrowserStack · {len(rows)} personas · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", ""]
    if overall:
        md += ["## Top findings", ""] + [f"- {x}" for x in overall.get("findings", [])] + [""]
        md += ["## Recommendations", ""] + [f"{i}. {x}" for i, x in enumerate(overall.get("recommendations", []), 1)] + [""]
    md += ["## Personas", ""]
    for r in rows:
        p, s = r["persona"], r["summary"]
        md += [f"### {p.get('name')}, {p.get('age')} — {'completed' if s.get('completed') else 'did not complete'}",
               f"*Task:* {p.get('task')}  ", f"*Reached:* {s.get('reached')}  ",
               f"*Paywall:* {s.get('paywall')}  ", f"*Steps:* {r['steps']} · outcome `{r['outcome']}`", "",
               f"> {s.get('quote')}", "", "Friction:"] + [f"- {x}" for x in s.get("friction", [])] + \
              ["", "Worked:"] + [f"- {x}" for x in s.get("positives", [])] + \
              ["", f"Screens: `{r['dir']}`", ""]
    (out / "README.md").write_text("\n".join(md))

    cards = []
    for r in rows:
        p, s = r["persona"], r["summary"]
        shots = sorted(Path(r["dir"]).glob("*.png"))
        pick = [shots[i] for i in sorted({0, len(shots) // 3, 2 * len(shots) // 3, len(shots) - 1}) if shots and 0 <= i < len(shots)]
        imgs = "".join(f'<img src="{html.escape(str(x.relative_to(out)))}" loading="lazy">' for x in pick)
        li = lambda xs: "".join(f"<li>{html.escape(str(x))}</li>" for x in xs)
        cards.append(
            f'<section class="card"><h3>{html.escape(str(p.get("name")))}, {html.escape(str(p.get("age")))} '
            f'<span class="tag {"ok" if s.get("completed") else "no"}">{"completed" if s.get("completed") else "dropped"}</span></h3>'
            f'<p><b>Task</b> {html.escape(str(p.get("task")))}</p><p><b>Reached</b> {html.escape(str(s.get("reached")))}</p>'
            f'<p><b>Paywall</b> {html.escape(str(s.get("paywall")))}</p><blockquote>{html.escape(str(s.get("quote")))}</blockquote>'
            f'<div class="cols"><div><b>Friction</b><ul>{li(s.get("friction", []))}</ul></div>'
            f'<div><b>Worked</b><ul>{li(s.get("positives", []))}</ul></div></div><div class="shots">{imgs}</div></section>'
        )
    li = lambda xs: "".join(f"<li>{html.escape(str(x))}</li>" for x in xs)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(app)} study</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#57534e;--card:#fff;--line:#e7e5e4;--ok:#15803d;--no:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--line:#44403c;--ok:#4ade80;--no:#f87171}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1000px;margin:auto}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}}
.tag{{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid}}.ok{{color:var(--ok)}}.no{{color:var(--no)}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.shots{{display:flex;gap:8px;overflow-x:auto}}.shots img{{height:320px;border-radius:10px;border:1px solid var(--line)}}
blockquote{{color:var(--mut);border-left:3px solid var(--line);margin:8px 0;padding-left:12px}}p{{margin:4px 0}}
</style></head><body><h1>{html.escape(app)}</h1><p style="color:var(--mut)">UserSim on a real iPhone (BrowserStack) · {len(rows)} personas</p>
<h2>Top findings</h2><ul>{li(overall.get("findings", []))}</ul><h2>Recommendations</h2><ol>{li(overall.get("recommendations", []))}</ol>
<h2>Personas</h2>{"".join(cards)}</body></html>"""
    path = out / "report.html"
    path.write_text(page)
    return path


APPLIVE_SETUP = (
    "You are operating a real iPhone streamed into a BrowserStack App Live page. The screenshot shows the phone; "
    "tap by point on the phone. To type, tap the field on the phone, then type. The App Store is already open.\n"
)


def applive_install_goal(app_name: str) -> str:
    from mvp.ios_install import install_goal

    return APPLIVE_SETUP + install_goal(app_name) + (
        "\n5. Then tap Open to launch the app and reply done once the app's first screen shows."
    )


def main_applive(args) -> int:
    from mvp.applive_device import AppLiveDevice

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "reports" / f"ios-{re.sub(r'[^a-z0-9]+', '-', args.app.lower())[:20].strip('-')}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    personas = make_personas(args.app, args.desc, args.personas)
    (out / "personas.json").write_text(json.dumps(personas, indent=2))
    print(f"{len(personas)} personas -> {out} (App Live)", flush=True)
    dev = AppLiveDevice()
    rows: list[dict] = []
    try:
        for i, p in enumerate(personas, 1):
            # Each App Live session gets a wiped device: start fresh, sign in, install.
            dev.end_session()
            started = False
            for attempt in range(4):
                if dev.start_session(timeout_s=180):
                    started = True
                    break
                # Usually a previous session still holds the single parallel slot; stop and retry.
                print(f"session {i}: stream not up (attempt {attempt + 1}); stopping and retrying", flush=True)
                dev.end_session()
                time.sleep(90)
            if not started:
                print(f"session {i}: phone stream never started", flush=True)
                break
            inst = run_goal(dev, applive_install_goal(args.app), out_dir=out / f"install-{i}",
                            max_steps=60, budget_s=1500)
            print(f"install {i}: {inst.outcome} {inst.note[:120]}", flush=True)
            if not inst.ok:
                break
            print(f"\n== persona {i}: {p.get('name')} — {p.get('task')}", flush=True)
            pdir = out / f"p{i}"
            email = persona_email(i, args.app)
            goal = ("The phone is streamed in a BrowserStack App Live page; operate the phone by clicking inside "
                    "the phone image. The app is open.\n" + persona_goal(p, args.app, email))
            # allow_password=False: no Apple password during persona runs, so nothing can be bought.
            res = run_goal(dev, goal, out_dir=pdir, email_alias=email, allow_password=False,
                           max_steps=args.max_steps, budget_s=args.persona_budget)
            try:
                summary = summarize(args.app, p, res)
            except Exception as exc:
                summary = {"completed": res.ok, "reached": "?", "friction": [f"summary failed: {exc}"]}
            rows.append({"persona": p, "summary": summary, "outcome": res.outcome,
                         "steps": len(res.steps), "dir": str(pdir), "note": res.note})
            (out / "results.json").write_text(json.dumps(rows, indent=2))
            print(f"   -> {res.outcome}: {res.note[:200]}", flush=True)
    finally:
        dev.end_session()
        dev.quit()
    return _finish(out, args.app, rows)


def _finish(out: Path, app: str, rows: list[dict]) -> int:
    overall: dict = {}
    if rows:
        try:
            overall = _gemini_json(
                f"Synthesize a UX study of the iPhone app \"{app}\" from these persona results:\n"
                f"{json.dumps([{'persona': r['persona'].get('name'), **r['summary']} for r in rows])}\n"
                "Return JSON {\"findings\": [3-5 specific findings], \"recommendations\": [3 concrete fixes]}",
                max_tokens=1500,
            )
        except Exception:
            overall = {}
    report = write_report(out, app, rows, overall)
    print("report", report, flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="Reframe: Drink Less & Thrive")
    ap.add_argument("--bundle", default="com.glucobit.cravingBuster.CravingBuster")
    ap.add_argument("--desc", default="An app that helps people drink less alcohol using neuroscience-based daily lessons, tracking and coaching.")
    ap.add_argument("--personas", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=35)
    ap.add_argument("--persona-budget", type=float, default=720.0)
    ap.add_argument("--backend", choices=["automate", "applive"], default="automate",
                    help="automate = App Automate API; applive = drive the App Live web UI")
    args = ap.parse_args()
    if args.backend == "applive":
        return main_applive(args)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "reports" / f"ios-{re.sub(r'[^a-z0-9]+', '-', args.app.lower())[:20].strip('-')}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    personas = make_personas(args.app, args.desc, args.personas)
    (out / "personas.json").write_text(json.dumps(personas, indent=2))
    print(f"{len(personas)} personas -> {out}", flush=True)

    dev = Device(session_name=f"study {args.app[:30]}")
    print("session", dev.session_id, flush=True)
    rows: list[dict] = []
    try:
        inst = ensure_installed(dev, args.app, args.bundle, out / "install")
        print("install", inst, flush=True)
        if not inst.get("ok"):
            dev.mark(False, "install failed")
            return 1
        for i, p in enumerate(personas, 1):
            if i > 1:
                dev.terminate(args.bundle)
                dev.remove(args.bundle)
                inst = ensure_installed(dev, args.app, args.bundle, out / f"reinstall-{i}")
                if not inst.get("ok"):
                    print("reinstall failed", inst, flush=True)
                    break
            print(f"\n== persona {i}: {p.get('name')} — {p.get('task')}", flush=True)
            dev.launch(args.bundle)
            time.sleep(4)
            pdir = out / f"p{i}"
            email = persona_email(i, args.app)
            res = run_goal(dev, persona_goal(p, args.app, email), out_dir=pdir, email_alias=email,
                           max_steps=args.max_steps, budget_s=args.persona_budget)
            try:
                summary = summarize(args.app, p, res)
            except Exception as exc:
                summary = {"completed": res.ok, "reached": "?", "friction": [f"summary failed: {exc}"]}
            rows.append({"persona": p, "summary": summary, "outcome": res.outcome,
                         "steps": len(res.steps), "dir": str(pdir), "note": res.note})
            (out / "results.json").write_text(json.dumps(rows, indent=2))
            print(f"   -> {res.outcome}: {res.note[:200]}", flush=True)
        dev.mark(bool(rows), f"{len(rows)} personas run")
    finally:
        dev.quit()

    overall: dict = {}
    if rows:
        try:
            overall = _gemini_json(
                f"Synthesize a UX study of the iPhone app \"{args.app}\" from these persona results:\n"
                f"{json.dumps([{'persona': r['persona'].get('name'), **r['summary']} for r in rows])}\n"
                "Return JSON {\"findings\": [3-5 specific findings], \"recommendations\": [3 concrete fixes]}",
                max_tokens=1500,
            )
        except Exception:
            overall = {}
    report = write_report(out, args.app, rows, overall)
    print("report", report, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
