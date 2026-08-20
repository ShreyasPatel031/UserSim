"""UserSim v0.6: free-run agent vs UserSim on live Mind2Web sites."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from google import genai
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, RESULTS_DIR, ROOT
from live_browser import dismiss_cookies, execute_action, extract_candidates
from live_predict import predict_live
from model import TokenMeter

SITE_URLS = json.loads((ROOT / "data" / "site_urls.json").read_text())
TASKS = json.loads((ROOT / "data" / "mind2web_tasks.json").read_text())["tasks"]

# Prefer short no-login-ish public sites for the first free-run slice.
# Screened 2026-08-20 on cloud VM: these start URLs returned 200 without login wall.
PREFERRED = [
    32,  # ign Resident Evil guide (3)
    26,  # rottentomatoes Tom Hanks (4)
    33,  # espn NHL Atlantic (6)
    8,   # newegg keyboard/mouse (5)
    19,  # uniqlo baby sale (4)
    22,  # megabus Alanson stops (3)
    7,   # jetblue NY careers (4)
    12,  # ticketcenter NFL tickets (3)
    25,  # underarmour (screened open)
    34,  # eventbrite (screened open)
]


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return ""


def action_repr(cand_repr: str, action: str, value: str | None) -> str:
    if action == "STOP":
        return "STOP"
    if value:
        return f"{cand_repr} -> {action}: {value}"
    return f"{cand_repr} -> {action}"


def token_set(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) > 1}


def semantic_overlap(human: list[str], generated: list[str]) -> float:
    """Jaccard over bag-of-tokens across trajectory action strings (excl STOP)."""
    h = set()
    g = set()
    for s in human:
        h |= token_set(s)
    for s in generated:
        if s == "STOP":
            continue
        g |= token_set(s)
    if not h and not g:
        return 1.0
    if not h or not g:
        return 0.0
    return len(h & g) / len(h | g)


def count_repeats(actions: list[str]) -> int:
    if len(actions) < 2:
        return 0
    return sum(1 for a, b in zip(actions, actions[1:]) if a == b)


def count_backtracks(urls: list[str]) -> int:
    if len(urls) < 3:
        return 0
    n = 0
    for i in range(2, len(urls)):
        if urls[i] == urls[i - 2] and urls[i] != urls[i - 1]:
            n += 1
    return n


def screen_url(page, url: str, timeout_ms: int = 20000) -> dict:
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
        dismiss_cookies(page)
        title = page.title()
        final = page.url
        body = ""
        try:
            body = page.inner_text("body")[:1500].lower()
        except Exception:  # noqa: BLE001
            pass
        loginish = any(
            k in body
            for k in (
                "sign in to continue",
                "create an account",
                "log in to your account",
                "please log in",
                "captcha",
            )
        )
        status = resp.status if resp else None
        ok = status is not None and status < 400 and "chrome-error" not in final
        return {
            "ok": ok,
            "status": status,
            "url": final,
            "title": title,
            "login_wall_likely": loginish,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": None,
            "url": url,
            "title": "",
            "login_wall_likely": False,
            "error": str(exc)[:200],
        }


def run_episode(
    task: dict,
    condition: str,
    client: genai.Client,
    meter: TokenMeter,
    out_dir: Path,
    max_steps: int | None = None,
) -> dict:
    website = task["website"]
    start_url = SITE_URLS.get(website)
    human_n = int(task.get("n_steps") or 5)
    cap = max_steps or min(20, max(8, 2 * human_n))
    history: list[str] = []
    urls: list[str] = []
    steps: list[dict] = []
    stopped = False
    stop_reason = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1200)
            dismiss_cookies(page)
        except Exception as exc:  # noqa: BLE001
            browser.close()
            return {
                "annotation_id": task["annotation_id"],
                "website": website,
                "condition": condition,
                "task": task["confirmed_task"],
                "start_url": start_url,
                "error": f"goto failed: {exc}"[:300],
                "steps": [],
                "n_actions": 0,
                "stopped": False,
                "stop_reason": "navigation_error",
            }

        for step_i in range(cap):
            url = page.url
            urls.append(url)
            cands = extract_candidates(page, max_n=50)
            cand_strs = [c.repr() for c in cands]
            shot = page.screenshot(full_page=False, type="png")
            shot_path = out_dir / f"{condition}_step{step_i}.png"
            shot_path.write_bytes(shot)

            pred = predict_live(
                task=task["confirmed_task"],
                url=url,
                candidates=cand_strs,
                history=history,
                screenshot_png=shot,
                condition=condition,
                client=client,
            )
            meter.add(pred)

            action = (pred.action or "").upper()
            idx = pred.element_index
            value = pred.value
            cand = None
            cand_str = ""
            if action != "STOP" and idx and 1 <= idx <= len(cands):
                cand = cands[idx - 1]
                cand_str = cand.repr()
            elif action != "STOP":
                # Invalid index → treat as failed step and stop to avoid loops
                steps.append(
                    {
                        "i": step_i,
                        "url": url,
                        "prediction": {
                            "element_index": idx,
                            "action": action,
                            "value": value,
                            "raw": pred.raw,
                            "error": pred.error or "invalid_element_index",
                        },
                        "executed": False,
                    }
                )
                stop_reason = "invalid_prediction"
                break

            repr_s = action_repr(cand_str, action or "STOP", value)
            step_rec = {
                "i": step_i,
                "url": url,
                "n_candidates": len(cands),
                "prediction": {
                    "element_index": idx,
                    "action": action,
                    "value": value,
                    "raw": pred.raw,
                    "error": pred.error,
                    "prompt_tokens": pred.prompt_tokens,
                    "output_tokens": pred.output_tokens,
                },
                "action_repr": repr_s,
                "screenshot": str(shot_path.relative_to(RESULTS_DIR)),
            }

            if action == "STOP" or pred.error:
                step_rec["executed"] = False
                steps.append(step_rec)
                stopped = action == "STOP"
                stop_reason = "model_stop" if stopped else f"api_error:{pred.error}"
                break

            result = execute_action(page, cand, action, value)
            step_rec["executed"] = bool(result.get("ok"))
            step_rec["exec"] = result
            steps.append(step_rec)
            history.append(repr_s)
            if not result.get("ok"):
                stop_reason = f"exec_error:{result.get('error')}"
                break
        else:
            stop_reason = "max_steps"

        end_url = page.url
        end_title = ""
        try:
            end_title = page.title()
        except Exception:  # noqa: BLE001
            pass
        browser.close()

    gen_actions = [s.get("action_repr") for s in steps if s.get("action_repr") and s["action_repr"] != "STOP"]
    human = list(task.get("action_reprs") or [])
    op_counts = Counter()
    for s in steps:
        a = (s.get("prediction") or {}).get("action")
        if a:
            op_counts[a] += 1

    return {
        "annotation_id": task["annotation_id"],
        "eval_index": task.get("eval_index"),
        "website": website,
        "domain": task.get("domain"),
        "condition": condition,
        "task": task["confirmed_task"],
        "start_url": start_url,
        "end_url": end_url,
        "end_title": end_title,
        "human_n_steps": human_n,
        "human_actions": human,
        "n_actions": len(gen_actions),
        "n_model_steps": len(steps),
        "length_ratio_vs_human": (len(gen_actions) / human_n) if human_n else None,
        "extra_actions_vs_human": len(gen_actions) - human_n,
        "repeated_actions": count_repeats(gen_actions),
        "backtracks": count_backtracks(urls),
        "unique_hosts": sorted({_host(u) for u in urls if _host(u)}),
        "action_type_counts": dict(op_counts),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "semantic_overlap_vs_human": semantic_overlap(human, gen_actions),
        "steps": steps,
    }


def summarize(episodes: list[dict]) -> dict:
    by_cond: dict[str, list[dict]] = defaultdict(list)
    for ep in episodes:
        by_cond[ep["condition"]].append(ep)

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    out = {}
    for cond, eps in by_cond.items():
        ok = [e for e in eps if not e.get("error")]
        out[cond] = {
            "n": len(eps),
            "n_ok": len(ok),
            "mean_n_actions": mean([e["n_actions"] for e in ok]),
            "mean_length_ratio_vs_human": mean(
                [e["length_ratio_vs_human"] for e in ok if e.get("length_ratio_vs_human") is not None]
            ),
            "mean_extra_actions": mean([e["extra_actions_vs_human"] for e in ok]),
            "mean_repeats": mean([e["repeated_actions"] for e in ok]),
            "mean_backtracks": mean([e["backtracks"] for e in ok]),
            "mean_semantic_overlap": mean([e["semantic_overlap_vs_human"] for e in ok]),
            "stop_rate": mean([1.0 if e.get("stopped") else 0.0 for e in ok]),
            "action_types": dict(
                sum((Counter(e.get("action_type_counts") or {}) for e in ok), Counter())
            ),
            "stop_reasons": dict(Counter(e.get("stop_reason") for e in ok)),
        }
    # paired deltas agent - usersim
    paired = {}
    a = {e["annotation_id"]: e for e in by_cond.get("agent", []) if not e.get("error")}
    u = {e["annotation_id"]: e for e in by_cond.get("usersim", []) if not e.get("error")}
    ids = sorted(set(a) & set(u))
    if ids:
        paired = {
            "n_paired": len(ids),
            "delta_mean_n_actions": mean([a[i]["n_actions"] - u[i]["n_actions"] for i in ids]),
            "delta_mean_length_ratio": mean(
                [
                    (a[i]["length_ratio_vs_human"] or 0) - (u[i]["length_ratio_vs_human"] or 0)
                    for i in ids
                ]
            ),
            "delta_mean_semantic_overlap": mean(
                [
                    a[i]["semantic_overlap_vs_human"] - u[i]["semantic_overlap_vs_human"]
                    for i in ids
                ]
            ),
            "delta_stop_rate": mean(
                [(1.0 if a[i]["stopped"] else 0.0) - (1.0 if u[i]["stopped"] else 0.0) for i in ids]
            ),
        }
    return {"by_condition": out, "paired_agent_minus_usersim": paired}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--indices", type=str, default="")
    args = parser.parse_args()

    out_root = RESULTS_DIR / "v06"
    out_root.mkdir(parents=True, exist_ok=True)

    if args.indices:
        idxs = [int(x) for x in args.indices.split(",") if x.strip()]
    else:
        idxs = PREFERRED[: args.limit]

    tasks = []
    by_idx = {t["eval_index"]: t for t in TASKS}
    for i in idxs:
        if i in by_idx and by_idx[i]["website"] in SITE_URLS:
            tasks.append(by_idx[i])

    # Screen start URLs
    screen = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for t in tasks:
            url = SITE_URLS[t["website"]]
            info = screen_url(page, url)
            info.update(
                {
                    "eval_index": t["eval_index"],
                    "website": t["website"],
                    "task": t["confirmed_task"],
                    "n_steps": t["n_steps"],
                }
            )
            screen.append(info)
            print(
                f"screen {t['website']:18s} ok={info['ok']} login={info['login_wall_likely']} "
                f"status={info['status']} err={info['error']}"
            )
        browser.close()
    (out_root / "screen.json").write_text(json.dumps(screen, indent=2))
    if args.screen_only:
        print(json.dumps(screen, indent=2))
        return

    runnable = [
        by_idx[s["eval_index"]]
        for s in screen
        if s["ok"] and not s["login_wall_likely"]
    ][: args.limit]
    print(f"running {len(runnable)} tasks × 2 conditions")

    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
    )
    meter = TokenMeter()
    episodes = []
    for t in runnable:
        for cond in ("agent", "usersim"):
            ep_dir = out_root / "traces" / f"{t['eval_index']}_{t['website']}"
            ep_dir.mkdir(parents=True, exist_ok=True)
            print(f"== {cond} | {t['website']} | {t['confirmed_task'][:60]}")
            ep = run_episode(t, cond, client, meter, ep_dir)
            episodes.append(ep)
            (ep_dir / f"{cond}.json").write_text(json.dumps(ep, indent=2))
            print(
                f"   actions={ep.get('n_actions')} stop={ep.get('stop_reason')} "
                f"overlap={ep.get('semantic_overlap_vs_human')}"
            )

    summary = {
        "model": MODEL,
        "project": GCP_PROJECT,
        "n_tasks": len(runnable),
        "task_ids": [t["annotation_id"] for t in runnable],
        "websites": [t["website"] for t in runnable],
        "spend_usd": meter.cost_usd,
        "calls": meter.calls,
        "prompt_tokens": meter.prompt_tokens,
        "output_tokens": meter.output_tokens,
        "errors_api": meter.errors,
        "metrics": summarize(episodes),
        "screen": screen,
        "note": (
            "Free-running on live sites. Human path similarity is semantic token overlap, "
            "not exact DOM match. Live sites differ from 2022–2023 Mind2Web snapshots. "
            "Task success is not auto-judged in this pass."
        ),
    }
    (RESULTS_DIR / "summary_v06.json").write_text(json.dumps(summary, indent=2))
    (out_root / "episodes.json").write_text(json.dumps(episodes, indent=2))
    print(json.dumps({"spend": meter.cost_usd, "calls": meter.calls, "metrics": summary["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
