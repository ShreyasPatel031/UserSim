#!/usr/bin/env python3
"""Spend the captcha balance and log results/captcha_experiment.jsonl.

``spend`` sends priced CapSolver createTask calls until the live balance would
drop below $1. ``compare`` runs Browserbase alone against Browserbase plus
CapSolver on signup pages (two owner=signup sessions). Neither command prints
the API key.

Usage:
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_volume spend
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_volume compare --per-type 10
  PYTHONPATH=src:. .venv/bin/python -m mvp.captcha_volume table
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mvp.captcha_experiment import (  # noqa: E402
    DETECT_PATH,
    EXPERIMENT_LOG,
    TRIAL_PATH,
    _closest_paid_method,
    _experiment_env,
    _now,
    _read_jsonl,
    _release_leftover_experiment_sessions,
    _task_label,
    log_experiment,
    trial_one,
)


def _latest_detections() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(DETECT_PATH):
        if row.get("site"):
            latest[str(row["site"])] = row
    return latest


def _targets() -> list[dict[str, Any]]:
    """Priced createTask inputs from surveyed keys. hCaptcha is not sent as itself."""
    from mvp.captcha_spend import task_price

    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(**fields: Any) -> None:
        price = task_price(fields["task"])
        if price is None:
            return
        key = (fields["site"], fields["task"])
        if key in seen:
            return
        seen.add(key)
        fields["price"] = price
        fields["id"] = f"{fields['site']}|{fields['task']}"
        targets.append(fields)

    for row in _latest_detections().values():
        site = str(row.get("site") or "")
        url = str(row.get("url") or "")
        key = str(row.get("sitekey") or "")
        types = set(row.get("types") or [])
        ctype = str(row.get("type") or "")
        action = row.get("action")
        if key.startswith("0x4") and len(key) >= 12:
            add(
                site=site,
                type="turnstile",
                task="AntiTurnstileTaskProxyLess",
                sitekey=key,
                url=url,
                captcha_type="turnstile",
                action=None,
                extra={},
            )
        if key.startswith("6L") and len(key) >= 30:
            if "recaptcha_v3_enterprise" in types or ctype == "recaptcha_v3_enterprise":
                add(
                    site=site,
                    type="recaptcha_v3_enterprise",
                    task="ReCaptchaV3EnterpriseTaskProxyLess",
                    sitekey=key,
                    url=url,
                    captcha_type="recaptcha_v3_enterprise",
                    action=action,
                    extra={},
                )
            elif "recaptcha_enterprise" in types or ctype == "recaptcha_enterprise":
                add(
                    site=site,
                    type="recaptcha_enterprise",
                    task="ReCaptchaV2EnterpriseTaskProxyLess",
                    sitekey=key,
                    url=url,
                    captcha_type="recaptcha_enterprise",
                    action=None,
                    extra={},
                )
            elif ctype == "hcaptcha" and "recaptcha_v2" not in types and "recaptcha" not in types:
                pass
            else:
                logged = ctype if ctype.startswith("recaptcha") else "recaptcha_v2"
                add(
                    site=site,
                    type=logged,
                    task="ReCaptchaV2TaskProxyLess",
                    sitekey=key,
                    url=url,
                    captcha_type="recaptcha_v2",
                    action=None,
                    extra={},
                )
        extra: dict[str, Any] = {}
        if row.get("captchaId"):
            extra["captchaId"] = row["captchaId"]
        if row.get("gt"):
            extra["gt"] = row["gt"]
        if row.get("challenge"):
            extra["challenge"] = row["challenge"]
        if extra:
            add(
                site=site,
                type="geetest",
                task="GeeTestTaskProxyLess",
                sitekey=str(row.get("captchaId") or row.get("gt") or ""),
                url=url,
                captcha_type="geetest",
                action=None,
                extra=extra,
            )
    return targets


def _solve_one(target: dict[str, Any]) -> dict[str, Any]:
    os.environ["MVP_CAPTCHA_EXPERIMENT"] = "1"
    from mvp.captcha import _capsolver_solve
    from mvp.captcha_spend import ensure_attempt, last_outcome

    base = {
        "site": target["site"],
        "type": target["type"],
        "method": "capsolver",
        "task_type": target["task"],
        "cost": 0.0,
        "solve_ok": False,
        "signup_ok": False,
        "error": "",
        "floor": False,
    }
    try:
        ensure_attempt(target["site"])
    except Exception as exc:  # noqa: BLE001
        base["error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
        return base
    token = _capsolver_solve(
        "",
        sitekey=target["sitekey"],
        page_url=target["url"],
        captcha_type=target["captcha_type"],
        action=target.get("action"),
        timeout_s=75,
        blocking=True,
        extra=target.get("extra") or None,
        task_type_override=target["task"],
    )
    outcome = last_outcome()
    try:
        cost = float(outcome.get("cost") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    base["cost"] = round(cost, 6)
    base["solve_ok"] = bool(token)
    base["error"] = "" if token else str(outcome.get("note") or outcome.get("reason") or "no_token")[:300]
    return base


def _pick(targets: list[dict[str, Any]], stats: dict[str, dict[str, int]], n: int) -> list[dict[str, Any]]:
    alive = [t for t in targets if stats[t["id"]]["streak"] < 4]
    under = [t for t in alive if stats[t["id"]]["n"] < 12]
    pool = under or alive

    def rank(target: dict[str, Any]) -> tuple[int, float, int]:
        st = stats[target["id"]]
        return (0 if st["ok"] else 1, -float(target["price"]), st["n"])

    pool = sorted(pool, key=rank)
    if not pool:
        return []
    chosen: list[dict[str, Any]] = []
    i = 0
    while len(chosen) < n:
        chosen.append(pool[i % len(pool)])
        i += 1
        if i > n * 4:
            break
    return chosen[:n]


def run_spend(*, workers: int) -> None:
    """createTask until the live balance would fall below $1."""
    os.environ["MVP_CAPTCHA_EXPERIMENT"] = "1"
    from mvp.captcha_spend import capsolver_key, get_balance, spent_usd

    print(f"capsolver_key_set {bool(capsolver_key())}", flush=True)
    targets = _targets()
    print(f"spend targets {len(targets)} workers {workers}", flush=True)
    if not targets:
        print("spend no priced targets", flush=True)
        return
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "ok": 0, "streak": 0})
    logged = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while True:
            balance = None
            for _ in range(5):
                balance = get_balance()
                if balance is not None:
                    break
                time.sleep(1.5)
            print(
                f"spend balance {balance} ledger {spent_usd()} logged {logged}",
                flush=True,
            )
            if balance is None:
                print("spend balance_unknown", flush=True)
                break
            if balance < 1.02:
                print("spend stop balance_floor", flush=True)
                break
            room = balance - 1.0
            batch: list[dict[str, Any]] = []
            cost = 0.0
            for target in _pick(targets, stats, workers):
                price = float(target["price"])
                if cost + price > room + 1e-9:
                    break
                batch.append(target)
                cost += price
            if not batch:
                print("spend stop no_affordable_target", flush=True)
                break
            futures = {pool.submit(_solve_one, target): target for target in batch}
            hit_floor = False
            for fut in as_completed(futures):
                target = futures[fut]
                row = fut.result()
                if row.get("floor"):
                    hit_floor = True
                    continue
                # A missed balance read never called createTask. It is not a trial
                # and must not retire a site that has been solving.
                if row.get("error") == "balance_unknown":
                    continue
                st = stats[target["id"]]
                st["n"] += 1
                if row.get("solve_ok"):
                    st["ok"] += 1
                    st["streak"] = 0
                elif float(row.get("cost") or 0) > 0:
                    st["streak"] = 0
                else:
                    st["streak"] += 1
                log_experiment(row)
                logged += 1
                print(
                    f"spend {row.get('site')} {row.get('type')} {row.get('task_type')} "
                    f"solve={row.get('solve_ok')} cost={row.get('cost')} {row.get('error') or ''}",
                    flush=True,
                )
            if hit_floor:
                print("spend stop balance_floor", flush=True)
                break
            if all(stats[t["id"]]["streak"] >= 4 for t in targets):
                print("spend stop targets_uncharged", flush=True)
                break
    print(f"spend done logged {logged} balance {get_balance()} ledger {spent_usd()}", flush=True)


def _counts() -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in _read_jsonl(EXPERIMENT_LOG):
        if row.get("method") in {"browserbase", "browserbase+capsolver"}:
            counts[(str(row.get("type") or ""), str(row.get("method") or ""))] += 1
    return counts


def _blocked_hosts() -> set[str]:
    hosts: set[str] = set()
    for row in _read_jsonl(TRIAL_PATH):
        note = str(row.get("note") or "")
        if note and note != "not_blocked" and row.get("site"):
            hosts.add(str(row["site"]))
    return hosts


def _paired_jobs(per_type: int) -> list[tuple[dict[str, Any], str, int]]:
    blocked = _blocked_hosts()
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _latest_detections().values():
        ctype = str(row.get("type") or "none")
        if ctype in {"none", "error"}:
            continue
        by_type[ctype].append(row)
    have = _counts()
    jobs: list[tuple[dict[str, Any], str, int]] = []
    for ctype, sites in sorted(by_type.items()):
        sites = sorted(sites, key=lambda r: (0 if r.get("site") in blocked else 1, str(r.get("site") or "")))
        if not sites:
            continue
        for method in ("browserbase", "browserbase+capsolver"):
            need = per_type - have.get((ctype, method), 0)
            for i in range(max(0, need)):
                jobs.append((sites[i % len(sites)], method, i))
    return jobs


def _from_trial(row: dict[str, Any]) -> dict[str, Any]:
    cleared = row.get("cleared") == "y"
    token = row.get("token") == "y"
    note = str(row.get("note") or "")
    if token and not cleared:
        note = note or "token_returned_widget_remained"
    return {
        "site": row.get("site") or "",
        "type": row.get("type") or "",
        "method": row.get("method") or "",
        "task_type": row.get("task_type") or _task_label(str(row.get("type") or ""), str(row.get("method") or "")),
        "cost": row.get("cost") or 0,
        "solve_ok": cleared,
        "signup_ok": row.get("signup") == "y",
        "error": "" if cleared and row.get("signup") == "y" else note,
    }


async def run_compare(*, per_type: int) -> None:
    _experiment_env()
    closed = _release_leftover_experiment_sessions()
    if closed:
        print(f"released {closed} leftover signup-captcha sessions", flush=True)
    from mvp.captcha_spend import capsolver_key, get_balance

    print(f"capsolver_key_set {bool(capsolver_key())}", flush=True)
    jobs = _paired_jobs(per_type)
    print(f"compare queued {len(jobs)}", flush=True)
    sem = asyncio.Semaphore(2)

    async def one(job: tuple[dict[str, Any], str, int]) -> None:
        detection, method, repeat = job
        async with sem:
            if method == "browserbase+capsolver":
                balance = get_balance()
                if balance is not None and balance < 1.05:
                    log_experiment(
                        {
                            "site": detection.get("site"),
                            "type": detection.get("type"),
                            "method": method,
                            "task_type": _task_label(str(detection.get("type") or ""), method),
                            "cost": 0.0,
                            "solve_ok": False,
                            "signup_ok": False,
                            "error": "balance_floor",
                        }
                    )
                    print(f"compare skip {detection.get('site')} balance_floor", flush=True)
                    return
            row = await trial_one(detection, method, repeat)
            logged = _from_trial(row)
            # Closest-task label when the trial used a fallback method.
            if method == "browserbase+capsolver" and not logged.get("task_type"):
                logged["task_type"] = _task_label(
                    str(row.get("type") or ""),
                    _closest_paid_method(str(row.get("type") or "")),
                )
            log_experiment(logged)
            print(
                f"compare {logged.get('site')} {logged.get('type')} {logged.get('method')} "
                f"task={logged.get('task_type')} solve={logged.get('solve_ok')} "
                f"signup={logged.get('signup_ok')} cost={logged.get('cost')} {logged.get('error') or ''}",
                flush=True,
            )

    try:
        for i in range(0, len(jobs), 2):
            await asyncio.gather(*(one(job) for job in jobs[i : i + 2]))
            refresh_policy()
    finally:
        _release_leftover_experiment_sessions()
    refresh_policy()


def refresh_policy() -> dict[str, Any]:
    """Turn signup payment on for types whose browser trial actually cleared."""
    from mvp.captcha_experiment import POLICY_PATH
    from mvp.captcha_spend import load_method_policy

    policy = load_method_policy()
    types = dict(policy.get("types") or {})
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(EXPERIMENT_LOG):
        if row.get("method") != "browserbase+capsolver":
            continue
        if not row.get("solve_ok"):
            continue
        grouped[str(row.get("type") or "")].append(row)
    task_method = {
        "AntiTurnstileTaskProxyLess": "capsolver",
        "ReCaptchaV2TaskProxyLess": "capsolver",
        "ReCaptchaV3TaskProxyLess": "capsolver",
        "ReCaptchaV3EnterpriseTaskProxyLess": "capsolver",
        "ReCaptchaV2EnterpriseTaskProxyLess": "capsolver",
        "GeeTestTaskProxyLess": "capsolver",
        "ImageToTextTask": "image_to_text",
        "ReCaptchaV2Classification": "recaptcha_classification",
        "AntiAwsWafTaskProxyLess": "capsolver",
        "computed_drag": "mouse_drag",
        "FunCaptchaTaskProxyLess": "capsolver",
    }
    for ctype, rows in grouped.items():
        if not ctype:
            continue
        tasks = [str(r.get("task_type") or "") for r in rows if r.get("task_type") not in {None, "", "Browserbase"}]
        task = tasks[0] if tasks else ""
        method = task_method.get(task, "capsolver")
        if method == "capsolver" and task in {"FunCaptchaTaskProxyLess"}:
            continue
        types[ctype] = {
            "method": method,
            "task": task or None,
            "captcha_type": ctype,
            "cleared": len(rows),
            "n": len(rows),
            "signup_ok": sum(1 for r in rows if r.get("signup_ok")),
        }
    doc = {
        "apply_to_signup": bool(types),
        "updated_at": _now(),
        "types": types,
        "note": "Signup pays only for captcha types that cleared in a browser trial.",
    }
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(__import__("json").dumps(doc, indent=2) + "\n")
    return doc


def table_rows() -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _read_jsonl(EXPERIMENT_LOG):
        grouped[(str(row.get("type") or ""), str(row.get("method") or ""))].append(row)
    lines = []
    for key in sorted(grouped):
        rows = grouped[key]
        n = len(rows)
        solved = sum(1 for r in rows if r.get("solve_ok"))
        signed = sum(1 for r in rows if r.get("signup_ok"))
        cost = round(sum(float(r.get("cost") or 0) for r in rows), 6)
        lines.append(
            {
                "type": key[0],
                "method": key[1],
                "n": n,
                "solve_ok": solved,
                "solve_rate": round(solved / n, 3) if n else 0,
                "signup_ok": signed,
                "signup_rate": round(signed / n, 3) if n else 0,
                "cost": cost,
            }
        )
    return lines


def render_table() -> str:
    from mvp.captcha_spend import get_balance, spent_usd

    lines = table_rows()
    header = "| type | method | trials | solve ok | solve rate | signup ok | signup rate | cost |"
    sep = "|---|---|---:|---:|---:|---:|---:|---:|"
    body = [
        f"| {r['type']} | {r['method']} | {r['n']} | {r['solve_ok']} | {r['solve_rate']:.1%} | {r['signup_ok']} | {r['signup_rate']:.1%} | ${r['cost']:.4f} |"
        for r in lines
    ]
    spent = spent_usd()
    balance = get_balance()
    text = "\n".join(
        [
            header,
            sep,
            *body,
            "",
            f"Ledger booked ${spent:.4f}. Live CapSolver balance ${balance if balance is not None else 'unknown'}.",
        ]
    )
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Captcha spend and paired browser trials")
    sub = parser.add_subparsers(dest="cmd", required=True)
    spend = sub.add_parser("spend")
    spend.add_argument("--workers", type=int, default=int(os.environ.get("CAPTCHA_SPEND_WORKERS") or "12"))
    compare = sub.add_parser("compare")
    compare.add_argument("--per-type", type=int, default=10)
    sub.add_parser("table")
    sub.add_parser("wire")
    args = parser.parse_args()
    if args.cmd == "spend":
        run_spend(workers=args.workers)
    elif args.cmd == "compare":
        asyncio.run(run_compare(per_type=args.per_type))
    elif args.cmd == "table":
        print(render_table(), flush=True)
    elif args.cmd == "wire":
        print(__import__("json").dumps(refresh_policy(), indent=2), flush=True)


if __name__ == "__main__":
    main()
