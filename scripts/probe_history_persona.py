#!/usr/bin/env python3
"""Cheap A/B: task history only vs history + real OPeRA persona.

Same next-action records, same history in the user prompt. Only the system
prompt differs (persona block on/off). Primary metric: session-macro exact.

Budget: hard $5. Target wall <15m via ThreadPoolExecutor.
Default model: gemini-2.5-flash (~$1 for ~100x2 with OPeRA HTML).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

USERSIM = Path(__file__).resolve().parents[1]
OPERA = Path("/Users/shreyaspatel/Opera Human Behaviour Simulation")
sys.path.insert(0, str(USERSIM / "src"))
sys.path.insert(0, str(OPERA))

from auth import vertex_credentials  # noqa: E402
from opera_repro.actions import Action, actions_equal, parse_action  # noqa: E402
from opera_repro.evaluate import evaluate_predictions, format_report  # noqa: E402
from opera_repro.prompts import SYSTEM_PROMPT  # noqa: E402

PROJECT = os.environ.get("GCP_PROJECT") or os.environ.get(
    "GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"
)
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")

# Flash: $0.30 / $2.50 per M. Lite: $0.10 / $0.40.
PRICE = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}


def user_key(session_id: str) -> str:
    sid = session_id or ""
    return sid.split("_20")[0] if "_20" in sid else sid.split("_")[0]


def load_personas() -> dict[str, dict]:
    cat = json.loads((OPERA / "data/opera_catalog.json").read_text())
    return {p["id"]: p for p in cat.get("personas") or []}


def persona_block(p: dict) -> str:
    priorities = ", ".join(p.get("priorities") or []) or "value and reviews"
    avoids = ", ".join(p.get("avoids") or []) or "unclear listings"
    personality = p.get("personality") or {}
    pers = ", ".join(f"{k}={v}" for k, v in personality.items()) if personality else ""
    lines = [
        "SHOPPER PERSONA (this is the real human whose next action you predict):",
        f"Label: {p.get('label') or ''}",
        f"Bio: {p.get('bio') or ''}",
        f"Age/city/gender: {p.get('age') or '?'}, {p.get('city') or '?'}, {p.get('gender') or '?'}",
        f"Income: {p.get('income') or '?'}. Employment: {p.get('employment') or '?'}.",
        f"Budget: {p.get('budget') or '?'}. Prime: {p.get('prime') or '?'}. Shops: {p.get('shop_frequency') or '?'}.",
        f"Cares about: {priorities}.",
        f"Avoids: {avoids}.",
    ]
    if pers:
        lines.append(f"Personality: {pers}.")
    lines.append("Predict what THIS shopper does next, not a generic optimal shopper.")
    return "\n".join(lines)


def take_sessions(records: list[dict], max_sessions: int, max_examples: int) -> list[dict]:
    by_sid: OrderedDict[str, list] = OrderedDict()
    for row in records:
        by_sid.setdefault(row["session_id"], []).append(row)
    out: list = []
    n_sess = 0
    for rows in by_sid.values():
        if n_sess >= max_sessions:
            break
        if out and len(out) + len(rows) > max_examples:
            break
        out.extend(rows)
        n_sess += 1
    return out


def estimate_cost(n_calls: int, avg_in_chars: int, model: str) -> float:
    pin, pout = PRICE.get(model, (0.30, 2.50))
    in_tok = (avg_in_chars / 4) * n_calls
    out_tok = 80 * n_calls
    return in_tok / 1e6 * pin + out_tok / 1e6 * pout


def call_gemini(model: str, system: str, user: str, max_output_tokens: int = 128) -> tuple[dict, int, int]:
    creds = vertex_credentials()
    token = creds.token
    host = (
        "aiplatform.googleapis.com"
        if LOCATION == "global"
        else f"{LOCATION}-aiplatform.googleapis.com"
    )
    url = (
        f"https://{host}/v1/projects/{PROJECT}/locations/{LOCATION}"
        f"/publishers/google/models/{model}:generateContent"
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "maxOutputTokens": max_output_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode())
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text") or "" for p in parts)
    usage = data.get("usageMetadata") or {}
    pt = int(usage.get("promptTokenCount") or 0)
    ot = int(usage.get("candidatesTokenCount") or usage.get("totalTokenCount") or 0)
    # parse json
    import re

    m = re.search(r"\{.*\}", text, re.DOTALL)
    parsed = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            parsed = {}
    return (parsed if isinstance(parsed, dict) else {}), pt, ot


def run_condition(
    name: str,
    records: list[dict],
    systems: list[str],
    model: str,
    workers: int,
    max_spend: float,
    spend_so_far: float,
) -> tuple[dict, float]:
    pin, pout = PRICE.get(model, (0.30, 2.50))
    preds = [""] * len(records)
    pts = [0] * len(records)
    ots = [0] * len(records)
    ok = [False] * len(records)
    spent = spend_so_far
    stop = False

    def one(i: int) -> tuple[int, str, int, int, bool]:
        user = next(m["content"] for m in records[i]["messages"] if m["role"] == "user")
        last = ""
        for attempt in range(5):
            try:
                parsed, pt, ot = call_gemini(model, systems[i], user)
                return i, json.dumps(parsed, ensure_ascii=False) if parsed else "", pt, ot, True
            except Exception as exc:
                last = str(exc)
                if "429" in last or "500" in last or "503" in last:
                    time.sleep(min(2**attempt, 12) + random.random())
                    continue
                break
        return i, "", 0, 0, False

    t0 = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, i) for i in range(len(records))]
        for fut in as_completed(futs):
            i, text, pt, ot, succeeded = fut.result()
            preds[i] = text
            pts[i] = pt
            ots[i] = ot
            ok[i] = succeeded
            cost = pt / 1e6 * pin + ot / 1e6 * pout
            spent += cost
            done += 1
            if spent >= max_spend:
                stop = True
            if done == 1 or done % 20 == 0 or done == len(records):
                parsed = parse_action(text)
                gold = records[i]["gold_action"]
                hit = actions_equal(parsed, Action(**gold)) if parsed else False
                rate = done / max(time.perf_counter() - t0, 1e-6)
                print(
                    f"  [{name}] {done}/{len(records)} ok={sum(ok)} "
                    f"~${spent:.3f} {rate:.1f}/s last={'HIT' if hit else 'MISS'}",
                    flush=True,
                )
            if stop:
                break

    elapsed = time.perf_counter() - t0
    scored = evaluate_predictions(records, preds)
    # terminate slice
    term_idx = [
        i for i, r in enumerate(records) if (r.get("gold_action") or {}).get("type") == "terminate"
    ]
    term_hit = 0
    for i in term_idx:
        pred = parse_action(preds[i])
        if pred and pred.type == "terminate":
            term_hit += 1
    type_hit = 0
    for r, p in zip(records, preds):
        pred = parse_action(p)
        if pred and pred.type == (r.get("gold_action") or {}).get("type"):
            type_hit += 1

    hits = []
    for r, p in zip(records, preds):
        pred = parse_action(p)
        hits.append(bool(pred and actions_equal(pred, Action(**r["gold_action"]))))

    out = {
        "name": name,
        "elapsed_s": round(elapsed, 2),
        "spent_usd": round(spent - spend_so_far, 4),
        "prompt_tokens": sum(pts),
        "output_tokens": sum(ots),
        "n_ok": sum(ok),
        "hits": hits,
        "preds": preds,
        "metrics": scored.as_dict(),
        "action_type_acc": type_hit / max(len(records), 1),
        "terminate_n": len(term_idx),
        "terminate_type_recall": (term_hit / len(term_idx)) if term_idx else None,
        "budget_stop": stop,
    }
    print(format_report(scored, f"{model} — {name} ({elapsed:.1f}s ~${out['spent_usd']:.3f})"))
    print(
        f"    type_acc={out['action_type_acc']:.3f} "
        f"terminate_recall={out['terminate_type_recall']} (n={out['terminate_n']})",
        flush=True,
    )
    return out, spent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--sessions", type=int, default=12)
    ap.add_argument("--max-examples", type=int, default=100)
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--max-spend", type=float, default=5.0)
    ap.add_argument(
        "--out",
        default=str(USERSIM / "results" / "probe_history_persona.json"),
    )
    args = ap.parse_args()

    # Prefer UserSim ADC
    adc = USERSIM / "secrets" / "vertex_adc.json"
    if adc.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc)
    os.environ.setdefault("GCP_PROJECT", PROJECT)
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)

    test_path = OPERA / "data/processed/test.jsonl"
    records_all = [json.loads(l) for l in test_path.read_text().splitlines()]
    personas = load_personas()
    records = take_sessions(records_all, args.sessions, args.max_examples)
    # keep only rows with persona
    records = [r for r in records if user_key(r["session_id"]) in personas]
    if not records:
        raise SystemExit("no records with matched personas")

    avg_chars = sum(len(r.get("prompt_text") or "") for r in records) / len(records)
    est = estimate_cost(len(records) * 2, avg_chars, args.model)
    print(
        f"Model={args.model} n={len(records)} sessions="
        f"{len({r['session_id'] for r in records})} "
        f"workers={args.workers} est≈${est:.2f} cap=${args.max_spend:.2f}",
        flush=True,
    )
    if est > args.max_spend * 0.95:
        raise SystemExit(f"estimated ${est:.2f} exceeds cap ${args.max_spend:.2f} — shrink slice")

    # auth smoke
    creds = vertex_credentials()
    print(f"ADC ok token={bool(creds.token)}", flush=True)

    oracle = evaluate_predictions(
        records, [json.dumps(r["gold_action"], ensure_ascii=False) for r in records]
    )
    print(format_report(oracle, "oracle"))
    if oracle.session_macro_accuracy < 1.0:
        raise SystemExit("oracle failed")

    sys_hist = SYSTEM_PROMPT
    systems_hist = [sys_hist] * len(records)
    systems_pers = []
    for r in records:
        p = personas[user_key(r["session_id"])]
        systems_pers.append(SYSTEM_PROMPT + "\n\n" + persona_block(p))

    results = {
        "model": args.model,
        "n": len(records),
        "n_sessions": len({r["session_id"] for r in records}),
        "max_spend": args.max_spend,
        "conditions": [],
    }
    spent = 0.0
    t_wall = time.perf_counter()

    for name, systems in (
        ("history_only", systems_hist),
        ("history_plus_persona", systems_pers),
    ):
        remaining = args.max_spend - spent
        if remaining <= 0.05:
            print("budget exhausted — skipping", name)
            break
        print(f"\n=== {name} remaining=${remaining:.2f} ===", flush=True)
        row, spent = run_condition(
            name, records, systems, args.model, args.workers, args.max_spend, spent
        )
        results["conditions"].append(row)

    results["elapsed_s"] = round(time.perf_counter() - t_wall, 2)
    results["total_spend_usd"] = round(spent, 4)

    # paired stats: McNemar + clustered bootstrap on the same records
    by = {c["name"]: c for c in results["conditions"]}
    if "history_only" in by and "history_plus_persona" in by:
        ha = by["history_only"]["hits"]
        hb = by["history_plus_persona"]["hits"]
        b01 = sum(1 for a, x in zip(ha, hb) if not a and x)  # persona fixed it
        b10 = sum(1 for a, x in zip(ha, hb) if a and not x)  # persona broke it
        agree = sum(1 for a, x in zip(ha, hb) if a == x)
        sids = [r["session_id"] for r in records]
        uniq = sorted(set(sids))
        idx_by_sid = defaultdict(list)
        for i, s in enumerate(sids):
            idx_by_sid[s].append(i)

        def macro(hits: list[bool], sessions: list[str]) -> float:
            vals = []
            for s in sessions:
                idxs = idx_by_sid[s]
                vals.append(sum(hits[i] for i in idxs) / len(idxs))
            return sum(vals) / len(vals) if vals else 0.0

        rng = random.Random(0)
        deltas = []
        for _ in range(3000):
            samp = [uniq[rng.randrange(len(uniq))] for _ in uniq]
            deltas.append(macro(hb, samp) - macro(ha, samp))
        deltas.sort()
        results["paired"] = {
            "n_agree": agree,
            "persona_fixed": b01,
            "persona_broke": b10,
            "micro_delta": (sum(hb) - sum(ha)) / len(ha),
            "macro_delta": macro(hb, uniq) - macro(ha, uniq),
            "macro_delta_ci95_clustered": [
                deltas[int(0.025 * len(deltas))],
                deltas[int(0.975 * len(deltas))],
            ],
        }
        print(
            f"\nPAIRED: agree={agree}/{len(ha)} persona_fixed={b01} persona_broke={b10} "
            f"macro_delta={results['paired']['macro_delta']:+.4f} "
            f"CI95={[round(x, 4) for x in results['paired']['macro_delta_ci95_clustered']]}",
            flush=True,
        )
        a = by["history_only"]["metrics"]["session_macro_accuracy"]
        b = by["history_plus_persona"]["metrics"]["session_macro_accuracy"]
        results["delta_session_macro"] = b - a
        results["delta_action_type"] = (
            by["history_plus_persona"]["action_type_acc"] - by["history_only"]["action_type_acc"]
        )
        ta = by["history_only"].get("terminate_type_recall")
        tb = by["history_plus_persona"].get("terminate_type_recall")
        results["delta_terminate_recall"] = (
            None if ta is None or tb is None else tb - ta
        )
        print(
            f"\nDELTA session_macro (persona - hist) = {results['delta_session_macro']:+.4f} "
            f"type={results['delta_action_type']:+.4f} "
            f"term={results['delta_terminate_recall']}",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out} total_spend=${spent:.3f} wall={results['elapsed_s']}s")


if __name__ == "__main__":
    main()
