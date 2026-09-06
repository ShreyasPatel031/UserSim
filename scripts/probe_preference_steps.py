#!/usr/bin/env python3
"""Isolate preference-bearing steps and test persona there.

Full-HTML next-action prediction is grounding-dominated: the model must copy one
exact name= out of ~300 candidates, so persona cannot move it. This probe strips
the grounding problem away and keeps only the choice:

  "Here are the K products/options visible. Which one does THIS shopper click?"

Steps used (genuine choice among comparable alternatives):
  - click_type == product_link    (which listing to open)
  - click_type == product_option  (which colour/size/variant)

Arms (identical candidate set + identical task history):
  A. history only
  B. history + real OPeRA persona

Metric: top-1 choice accuracy, paired McNemar + clustered bootstrap.
Prompts are small, so this costs cents.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import comb
from pathlib import Path

USERSIM = Path(__file__).resolve().parents[1]
OPERA = Path("/Users/shreyaspatel/Opera Human Behaviour Simulation")
sys.path.insert(0, str(USERSIM / "src"))
sys.path.insert(0, str(OPERA))

from auth import vertex_credentials  # noqa: E402

PROJECT = os.environ.get("GCP_PROJECT", "project-amer-scs-sandbox")
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
PRICE = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

NAME_RE = re.compile(r'name="([^"]+)"')
LIST_PREFIXES = ("active_item_list.", "search_results.", "product_list.")
OPTION_PREFIX = "product_options."


def user_key(session_id: str) -> str:
    sid = session_id or ""
    return sid.split("_20")[0] if "_20" in sid else sid.split("_")[0]


def humanize(slug: str) -> str:
    return re.sub(r"\s+", " ", slug.replace("_", " ")).strip()


def product_slug(name: str) -> str | None:
    """active_item_list.<slug>.product_detail -> <slug>"""
    for pre in LIST_PREFIXES:
        if name.startswith(pre):
            rest = name[len(pre) :]
            # strip trailing element role (.product_detail, .price, .image, ...)
            parts = rest.split(".")
            return parts[0] if parts else None
    return None


def option_slug(name: str) -> str | None:
    """product_options.color.button_list.<slug> -> color::<slug>"""
    if not name.startswith(OPTION_PREFIX):
        return None
    rest = name[len(OPTION_PREFIX) :]
    parts = rest.split(".")
    if len(parts) < 2:
        return None
    family = parts[0]
    leaf = parts[-1]
    return f"{family}::{leaf}"


def candidates_for(row: dict, kind: str) -> tuple[str | None, dict[str, str]]:
    """Return (gold_key, {key: full_name}) deduped to distinct products/options."""
    user_msg = next(m["content"] for m in row["messages"] if m["role"] == "user")
    names = set(NAME_RE.findall(user_msg))
    keyfn = product_slug if kind == "product_link" else option_slug
    by_key: dict[str, str] = {}
    for n in sorted(names):
        k = keyfn(n)
        if not k:
            continue
        by_key.setdefault(k, n)
    gold_name = (row.get("gold_action") or {}).get("name") or ""
    gold_key = keyfn(gold_name)
    if not gold_key or gold_key not in by_key:
        return None, {}
    return gold_key, by_key


def build_history(rows_by_session: dict[str, list[dict]], row: dict, max_steps: int = 8) -> str:
    """Compact prior-action trace for the same session (no HTML)."""
    sid = row["session_id"]
    idx = int(row["step_index"])
    prior = [r for r in rows_by_session[sid] if int(r["step_index"]) < idx]
    prior.sort(key=lambda r: int(r["step_index"]))
    prior = prior[-max_steps:]
    if not prior:
        return "(this is the first action of the session)"
    lines = []
    for r in prior:
        g = r.get("gold_action") or {}
        t = g.get("type")
        if t == "type_and_submit":
            lines.append(f'- searched: "{g.get("text") or ""}"')
        elif t == "click":
            nm = g.get("name") or ""
            slug = product_slug(nm) or option_slug(nm) or nm
            lines.append(f"- clicked: {humanize(str(slug))[:90]}")
        else:
            lines.append(f"- {t}")
    return "\n".join(lines)


def persona_block(p: dict) -> str:
    priorities = ", ".join(p.get("priorities") or []) or "value and reviews"
    avoids = ", ".join(p.get("avoids") or []) or "unclear listings"
    personality = p.get("personality") or {}
    pers = ", ".join(f"{k}={v}" for k, v in personality.items()) if personality else ""
    lines = [
        "THE SHOPPER (real person, from panel data):",
        f"- {p.get('label') or ''}",
        f"- {p.get('bio') or ''}",
        f"- age {p.get('age') or '?'}, {p.get('city') or '?'}, {p.get('gender') or '?'}",
        f"- income {p.get('income') or '?'}, employment {p.get('employment') or '?'}",
        f"- budget {p.get('budget') or '?'}, Prime {p.get('prime') or '?'}, shops {p.get('shop_frequency') or '?'}",
        f"- cares about: {priorities}",
        f"- avoids: {avoids}",
    ]
    if pers:
        lines.append(f"- personality: {pers}")
    return "\n".join(lines)


SYSTEM_BASE = """You predict which option a real online shopper clicks next.

You are given the shopper's recent actions in this session and a numbered list of
the comparable choices visible on the current Amazon page.

Reply with ONE JSON object and nothing else:
{"choice": <integer index from the list>}
"""

SYSTEM_PERSONA_HINT = """
Use the shopper's profile to decide. Different people pick different options from
the same list; predict THIS person's pick, not the objectively best option.
"""


SYSTEM_DEMO_HINT = """
You will first see solved examples: other shoppers' choice sets and the option a
real human actually picked. Use them to calibrate how real shoppers choose.
"""


def demo_block(demos: list[dict]) -> str:
    out = ["SOLVED EXAMPLES (real human picks):"]
    for d in demos:
        out.append("")
        for i, opt in enumerate(d["options"]):
            out.append(f"  {i}. {opt[:120]}")
        out.append(f"  -> human picked: {d['gold_index']}")
    out.append("")
    return "\n".join(out)


def build_prompt(
    history: str,
    options: list[str],
    persona: dict | None,
    demos: list[dict] | None = None,
) -> tuple[str, str]:
    system = SYSTEM_BASE + (SYSTEM_PERSONA_HINT if persona else "")
    if demos:
        system += SYSTEM_DEMO_HINT
    parts = []
    if demos:
        parts.append(demo_block(demos))
    if persona:
        parts.append(persona_block(persona))
        parts.append("")
    parts.append("RECENT ACTIONS THIS SESSION:")
    parts.append(history)
    parts.append("")
    parts.append("CHOICES VISIBLE NOW:")
    for i, opt in enumerate(options):
        parts.append(f"{i}. {opt[:180]}")
    parts.append("")
    parts.append("Which index does this shopper click?")
    return system, "\n".join(parts)


def call_gemini(model: str, system: str, user: str) -> tuple[dict, int, int]:
    creds = vertex_credentials()
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
            "maxOutputTokens": 32,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text") or "" for p in parts)
    usage = data.get("usageMetadata") or {}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    parsed = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            parsed = {}
    return (
        parsed if isinstance(parsed, dict) else {},
        int(usage.get("promptTokenCount") or 0),
        int(usage.get("candidatesTokenCount") or 0),
    )


def run_arm(
    name: str,
    items: list[dict],
    with_persona: bool,
    model: str,
    workers: int,
    max_spend: float,
    spent: float,
    persona_field: str = "persona",
    demos: list[dict] | None = None,
) -> tuple[dict, float]:
    pin, pout = PRICE.get(model, (0.30, 2.50))
    hits = [False] * len(items)
    picks = [None] * len(items)
    pts = ots = 0
    stop = False

    def one(i: int):
        it = items[i]
        system, user = build_prompt(
            it["history"],
            it["options"],
            it[persona_field] if with_persona else None,
            demos=demos,
        )
        for attempt in range(5):
            try:
                parsed, pt, ot = call_gemini(model, system, user)
                return i, parsed.get("choice"), pt, ot
            except Exception as exc:
                s = str(exc)
                if any(c in s for c in ("429", "500", "503")):
                    time.sleep(min(2**attempt, 10) + random.random())
                    continue
                break
        return i, None, 0, 0

    t0 = time.perf_counter()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, i) for i in range(len(items))]
        for fut in as_completed(futs):
            i, choice, pt, ot = fut.result()
            pts += pt
            ots += ot
            spent += pt / 1e6 * pin + ot / 1e6 * pout
            picks[i] = choice
            try:
                hits[i] = int(choice) == items[i]["gold_index"]
            except (TypeError, ValueError):
                hits[i] = False
            done += 1
            if done % 50 == 0 or done == len(items):
                print(
                    f"  [{name}] {done}/{len(items)} acc={sum(hits)/done:.3f} ~${spent:.3f}",
                    flush=True,
                )
            if spent >= max_spend:
                stop = True
                break

    acc = sum(hits) / len(items)
    print(f"  {name}: top-1 acc = {acc:.4f}  ({sum(hits)}/{len(items)})  {time.perf_counter()-t0:.1f}s")
    return (
        {
            "name": name,
            "with_persona": with_persona,
            "acc": acc,
            "n_correct": sum(hits),
            "hits": hits,
            "picks": picks,
            "prompt_tokens": pts,
            "output_tokens": ots,
            "budget_stop": stop,
        },
        spent,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--kinds", default="product_link,product_option")
    ap.add_argument("--max-options", type=int, default=10)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--max-spend", type=float, default=1.0)
    ap.add_argument("--n-demos", type=int, default=4)
    ap.add_argument("--n-demo-options", type=int, default=6)
    ap.add_argument("--out", default=str(USERSIM / "results" / "probe_preference_steps.json"))
    args = ap.parse_args()

    adc = USERSIM / "secrets" / "vertex_adc.json"
    if adc.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc)

    rows = [json.loads(l) for l in (OPERA / "data/processed/test.jsonl").read_text().splitlines()]
    by_session: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_session[r["session_id"]].append(r)
    personas = {
        p["id"]: p for p in json.loads((OPERA / "data/opera_catalog.json").read_text())["personas"]
    }

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    rng = random.Random(7)
    items: list[dict] = []
    for r in rows:
        kind = r.get("click_type")
        if kind not in kinds:
            continue
        uid = user_key(r["session_id"])
        if uid not in personas:
            continue
        gold_key, by_key = candidates_for(r, kind)
        if not gold_key or len(by_key) < 3:
            continue
        others = [k for k in by_key if k != gold_key]
        rng.shuffle(others)
        keep = others[: max(0, args.max_options - 1)]
        keys = keep + [gold_key]
        rng.shuffle(keys)
        options = [humanize(k.split("::")[-1]) for k in keys]
        items.append(
            {
                "session_id": r["session_id"],
                "step_index": r["step_index"],
                "kind": kind,
                "n_candidates_page": len(by_key),
                "options": options,
                "gold_index": keys.index(gold_key),
                "history": build_history(by_session, r),
                "persona": personas[uid],
            }
        )
        if len(items) >= args.limit:
            break

    if not items:
        raise SystemExit("no preference-bearing items found")

    # Mismatched-persona control: a different real persona on the same step.
    # correct ~= shuffled  => the model is ignoring the persona text entirely.
    all_pids = sorted(personas)
    for it in items:
        own = it["persona"]["id"]
        other = own
        while other == own:
            other = all_pids[rng.randrange(len(all_pids))]
        it["persona_shuffled"] = personas[other]

    kind_counts: dict[str, int] = defaultdict(int)
    for it in items:
        kind_counts[it["kind"]] += 1
    chance = sum(1 / len(it["options"]) for it in items) / len(items)
    print(
        f"Model={args.model} items={len(items)} kinds={dict(kind_counts)} "
        f"sessions={len({it['session_id'] for it in items})} "
        f"chance≈{chance:.3f} workers={args.workers} cap=${args.max_spend:.2f}",
        flush=True,
    )
    creds = vertex_credentials()
    print(f"ADC ok token={bool(creds.token)}", flush=True)

    results = {
        "model": args.model,
        "n": len(items),
        "kinds": dict(kind_counts),
        "chance_acc": chance,
        "max_options": args.max_options,
        "arms": [],
    }
    spent = 0.0
    t0 = time.perf_counter()
    # SimBench-style cross-example demos, drawn from the TRAIN split (no leakage):
    # other shoppers' choice sets with the option a real human picked.
    demos: list[dict] = []
    train_rows = [
        json.loads(l) for l in (OPERA / "data/processed/train.jsonl").read_text().splitlines()
    ]
    for r in train_rows:
        kind = r.get("click_type")
        if kind not in kinds:
            continue
        gold_key, by_key = candidates_for(r, kind)
        if not gold_key or len(by_key) < 4:
            continue
        others = [k for k in by_key if k != gold_key]
        rng.shuffle(others)
        keys = others[: args.n_demo_options - 1] + [gold_key]
        rng.shuffle(keys)
        demos.append(
            {
                "options": [humanize(k.split("::")[-1]) for k in keys],
                "gold_index": keys.index(gold_key),
            }
        )
        if len(demos) >= args.n_demos:
            break
    print(f"demos built from train: {len(demos)}", flush=True)
    results["n_demos"] = len(demos)

    arms_spec = [
        ("history_only", False, "persona", None),
        ("history_plus_persona", True, "persona", None),
        ("history_plus_shuffled_persona", True, "persona_shuffled", None),
        ("history_plus_demos", False, "persona", demos),
        ("history_plus_demos_plus_persona", True, "persona", demos),
    ]
    for name, wp, field, dm in arms_spec:
        if args.max_spend - spent <= 0.02:
            print("budget exhausted")
            break
        print(f"\n=== {name} ===", flush=True)
        arm, spent = run_arm(
            name, items, wp, args.model, args.workers, args.max_spend, spent,
            persona_field=field, demos=dm,
        )
        results["arms"].append(arm)

    results["elapsed_s"] = round(time.perf_counter() - t0, 2)
    results["total_spend_usd"] = round(spent, 4)

    by = {a["name"]: a for a in results["arms"]}
    print("\n--- summary (chance %.4f) ---" % results["chance_acc"])
    for a in results["arms"]:
        print(f"  {a['name']:34s} {a['acc']:.4f}  ({a['n_correct']}/{len(items)})")
    if "history_plus_demos" in by and "history_only" in by:
        results["delta_demos"] = by["history_plus_demos"]["acc"] - by["history_only"]["acc"]
        print(f"  demos - history_only = {results['delta_demos']:+.4f}")
    if "history_plus_shuffled_persona" in by and "history_plus_persona" in by:
        sc = by["history_plus_shuffled_persona"]["acc"]
        cc = by["history_plus_persona"]["acc"]
        results["correct_minus_shuffled_persona"] = cc - sc
        print(
            f"\nPersona identity check: correct={cc:.4f} shuffled={sc:.4f} "
            f"delta={cc - sc:+.4f}  (≈0 => persona text is being ignored)",
            flush=True,
        )
    if "history_only" in by and "history_plus_persona" in by:
        ha, hb = by["history_only"]["hits"], by["history_plus_persona"]["hits"]
        b01 = sum(1 for a, b in zip(ha, hb) if not a and b)
        b10 = sum(1 for a, b in zip(ha, hb) if a and not b)
        n = b01 + b10
        p = (
            sum(comb(n, k) for k in range(0, min(b01, b10) + 1)) / 2**n * 2
            if n
            else 1.0
        )
        sids = [it["session_id"] for it in items]
        idx_by_sid = defaultdict(list)
        for i, s in enumerate(sids):
            idx_by_sid[s].append(i)
        uniq = sorted(idx_by_sid)

        def acc(hits, sessions):
            idxs = [i for s in sessions for i in idx_by_sid[s]]
            return sum(hits[i] for i in idxs) / len(idxs) if idxs else 0.0

        rng2 = random.Random(0)
        deltas = []
        for _ in range(3000):
            samp = [uniq[rng2.randrange(len(uniq))] for _ in uniq]
            deltas.append(acc(hb, samp) - acc(ha, samp))
        deltas.sort()
        results["paired"] = {
            "delta_acc": by["history_plus_persona"]["acc"] - by["history_only"]["acc"],
            "persona_fixed": b01,
            "persona_broke": b10,
            "mcnemar_p": min(p, 1.0),
            "delta_ci95_clustered": [
                deltas[int(0.025 * len(deltas))],
                deltas[int(0.975 * len(deltas))],
            ],
        }
        pr = results["paired"]
        print(
            f"\nPAIRED delta_acc={pr['delta_acc']:+.4f} "
            f"CI95=[{pr['delta_ci95_clustered'][0]:+.4f},{pr['delta_ci95_clustered'][1]:+.4f}] "
            f"fixed={b01} broke={b10} McNemar p={pr['mcnemar_p']:.3f}",
            flush=True,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {out} spend=${spent:.3f} wall={results['elapsed_s']}s")


if __name__ == "__main__":
    main()
