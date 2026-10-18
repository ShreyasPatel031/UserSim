"""Per-person pilot: can added data predict an individual reviewer's ease-of-use rating for a product the model
knows less well?  New-product framing: no target-product reviews are ever shown.

Products: Freshsales, Zoho CRM, Pipedrive (CRM; mutual competitors). Insightly was the first pick but its site
returns 403 to automated requests, so it was replaced rather than worked around.

Cases: 30 reviewers per product, balanced 10/10/10 across ease bands (1-3, 4, 5), each with usable context and one
clear stated task. Visible per case: role, industry, company-size band, tenure band, neutral task. Hidden: rating.

Setups (same predictor, prompt template and cases):
  P0 M (name + seed)   P1 M+D   P2 M+D+O   P3 M+D+O+C   P4 M+D+C
Baselines (no LLM): always-5, competitor-pack rating distribution, and a smoothed attribute model fitted on
reviewers of the other 63 products (role family, company size, tenure, industry).

Commands (repo root):
    python experiments/staged_context/per_person.py prepare
    python experiments/staged_context/per_person.py select
    python experiments/staged_context/per_person.py predict
    python experiments/staged_context/per_person.py score
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import experiment as E  # noqa: E402
import matched as MT  # noqa: E402

POUT = E.OUT / "per_person"
PPACKS = POUT / "packs"
PHIDDEN = POUT / "hidden"
PRODUCTS = ["Freshsales", "Zoho CRM", "Pipedrive"]
NAME_PATTERNS = {"Freshsales": r"\bfresh\s?sales\b|\bfreshworks\b", "Zoho CRM": r"\bzoho\b", "Pipedrive": r"\bpipe\s?drive\b"}
SEED_SENTENCE = {
    "Freshsales": "Freshsales is a web-based customer relationship management (CRM) application for sales teams.",
    "Zoho CRM": "Zoho CRM is a web-based customer relationship management (CRM) application.",
    "Pipedrive": "Pipedrive is a web-based sales customer relationship management (CRM) application.",
}
PAGES = {
    "Freshsales": {"landing": "https://www.freshworks.com/crm/sales/", "features": "https://www.freshworks.com/crm/features/"},
    "Zoho CRM": {"landing": "https://www.zoho.com/crm/", "features": "https://www.zoho.com/crm/features.html"},
    "Pipedrive": {"landing": "https://www.pipedrive.com/en", "features": "https://www.pipedrive.com/en/features"},
}
BANDS = {"low_1_3": (1, 2, 3), "four": (4,), "five": (5,)}
PER_BAND = 10
SETUPS = {"P0": [], "P1": ["D"], "P2": ["D", "O"], "P3": ["D", "O", "C"], "P4": ["D", "C"]}
SCREEN_MODEL = "gemini-2.5-flash"
PREDICT_THINKING = 1024
SEED = 42


def band(r: int) -> str:
    return next(k for k, v in BANDS.items() if r in v)


# ----------------------------------------------------------------------------- packs


def _rows(df: pd.DataFrame) -> dict:
    out = {}
    for rd in df[df.product_name.isin(PRODUCTS)].to_dict("records"):
        rd = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rd.items()}
        rd["norm"] = E.norm_text(E.review_prose(rd))
        out[rd["review_id"]] = rd
    return out


def prepare() -> None:
    """Pages -> D, dedup clusters, C packs (from rows that can never become cases), O via the shared mapper."""
    df, meta = E.load_capterra()
    rows = _rows(df)
    cluster = E.cluster_duplicates(list(rows.values()))
    members: dict = {}
    for rid, c in cluster.items():
        members.setdefault(c, []).append(rid)
    keep = {min(m, key=E.sha) for m in members.values()}
    # Per product: hash order; first half of the order is the case-candidate partition, the rest is evidence pool.
    split = {}
    for p in PRODUCTS:
        ids = sorted((i for i in keep if rows[i]["product_name"] == p), key=lambda i: E.sha(f"{SEED}|pp|{p}|{i}"))
        split[p] = {"candidates": ids[: len(ids) // 2], "pool": ids[len(ids) // 2:]}
    E.write_json(POUT / "split.json", {"seed": SEED, "source": meta, "dropped_duplicates": len(rows) - len(keep),
                                       "partition": "per product sha256 order; first half case candidates, rest evidence pool",
                                       "products": {p: {k: len(v) for k, v in s.items()} for p, s in split.items()},
                                       "ids": split})
    captured = {}
    for p, pages in PAGES.items():
        captured[p] = {}
        for page, url in pages.items():
            dest = E.CACHE / "pages" / f"{p.replace(' ', '_')}_{page}.html"
            E.download(url, dest)
            html = dest.read_text(encoding="utf-8", errors="ignore")
            sents, dropped = E.filter_sentences(E.page_text(html))
            captured[p][page] = {"url": url, "html_sha256": E.sha(html), "sentences": sents, "dropped": dropped,
                                 "captured": datetime.fromtimestamp(dest.stat().st_mtime, timezone.utc).date().isoformat()}
    E.PRODUCTS, E.PEER_OVERVIEW = PRODUCTS, {p: "landing" for p in PRODUCTS}  # build_D reads these globals
    try:
        D = E.build_D(captured)
    finally:
        E.PRODUCTS, E.PEER_OVERVIEW = ["Asana", "Trello", "ClickUp"], {"Asana": "landing", "Trello": "features", "ClickUp": "landing"}
    manifest = {"products": {}}
    for t in PRODUCTS:
        items = []
        for src in (x for x in PRODUCTS if x != t):
            cands = [rows[i] for i in split[src]["pool"] if rows[i]["norm"]]
            cands.sort(key=lambda r: E.sha(f"{SEED}|C|{src}|{r['review_id']}"))
            for r in cands[: E.N_PACK]:
                text, info = E.format_review(r, NAME_PATTERNS[t])
                items.append({"id": f"C:{r['review_id']}", "review_id": r["review_id"], "product": src, "text": text,
                              "tokens": E.approx_tokens(text), **info, "ease_of_use_rating": r.get("ease_of_use_rating")})
        packs = {"M": {"items": [{"id": f"M:{t}", "text": f"Product: {t}. {SEED_SENTENCE[t]}"}]}, "D": D[t],
                 "C": {"items": items}}
        for k, v in packs.items():
            E.write_json(PPACKS / t / f"{k}.json", v)
        o = E.onet_pack(t, D[t], SEED_SENTENCE[t])
        E.write_json(PPACKS / t / "O.json", o)
        manifest["products"][t] = {k: E.pack_summary(k, v) for k, v in {**packs, "O": o}.items()}
        manifest["products"][t]["D"]["sources"] = D[t]["sources"]
    E.write_json(POUT / "evidence_manifest.json", manifest)
    print(json.dumps({t: {k: v.get("tokens_approx") for k, v in m.items()} for t, m in manifest["products"].items()}, indent=1))


# ----------------------------------------------------------------------------- case selection


def _screen(p: str, r: dict) -> dict:
    text = E.review_for_extraction(r)
    rec = E.call_model("pp_screen", SCREEN_MODEL, MT.SCREEN_SYSTEM, MT.SCREEN_PROMPT.format(product=p, review=text),
                       temperature=0.0, seed=42, max_tokens=4096, thinking_budget=512)
    s = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    ok = bool(s.get("eligible")) and isinstance(s.get("task"), dict) and bool(s.get("neutral_task"))
    reason = s.get("reason") or rec.get("error")
    if ok and MT.LEAK.search(s["neutral_task"]):
        ok, reason = False, "neutral_task contained evaluative wording: " + MT.LEAK.search(s["neutral_task"]).group(0)
    if ok and not E.span_ok(s.get("span", ""), text):
        ok, reason = False, "task span not verbatim"
    return {"ok": ok, "reason": reason, "screen": s}


def select() -> None:
    """Walk each product's candidate partition in hash order, filling 10 cases per ease band.
    Screening (task clarity, neutral wording) never sees the rating; the band only decides which quota a row fills."""
    split = E.read_json(POUT / "split.json")["ids"]
    df, _ = E.load_capterra()
    rows = _rows(df)
    cards, answers, log = [], [], []
    for p in PRODUCTS:
        need = {b: PER_BAND for b in BANDS}
        queue = [rows[i] for i in split[p]["candidates"] if MT.context_ok(rows[i])]
        log += [{"review_id": i, "product": p, "eligible": False, "reason": "missing context or rating"}
                for i in split[p]["candidates"] if not MT.context_ok(rows[i])]
        pos = 0
        while any(need.values()) and pos < len(queue):
            batch = []
            while len(batch) < E.WORKERS and pos < len(queue):
                r = queue[pos]
                pos += 1
                b = band(int(r["ease_of_use_rating"]))
                if need[b] > 0:
                    batch.append((r, b))
            with ThreadPoolExecutor(E.WORKERS) as pool:
                results = list(pool.map(lambda rb: _screen(p, rb[0]), batch))
            for (r, b), res in zip(batch, results):
                log.append({"review_id": r["review_id"], "product": p, "band": b, "eligible": res["ok"], "reason": res["reason"]})
                if res["ok"] and need[b] > 0:
                    need[b] -= 1
                    card = MT.case_card(r, res["screen"])
                    cards.append(card)
                    answers.append({"case_id": card["case_id"], "review_id": r["review_id"], "product": p,
                                    "ease_of_use_rating": int(r["ease_of_use_rating"]), "band": b,
                                    "task_span": res["screen"].get("span"), "pros": r.get("pros"), "cons": r.get("cons")})
        print(p, "unfilled quota:", {k: v for k, v in need.items() if v})
    E.write_json(POUT / "cases.json", {"seed": SEED, "per_band": PER_BAND, "bands": BANDS, "screen_model": SCREEN_MODEL,
                                       "cases": cards})
    E.write_jsonl(PHIDDEN / "answers.jsonl", answers)
    E.write_jsonl(POUT / "screening_log.jsonl", log)
    pool_ids = {i for p in PRODUCTS for i in split[p]["pool"]}
    c_ids = {x["review_id"] for t in PRODUCTS for x in E.read_json(PPACKS / t / "C.json")["items"]}
    case_ids = {a["review_id"] for a in answers}
    checks = {"cases_disjoint_from_pool": not (case_ids & pool_ids), "c_packs_from_pool": c_ids <= pool_ids,
              "no_target_mentions_in_C": all(not re.search(NAME_PATTERNS[t], x["text"], re.I)
                                             for t in PRODUCTS for x in E.read_json(PPACKS / t / "C.json")["items"])}
    E.write_json(POUT / "leakage_checks.json", checks)
    print(f"selected {len(cards)} cases; screened {len(log)}; checks {checks}")


# ----------------------------------------------------------------------------- prediction

PRED_PROMPT = """A reviewer of {product} described this situation. Predict the ease-of-use rating (1-5) this specific person
gave {product} in their review. Their review is hidden; you only know the context below.

Reviewer and task (as stated by the reviewer; normalized):
- Role: {role_title} (family: {role_family})
- Industry: {industry}
- Company size: {company_size_band}
- Time using {product}: {tenure_band}
- Task: {neutral_task}

Return {{"ease_of_use_probabilities_1_to_5": [p1, p2, p3, p4, p5], "likely_frictions": [str], "rationale": str}}
Probabilities in [0,1] summing to 1. Up to 3 short likely frictions for this person.

Evidence:
"""


def _predict_one(card: dict, setup: str, packs: dict) -> dict:
    parts = [PRED_PROMPT.format(**card)]
    for k in ["M"] + SETUPS[setup]:
        parts.append(f"## {E.PACK_HEADINGS[k]}\n{E.pack_text(k, packs[k])}\n")
    user = "\n".join(parts)
    for attempt in range(2):
        rec = E.call_model("pp_predict", E.PREDICT_MODEL, MT.PRED_SYSTEM, user, temperature=E.PREDICT_TEMPERATURE,
                           seed=1000 + attempt, max_tokens=8192, thinking_budget=PREDICT_THINKING,
                           key_extra=f"{card['case_id']}|{setup}|1")
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        probs = j.get("ease_of_use_probabilities_1_to_5")
        valid = (isinstance(probs, list) and len(probs) == 5 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in probs)
                 and abs(sum(probs) - 1) <= 0.02)
        if valid:
            break
    return {"case_id": card["case_id"], "product": card["product"], "setup": setup, "valid": valid,
            "error": rec.get("error") if not valid else None,
            "probs": [x / sum(probs) for x in probs] if valid else None,
            "likely_frictions": j.get("likely_frictions"), "rationale": j.get("rationale"),
            "input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"], "cost_usd": rec["cost_usd"]}


def predict() -> None:
    cards = E.read_json(POUT / "cases.json")["cases"]
    packs = {p: {k: E.read_json(PPACKS / p / f"{k}.json") for k in "MDOC"} for p in PRODUCTS}
    jobs = [(c, s) for c in cards for s in SETUPS]
    with ThreadPoolExecutor(E.WORKERS) as pool:
        preds = list(pool.map(lambda cs: _predict_one(cs[0], cs[1], packs[cs[0]["product"]]), jobs))
    E.write_jsonl(POUT / "predictions.jsonl", preds)
    print(f"{sum(p['valid'] for p in preds)}/{len(preds)} valid; spend so far ${E.spent_usd():.3f}")


# ----------------------------------------------------------------------------- baselines + scoring


def attribute_baseline(df: pd.DataFrame, cards: list[dict]) -> dict:
    """No-LLM per-person model fitted on the other 63 products: global mean + shrunk per-attribute deviations."""
    train = df[~df.product_name.isin(PRODUCTS)].dropna(subset=["ease_of_use_rating"]).copy()
    train["role_family"] = train.reviewer_job_title.fillna("").map(E.role_family)
    feats = {"role_family": "role_family", "company_size_band": "reviewer_company_size",
             "tenure_band": "reviewer_time_used_product", "industry": "reviewer_industry"}
    mu, k = train.ease_of_use_rating.mean(), 20.0
    effects = {}
    for card_key, col in feats.items():
        g = train.groupby(col).ease_of_use_rating.agg(["sum", "count"])
        effects[card_key] = ((g["sum"] + k * mu) / (g["count"] + k) - mu).to_dict()
    out = {}
    for c in cards:
        out[c["case_id"]] = float(np.clip(mu + sum(effects[f].get(c[f], 0.0) for f in feats), 1, 5))
    return {"mean": mu, "pred": out, "n_train": int(len(train))}


def probs_around(x: float) -> list[float]:
    """Point forecast -> distribution on the two nearest ratings (for RPS)."""
    lo = int(math.floor(x))
    p = [0.0] * 5
    if lo >= 5:
        p[4] = 1.0
    else:
        p[lo - 1] += 1 - (x - lo)
        p[lo] += x - lo
    return p


def auc(scores: list[float], labels: list[int]) -> float | None:
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(set(x)) < 2:
        return None
    rx, ry = pd.Series(x).rank(), pd.Series(y).rank()
    return float(np.corrcoef(rx, ry)[0, 1])


def metrics(name: str, rows: list[dict]) -> dict:
    """rows: {'y', 'probs'}. Per-person scores."""
    y = [r["y"] for r in rows]
    exp = [sum((k + 1) * p for k, p in enumerate(r["probs"])) for r in rows]
    low_score = [-e for e in exp]  # lower expected rating = more likely an unhappy (<=3) reviewer
    em = [E.ease_metrics(r["probs"], [r["y"]]) for r in rows]
    return {"setup": name, "n": len(rows), "mae": float(np.mean([m["ease_mae"] for m in em])),
            "rps": float(np.mean([m["ease_rps"] for m in em])), "spearman": spearman(exp, y),
            "auc_low": auc(low_score, [int(v <= 3) for v in y]), "mean_pred": float(np.mean(exp)),
            "pred_spread_sd": float(np.std(exp))}


def score() -> None:
    cards = {c["case_id"]: c for c in E.read_json(POUT / "cases.json")["cases"]}
    ans = {a["case_id"]: a for a in E.read_jsonl(PHIDDEN / "answers.jsonl")}
    preds = [p for p in E.read_jsonl(POUT / "predictions.jsonl") if p["valid"]]
    df, _ = E.load_capterra()
    base = attribute_baseline(df, list(cards.values()))
    out, per_case = [], []
    groups = {"ALL": PRODUCTS, **{p: [p] for p in PRODUCTS}}
    for gname, prods in groups.items():
        ids = [c for c in cards if cards[c]["product"] in prods]
        for s in SETUPS:
            rows = [{"y": ans[p["case_id"]]["ease_of_use_rating"], "probs": p["probs"]}
                    for p in preds if p["setup"] == s and p["case_id"] in ids]
            if rows:
                out.append({"group": gname, **metrics(s, rows)})
        cpack = {p: [int(x["ease_of_use_rating"]) for x in E.read_json(PPACKS / p / "C.json")["items"]
                     if x.get("ease_of_use_rating") in (1, 2, 3, 4, 5)] for p in prods}
        bl = {
            "BASE_always_5": [{"y": ans[c]["ease_of_use_rating"], "probs": [0, 0, 0, 0, 1]} for c in ids],
            "BASE_competitor_reviews": [{"y": ans[c]["ease_of_use_rating"],
                                         "probs": [cpack[cards[c]["product"]].count(k) / len(cpack[cards[c]["product"]])
                                                   for k in range(1, 6)]} for c in ids],
            "BASE_attribute_model": [{"y": ans[c]["ease_of_use_rating"], "probs": probs_around(base["pred"][c])} for c in ids],
        }
        for name, rows in bl.items():
            out.append({"group": gname, **metrics(name, rows)})
    for p in preds:
        a = ans[p["case_id"]]
        per_case.append({"case_id": p["case_id"], "product": p["product"], "setup": p["setup"],
                         "hidden_rating": a["ease_of_use_rating"],
                         "pred_expected": sum((k + 1) * x for k, x in enumerate(p["probs"])),
                         "attribute_model": base["pred"][p["case_id"]]})
    with (POUT / "metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    pd.DataFrame(per_case).to_csv(POUT / "per_case.csv", index=False)
    # paired bootstrap over cases (ALL) for absolute error deltas vs P0
    by = {(p["case_id"], p["setup"]): p for p in preds}
    rng = np.random.default_rng(42)
    boot = {}
    ids = list(cards)
    for s in SETUPS:
        if s == "P0":
            continue
        common = [c for c in ids if (c, s) in by and (c, "P0") in by]

        def err(c, st):
            pr = by[(c, st)]["probs"]
            return abs(sum((k + 1) * x for k, x in enumerate(pr)) - ans[c]["ease_of_use_rating"])
        d = np.array([err(c, s) - err(c, "P0") for c in common])
        bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        boot[f"{s}-P0"] = {"mean_abs_err_delta": float(d.mean()), "ci95": [float(np.percentile(bs, 2.5)),
                                                                          float(np.percentile(bs, 97.5))], "n": len(common)}
    E.write_json(POUT / "bootstrap.json", boot)
    E.write_json(POUT / "attribute_baseline.json", {"global_mean": base["mean"], "n_train": base["n_train"],
                                                    "shrinkage_k": 20, "fit_on": "63 other products"})
    m = pd.DataFrame(out)
    print(m[m.group == "ALL"].round(3).to_string(index=False))
    print(json.dumps(boot, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "select", "predict", "score"])
    a = ap.parse_args()
    {"prepare": prepare, "select": select, "predict": predict, "score": score}[a.cmd]()


if __name__ == "__main__":
    main()
