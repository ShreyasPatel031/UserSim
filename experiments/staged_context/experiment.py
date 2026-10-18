"""Staged-context pilot: which customer-context evidence improves product-level
predictions of held-out Capterra reviews (Asana, Trello, ClickUp)?

Commands (run from repo root):
    python experiments/staged_context/experiment.py prepare --seed 42
    python experiments/staged_context/experiment.py onet          # model: occupation mapping (pack O)
    python experiments/staged_context/experiment.py smoke         # model: S0+S4 on one product vs dev rows
    python experiments/staged_context/experiment.py predict --conditions all --repetitions 1
    python experiments/staged_context/experiment.py score         # model: extraction + blind judging
    python experiments/staged_context/experiment.py report

Prediction calls only read out/packs/. Hidden reviews live in out/hidden/ and are
read only by extraction/scoring.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import threading
import time
import unicodedata
from datetime import date, datetime, timezone
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = HERE / "cache"  # raw downloads (gitignored)
OUT = HERE / "out"
PACKS = OUT / "packs"
HIDDEN = OUT / "hidden"
CALLS = OUT / "calls"  # cached model requests/responses

DATASET_REPO = "FreshCrawl/capterra-b2b-software-reviews"
DATASET_REV = "fc7c316cae049cd9e445241b280209a2a140ed4c"
DATASET_FILE = "capterra_software_reviews.csv"
ONET_VERSION = "db_31_0_csv"
ONET_FILES = ["task_statements.csv", "occupation_data.csv"]

PRODUCTS = ["Asana", "Trello", "ClickUp"]
NAME_PATTERNS = {
    "Asana": r"\basana\b",
    "Trello": r"\btrello\b",
    "ClickUp": r"\bclick\s?-?up\b",
}
SEED_SENTENCE = {
    "Asana": "Asana is a web-based work and project management application for teams.",
    "Trello": "Trello is a board-and-card based visual task and project management application.",
    "ClickUp": "ClickUp is a web-based work management and productivity platform.",
}
PAGES = {
    "Asana": {"landing": "https://asana.com/", "features": "https://asana.com/features"},
    "Trello": {"landing": "https://trello.com/", "features": "https://trello.com/tour"},
    "ClickUp": {"landing": "https://clickup.com/", "features": "https://clickup.com/features"},
}
# Overview page used when the product is a competitor (Trello's landing page is mostly testimonials).
PEER_OVERVIEW = {"Asana": "landing", "Trello": "features", "ClickUp": "landing"}
PROSE_FIELDS = ["pros", "cons", "general_comments", "reasons_for_choosing", "reasons_for_switching"]
N_DEV, N_TEST, N_PACK = 5, 20, 10
CAP_D_TARGET, CAP_D_PEER, CAP_O, CAP_REVIEW = 1500, 500, 1000, 250
NEAR_DUP_JACCARD = 0.85

CONDITIONS = {
    "S0": [],
    "S1": ["D"],
    "S2": ["D", "O"],
    "S3": ["D", "O", "C"],
    "S4": ["D", "O", "C", "T"],
    "A1": ["D", "C"],
    "A2": ["D", "C", "T"],
    "A3": ["D", "T"],
}
COMPARISONS = [
    ("S1", "S0", "Did public pages help?"),
    ("S2", "S1", "Did O*NET help before reviews?"),
    ("S3", "S2", "Did competitor reviews help?"),
    ("S4", "S3", "Did target reviews help?"),
    ("S3", "A1", "Did O*NET help with competitor reviews? (S3 vs A1)"),
    ("S4", "A2", "Did O*NET help with both review sources? (S4 vs A2)"),
    ("A2", "A3", "Did competitors add value once target reviews existed? (A2 vs A3)"),
]

# USD per 1M tokens (list prices; thinking tokens billed as output).
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),
    "claude-sonnet-5-5": (3.00, 15.00),
    "claude-haiku-5-5": (1.00, 5.00),
}
PREDICT_MODEL = os.environ.get("EXP_PREDICT_MODEL", "gemini-2.5-flash")
JUDGE_MODEL = os.environ.get("EXP_JUDGE_MODEL", "gemini-2.5-pro")
SPEND_CAP = float(os.environ.get("EXP_SPEND_CAP_USD", "10"))
PREDICT_TEMPERATURE = 0.7
WORKERS = int(os.environ.get("EXP_WORKERS", "8"))  # parallel model calls
JUDGE_TEMPERATURE = 0.0
# Gemini 2.5 Pro thinking counts toward max_output_tokens; v1 judging (8192, dynamic thinking) truncated 24/48 sets.
JUDGE_MAX_TOKENS = 16384
JUDGE_THINKING_BUDGET = 2048


# ----------------------------------------------------------------------------- utils


def sha(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def approx_tokens(text: str) -> int:
    """Provider-neutral estimate (~4 chars/token). Actual usage is logged per call."""
    return math.ceil(len(text) / 4)


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def clean(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text())


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def download(url: str, dest: Path) -> Path:
    import requests

    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0 (research pilot)"})
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


# ----------------------------------------------------------------------------- model client


class SpendCapExceeded(RuntimeError):
    pass


_LOG_LOCK = threading.Lock()


def _ledger() -> list[dict]:
    with _LOG_LOCK:
        lines = (OUT / "call_log.jsonl").read_text().splitlines() if (OUT / "call_log.jsonl").exists() else []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # a line torn by an earlier concurrent writer
            continue
    return out


def spent_usd() -> float:
    return sum(r.get("cost_usd", 0.0) for r in _ledger() if not r.get("cached"))


def cost_of(model: str, inp: int, out: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return inp / 1e6 * pin + out / 1e6 * pout


def _vertex_generate(model, system, user, temperature, seed, max_tokens, thinking_budget=None):
    # Reuse the repo's existing Vertex client (src/model.py); credentials stay inside it.
    sys.path.insert(0, str(ROOT / "src"))
    from google.genai import types  # noqa: E402

    import model as repo_model  # noqa: E402

    client = repo_model._client()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        seed=seed,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget else None,
    )
    resp = client.models.generate_content(model=model, contents=user, config=cfg)
    um = resp.usage_metadata
    inp = getattr(um, "prompt_token_count", 0) or 0
    out = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
    return resp.text or "", inp, out


def _anthropic_generate(model, system, user, temperature, seed, max_tokens, thinking_budget=None):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        system=system + "\nReturn a single JSON object only.",
        messages=[{"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def call_model(stage: str, model: str, system: str, user: str, *, temperature: float, seed: int,
               max_tokens: int = 8192, key_extra: str = "", thinking_budget: int | None = None) -> dict:
    """Cached, logged JSON call. Returns {'json', 'text', 'request_hash', ...}."""
    key = [model, system, user, temperature, seed, max_tokens, key_extra]
    if thinking_budget:
        key.append(thinking_budget)
    req_hash = sha(json.dumps(key))
    cache_path = CALLS / f"{req_hash}.json"
    rec = None
    if cache_path.exists():
        try:
            rec = read_json(cache_path)
        except json.JSONDecodeError:  # torn by an earlier concurrent writer: treat as a miss
            rec = None
    if rec is not None:
        _log_call({**{k: rec[k] for k in ("stage", "model", "request_hash", "input_tokens", "output_tokens")},
                   "cost_usd": rec["cost_usd"], "cached": True, "elapsed_s": 0.0, "error": rec.get("error")})
        return rec
    if spent_usd() >= SPEND_CAP:
        raise SpendCapExceeded(f"spend cap ${SPEND_CAP:.2f} reached (spent ${spent_usd():.3f})")
    provider = "anthropic" if model.startswith("claude") else "vertex"
    gen = _anthropic_generate if provider == "anthropic" else _vertex_generate
    t0 = time.time()
    err, text, inp, out = None, "", 0, 0
    for attempt in range(3):
        try:
            text, inp, out = gen(model, system, user, temperature, seed, max_tokens, thinking_budget)
            err = None
            break
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {str(exc)[:300]}"
            time.sleep(2 ** (attempt + 1))
    parsed = None
    if err is None:
        parsed = parse_json(text)
        if parsed is None:
            err = "unparseable JSON"
    rec = {
        "stage": stage, "model": model, "provider": provider, "request_hash": req_hash,
        "temperature": temperature, "seed": seed, "max_tokens": max_tokens, "thinking_budget": thinking_budget,
        "input_tokens": inp, "output_tokens": out, "cost_usd": cost_of(model, inp, out),
        "elapsed_s": round(time.time() - t0, 2), "error": err, "text": text, "json": parsed,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if err is None:  # atomic: identical concurrent calls must not interleave their writes
        tmp = cache_path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        write_json(tmp, rec)
        os.replace(tmp, cache_path)
    _log_call({k: rec[k] for k in ("stage", "model", "provider", "request_hash", "temperature", "seed",
                                    "input_tokens", "output_tokens", "cost_usd", "elapsed_s", "error", "ts")}
              | {"cached": False})
    return rec


def _log_call(row: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK, (OUT / "call_log.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def parse_json(text: str):
    if not text:
        return None
    blob = text.strip()
    blob = re.sub(r"^```(?:json)?|```$", "", blob, flags=re.M).strip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", blob, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# ----------------------------------------------------------------------------- prepare: data + split


def load_capterra() -> tuple[pd.DataFrame, dict]:
    url = f"https://huggingface.co/datasets/{DATASET_REPO}/resolve/{DATASET_REV}/{DATASET_FILE}"
    path = download(url, CACHE / "capterra" / DATASET_FILE)
    df = pd.read_csv(path, dtype={"review_id": str})
    meta = {
        "repo": DATASET_REPO, "revision": DATASET_REV, "file": DATASET_FILE, "url": url,
        "sha256": sha(path.read_bytes()), "rows": int(len(df)), "products": int(df.product_name.nunique()),
        "rows_per_target": {p: int((df.product_name == p).sum()) for p in PRODUCTS},
    }
    return df, meta


def review_prose(row) -> str:
    return " | ".join(clean(row.get(f)) for f in PROSE_FIELDS if clean(row.get(f)))


def shingles(text: str, n: int = 5) -> set:
    w = text.split()
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def cluster_duplicates(rows: list[dict]) -> dict[str, str]:
    """Union-find over exact + near-duplicate (5-gram Jaccard) prose. Blank prose never clusters."""
    parent = {r["review_id"]: r["review_id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_text: dict[str, str] = {}
    sh: dict[str, set] = {}
    index: dict[str, set] = {}
    for r in rows:
        t = r["norm"]
        if not t:
            continue
        if t in by_text:
            union(by_text[t], r["review_id"])
        else:
            by_text[t] = r["review_id"]
        s = shingles(t)
        if s:
            sh[r["review_id"]] = s
            for g in s:
                index.setdefault(g, set()).add(r["review_id"])
    for rid, s in sh.items():
        cands = set()
        for g in s:
            cands |= index[g]
        for c in cands:
            if c <= rid:
                continue
            o = sh[c]
            if len(s & o) / len(s | o) >= NEAR_DUP_JACCARD:
                union(rid, c)
    return {rid: find(rid) for rid in parent}


def make_splits(df: pd.DataFrame, seed: int, meta: dict) -> dict:
    sub = df[df.product_name.isin(PRODUCTS)].copy()
    rows = []
    for _, r in sub.iterrows():
        rd = r.to_dict()
        rd["norm"] = norm_text(review_prose(rd))
        rows.append(rd)
    cluster = cluster_duplicates(rows)
    members: dict[str, list[str]] = {}
    for rid, c in cluster.items():
        members.setdefault(c, []).append(rid)
    # Keep one representative per duplicate cluster (smallest sha256 of review_id).
    keep = {min(m, key=lambda x: sha(x)) for m in members.values()}
    dropped = {rid: cluster[rid] for rid in cluster if rid not in keep}
    splits = {"seed": seed, "source": meta, "products": {}, "duplicate_handling": {
        "normalization": "NFKC + lowercase + whitespace collapse over " + ", ".join(PROSE_FIELDS),
        "exact": "identical nonempty normalized prose clustered",
        "near": f"word 5-gram Jaccard >= {NEAR_DUP_JACCARD}; blank prose never clustered",
        "policy": "one representative per cluster retained (min sha256(review_id)); others dropped from all partitions",
        "clusters_with_duplicates": sum(1 for m in members.values() if len(m) > 1),
        "dropped_rows": len(dropped),
        "dropped": [{"review_id": k, "cluster_rep": min(members[v], key=lambda x: sha(x))} for k, v in sorted(dropped.items())],
    }, "sort_key": f"sha256('{seed}|product_name|review_id|normalized_text')",
        "partition": f"first {N_DEV} dev, next {N_TEST} test, rest evidence pool (per product)"}
    for p in PRODUCTS:
        pr = [r for r in rows if r["product_name"] == p and r["review_id"] in keep]
        pr.sort(key=lambda r: sha(f"{seed}|{p}|{r['review_id']}|{r['norm']}"))
        part = {"dev": pr[:N_DEV], "test": pr[N_DEV:N_DEV + N_TEST], "pool": pr[N_DEV + N_TEST:]}
        splits["products"][p] = {
            k: [{"review_id": r["review_id"], "text_sha256": sha(r["norm"]), "cluster": cluster[r["review_id"]]}
                for r in v] for k, v in part.items()
        }
        splits["products"][p]["counts"] = {k: len(v) for k, v in part.items()}
    return splits, {r["review_id"]: r for r in rows}


# ----------------------------------------------------------------------------- prepare: evidence packs

DROP_SENTENCE = re.compile(
    r"\d+\s?%|\bfortune\b|\bcustomers?\b|\breviews?\b|\breviewers?\b|\btrusted by\b|\bread the story\b|"
    r"testimonial|\bmillions?\b|\d[\d,.]*\s?(k|m)?\+?\s*(teams|users|companies|organizations|businesses|people)|"
    r"\brat(ed|ing|ings)\b|\bstars?\b|\bg2\b|\bcapterra\b|techvalidate|\bsurvey\b|\bsign ?up\b|privacy|"
    r"terms of service|cookie|credit card|\bget started\b|\bget a demo\b|\blearn more\b|\b(director|manager|ceo|cto|"
    r"vp|head of|founder)\b.{0,40}\bat\b|\baward|\bleader in\b|\bgartner\b|\bforrester\b|\bchoose\b|"
    r"accurate as of|free and paid users",
    re.I,
)


def page_text(html: str) -> str:
    import bs4

    soup = bs4.BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button"]):
        t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def filter_sentences(text: str) -> tuple[list[str], int]:
    sents = re.split(r"(?<=[.!?])\s+", text)
    out, seen, dropped = [], set(), 0
    for s in sents:
        s = s.strip()
        if len(s.split()) < 4:
            continue
        k = norm_text(s)
        if k in seen:
            continue
        seen.add(k)
        if DROP_SENTENCE.search(s):
            dropped += 1
            continue
        out.append(s)
    return out, dropped


def passages_from(product: str, page: str, sents: list[str], cap: int) -> tuple[list[dict], bool]:
    """Group sentences into ~3-sentence passages until the token cap."""
    out, used, truncated, buf = [], 0, False, []
    for s in sents:
        if used + approx_tokens(s) > cap:
            truncated = True
            break
        buf.append(s)
        used += approx_tokens(s)
        if len(buf) == 3:
            out.append(buf)
            buf = []
    if buf:
        out.append(buf)
    return [{"id": f"D:{product}:{page}:{i + 1}", "text": " ".join(b)} for i, b in enumerate(out)], truncated


def build_D(captured: dict) -> dict:
    packs = {}
    for target in PRODUCTS:
        items, meta = [], []
        remaining = CAP_D_TARGET
        for page in ("landing", "features"):
            cap = captured[target][page]
            ps, trunc = passages_from(target, page, cap["sentences"], CAP_D_TARGET // 2 if page == "landing" else remaining)
            remaining -= sum(approx_tokens(x["text"]) for x in ps)
            items += [{**x, "product": target, "role": "target", "url": cap["url"]} for x in ps]
            meta.append({"product": target, "role": "target", "page": page, "url": cap["url"],
                         "captured": cap["captured"], "html_sha256": cap["html_sha256"],
                         "tokens": sum(approx_tokens(x["text"]) for x in ps), "truncated": trunc,
                         "sentences_dropped_by_filter": cap["dropped"]})
        for peer in PRODUCTS:
            if peer == target:
                continue
            page = PEER_OVERVIEW[peer]
            cap = captured[peer][page]
            ps, trunc = passages_from(peer, page, cap["sentences"], CAP_D_PEER)
            items += [{**x, "product": peer, "role": "competitor", "url": cap["url"]} for x in ps]
            meta.append({"product": peer, "role": "competitor", "page": page, "url": cap["url"],
                         "captured": cap["captured"], "html_sha256": cap["html_sha256"],
                         "tokens": sum(approx_tokens(x["text"]) for x in ps), "truncated": trunc,
                         "sentences_dropped_by_filter": cap["dropped"]})
        packs[target] = {"items": items, "sources": meta}
    return packs


def capture_pages() -> dict:
    captured = {}
    for p, pages in PAGES.items():
        captured[p] = {}
        for page, url in pages.items():
            dest = CACHE / "pages" / f"{p}_{page}.html"
            download(url, dest)
            html = dest.read_text(encoding="utf-8", errors="ignore")
            sents, dropped = filter_sentences(page_text(html))
            captured[p][page] = {
                "url": url, "captured": datetime.fromtimestamp(dest.stat().st_mtime, timezone.utc).date().isoformat(),
                "html_sha256": sha(html), "sentences": sents, "dropped": dropped,
            }
    return captured


REVIEW_FIELDS = [
    ("reviewer_job_title", "Role"), ("reviewer_industry", "Industry"), ("reviewer_company_size", "Company size"),
    ("reviewer_time_used_product", "Time used"), ("overall_rating", "Overall rating"),
    ("ease_of_use_rating", "Ease-of-use rating"), ("pros", "Pros"), ("cons", "Cons"),
    ("general_comments", "Comments"), ("reasons_for_choosing", "Reasons for choosing"),
    ("reasons_for_switching", "Reasons for switching"), ("switched_from", "Switched from"),
    ("alternatives_considered", "Alternatives considered"),
]


def format_review(r: dict, mask_pattern: str | None) -> tuple[str, dict]:
    """Same field order and truncation rule for C and T. Masks target-product mentions for C."""
    lines, masked = [], 0
    for f, label in REVIEW_FIELDS:
        v = clean(r.get(f))
        if not v:
            continue
        if isinstance(r.get(f), float) and f.endswith("rating"):
            v = str(int(r[f]))
        if mask_pattern:
            if f in ("switched_from", "alternatives_considered"):
                parts = [x for x in v.split("|") if not re.search(mask_pattern, x, re.I)]
                masked += len(v.split("|")) - len(parts)
                v = "|".join(parts)
                if not v:
                    continue
            else:
                sents = re.split(r"(?<=[.!?])\s+", v)
                keep = []
                for s in sents:
                    if re.search(mask_pattern, s, re.I):
                        masked += 1
                        keep.append("[sentence mentioning the target product removed]")
                    else:
                        keep.append(s)
                v = " ".join(keep)
        lines.append(f"{label}: {v}")
    text, truncated = "\n".join(lines), False
    if approx_tokens(text) > CAP_REVIEW:
        text, truncated = text[: CAP_REVIEW * 4].rsplit(" ", 1)[0] + " [truncated]", True
    return text, {"truncated": truncated, "masked_passages": masked}


def select_pool_rows(pool_ids: list[str], rows: dict, seed: int, tag: str, product: str, n: int) -> list[dict]:
    """Deterministic, outcome-independent: order by sha256(seed|tag|product|id); require nonempty prose."""
    cands = [rows[i] for i in pool_ids if rows[i]["norm"]]
    cands.sort(key=lambda r: sha(f"{seed}|{tag}|{product}|{r['review_id']}"))
    return cands[:n]


def build_review_pack(kind: str, target: str, splits: dict, rows: dict, seed: int) -> dict:
    sources = [p for p in PRODUCTS if p != target] if kind == "C" else [target]
    items = []
    for src in sources:
        pool = [x["review_id"] for x in splits["products"][src]["pool"]]
        for r in select_pool_rows(pool, rows, seed, kind, src, N_PACK):
            text, info = format_review(r, NAME_PATTERNS[target] if kind == "C" else None)
            items.append({"id": f"{kind}:{r['review_id']}", "review_id": r["review_id"], "product": src,
                          "text": text, "tokens": approx_tokens(text), **info,
                          "ease_of_use_rating": r.get("ease_of_use_rating")})
    return {"items": items}


def prepare(seed: int) -> None:
    df, meta = load_capterra()
    for f in ONET_FILES:
        download(f"https://www.onetcenter.org/dl_files/database/{ONET_VERSION}/{f}", CACHE / "onet" / f)
    splits, rows = make_splits(df, seed, meta)
    write_json(OUT / "splits.json", splits)

    for p in PRODUCTS:
        for part in ("dev", "test"):
            recs = []
            for x in splits["products"][p][part]:
                r = rows[x["review_id"]]
                recs.append({k: (None if isinstance(v, float) and math.isnan(v) else v)
                             for k, v in r.items() if k != "norm"})
            write_jsonl(HIDDEN / f"{part}_{p}.jsonl", recs)

    captured = capture_pages()
    D = build_D(captured)
    manifest = {"created": date.today().isoformat(), "seed": seed, "token_counting": "approx ceil(chars/4)",
                "caps": {"D_target": CAP_D_TARGET, "D_peer": CAP_D_PEER, "O": CAP_O, "review": CAP_REVIEW},
                "page_filter": "sentences matching testimonial/statistic/customer-count/rating/CTA regex removed",
                "targets": {}}
    for t in PRODUCTS:
        packs = {"M": {"items": [{"id": f"M:{t}", "text": f"Product: {t}. {SEED_SENTENCE[t]}"}]},
                 "D": D[t], "C": build_review_pack("C", t, splits, rows, seed),
                 "T": build_review_pack("T", t, splits, rows, seed)}
        old_o = PACKS / t / "O.json"
        for k, v in packs.items():
            write_json(PACKS / t / f"{k}.json", v)
        entry = {k: pack_summary(k, v) for k, v in packs.items()}
        entry["D"]["sources"] = D[t]["sources"]
        entry["O"] = pack_summary("O", read_json(old_o)) if old_o.exists() else {
            "status": "blocked: needs model call", "resume": "python experiments/staged_context/experiment.py onet"}
        manifest["targets"][t] = entry
    write_json(OUT / "evidence_manifest.json", manifest)
    checks = leakage_checks()
    print(json.dumps({"splits": {p: splits["products"][p]["counts"] for p in PRODUCTS},
                      "dropped_duplicates": splits["duplicate_handling"]["dropped_rows"],
                      "leakage_checks": checks}, indent=2))


def pack_summary(kind: str, pack: dict) -> dict:
    text = pack_text(kind, pack)
    s = {"items": len(pack.get("items", [])), "tokens_approx": approx_tokens(text), "sha256": sha(text)}
    if kind in ("C", "T"):
        s["review_ids"] = [x["review_id"] for x in pack["items"]]
        s["products"] = sorted({x["product"] for x in pack["items"]})
        s["truncated_reviews"] = sum(x["truncated"] for x in pack["items"])
        s["masked_passages"] = sum(x["masked_passages"] for x in pack["items"])
    if kind == "O":
        s["status"] = pack.get("status", "ok")
        s["occupations"] = pack.get("occupations", [])
    return s


def pack_text(kind: str, pack: dict) -> str:
    if kind == "O":
        lines = []
        for occ in pack.get("occupations", []):
            lines.append(f"[{occ['id']}] Occupation: {occ['title']} (O*NET-SOC {occ['code']})")
            for tk in occ["tasks"]:
                lines.append(f"  [{tk['id']}] {tk['text']}")
        return "\n".join(lines)
    if kind in ("C", "T"):
        return "\n\n".join(f"[{x['id']}] Product reviewed: {x['product']}\n{x['text']}" for x in pack["items"])
    if kind == "D":
        return "\n".join(f"[{x['id']}] ({x['product']}, {x['role']} page {x['url']}) {x['text']}" for x in pack["items"])
    return "\n".join(f"[{x['id']}] {x['text']}" for x in pack["items"])


def leakage_checks() -> dict:
    splits = read_json(OUT / "splits.json")
    res = {}
    ids = {k: set() for k in ("dev", "test", "pool")}
    clusters = {k: set() for k in ("dev", "test", "pool")}
    for p in PRODUCTS:
        for k in ids:
            ids[k] |= {x["review_id"] for x in splits["products"][p][k]}
            clusters[k] |= {x["cluster"] for x in splits["products"][p][k]}
    res["review_ids_disjoint"] = not (ids["dev"] & ids["test"] or ids["dev"] & ids["pool"] or ids["test"] & ids["pool"])
    res["clusters_disjoint"] = not (clusters["dev"] & clusters["test"] or clusters["dev"] & clusters["pool"]
                                    or clusters["test"] & clusters["pool"])
    hidden_rows = [r for p in PRODUCTS for part in ("dev", "test") for r in read_jsonl(HIDDEN / f"{part}_{p}.jsonl")]
    hidden_sh = set()
    for r in hidden_rows:
        hidden_sh |= shingles(norm_text(review_prose(r)), 8)
    pack_ok, no_target_in_c, no_overlap = True, True, True
    for t in PRODUCTS:
        for k in ("C", "T"):
            pack = read_json(PACKS / t / f"{k}.json")
            for x in pack["items"]:
                if x["review_id"] not in ids["pool"]:
                    pack_ok = False
                if k == "C" and (x["product"] == t or re.search(NAME_PATTERNS[t], x["text"], re.I)):
                    no_target_in_c = False
        for f in (PACKS / t).glob("*.json"):
            txt = norm_text(pack_text(f.stem, read_json(f)))
            if shingles(txt, 8) & hidden_sh:
                no_overlap = False
                res.setdefault("overlap_files", []).append(str(f.relative_to(OUT)))
    res["packs_only_from_pool"] = pack_ok
    res["no_target_reviews_or_mentions_in_C"] = no_target_in_c
    res["no_hidden_8gram_in_packs"] = no_overlap
    ref = read_jsonl(OUT / "reference_audit.jsonl")
    if ref:
        all_packs = " ".join(norm_text(pack_text(f.stem, read_json(f))) for t in PRODUCTS for f in (PACKS / t).glob("*.json"))
        bad = [s for r in ref for item in r["tasks"] + r["benefits"] + r["frictions"]
               for s in [norm_text(item.get("span") or "")] if len(s.split()) >= 6 and s in all_packs]
        res["no_reference_spans_in_packs"] = not bad
    write_json(OUT / "leakage_checks.json", res)
    return res


# ----------------------------------------------------------------------------- pack O (occupations)

ONET_SYSTEM = "You map software products to plausible user occupations using the O*NET taxonomy. Return JSON only."


def onet_pack(t: str, D: dict, seed_sentence: str) -> dict:
    """Pack O for one product: model maps D to <=3 O*NET occupations; tasks chosen lexically (Core first)."""
    occ = pd.read_csv(CACHE / "onet" / "occupation_data.csv", dtype=str)
    tasks = pd.read_csv(CACHE / "onet" / "task_statements.csv", dtype=str)
    catalog = "\n".join(f"{r['O*NET-SOC Code']}\t{r['Title']}" for _, r in occ.iterrows())
    codes = set(occ["O*NET-SOC Code"])
    d_target = " ".join(x["text"] for x in D["items"] if x["role"] == "target")
    user = (
        f"Product: {t}. {seed_sentence}\n\nPublic product page excerpts:\n{pack_text('D', D)}\n\n"
        "From these excerpts only, choose at most 3 O*NET occupations whose workers plausibly use this "
        "product in their work. Use codes exactly as listed in the catalog below.\n"
        'Return {"occupations": [{"code": "...", "title": "...", "rationale": "one sentence citing the excerpts"}]}\n\n'
        f"O*NET catalog (code<TAB>title):\n{catalog}"
    )
    rec = call_model("onet_map", JUDGE_MODEL, ONET_SYSTEM, user, temperature=0.0, seed=42, max_tokens=4096)
    if rec.get("error"):
        return {"status": f"failed: {rec['error']}", "occupations": []}
    chosen = [o for o in (rec["json"] or {}).get("occupations", []) if o.get("code") in codes][:3]
    d_words = set(re.findall(r"[a-z]+", d_target.lower())) - STOP
    out_occ, budget = [], CAP_O
    for o in chosen:
        ts = tasks[tasks["O*NET-SOC Code"] == o["code"]].copy()
        ts["overlap"] = ts["Task"].map(lambda s: len((set(re.findall(r"[a-z]+", s.lower())) - STOP) & d_words))
        ts["core"] = (ts["Task Type"] == "Core").astype(int)
        ts = ts.sort_values(["core", "overlap", "Task ID"], ascending=[False, False, True]).head(4)
        sel = []
        for _, r in ts.iterrows():
            if approx_tokens(r["Task"]) + 10 > budget:
                break
            budget -= approx_tokens(r["Task"]) + 10
            sel.append({"id": f"O:{o['code']}:{r['Task ID']}", "task_id": r["Task ID"], "text": r["Task"],
                        "task_type": r["Task Type"], "lexical_overlap_with_D": int(r["overlap"])})
        title = occ.loc[occ["O*NET-SOC Code"] == o["code"], "Title"].iloc[0]
        out_occ.append({"id": f"O:{o['code']}", "code": o["code"], "title": title,
                        "mapping": "model-inferred from pack D (no review data)", "rationale": o.get("rationale"),
                        "tasks": sel})
    return {"status": "ok", "onet_version": ONET_VERSION, "mapping_model": JUDGE_MODEL,
            "task_selection": "Core first, then lexical overlap with target D text, then Task ID",
            "occupations": out_occ}


def build_onet() -> None:
    for t in PRODUCTS:
        write_json(PACKS / t / "O.json", onet_pack(t, read_json(PACKS / t / "D.json"), SEED_SENTENCE[t]))
    man = read_json(OUT / "evidence_manifest.json")
    for t in PRODUCTS:
        man["targets"][t]["O"] = pack_summary("O", read_json(PACKS / t / "O.json"))
    write_json(OUT / "evidence_manifest.json", man)
    print(json.dumps({t: man["targets"][t]["O"] for t in PRODUCTS}, indent=2))


STOP = set("""a an the and or of to in for on with your you our we is are be by as at from that this it its all
any can into more most one so than then them they their will work team teams get every each""".split())


# ----------------------------------------------------------------------------- predict

PREDICT_SYSTEM = (
    "You are a product research analyst forecasting what reviewers of a B2B software product report. "
    "You never write first-person testimonials and never claim to know a specific reviewer or a market distribution. "
    "Return JSON only."
)

PREDICT_INSTRUCTIONS = """Predict what reviewers of {product} on a B2B software review site are likely to report using it for and experiencing.
Base the forecast only on the evidence below plus your general knowledge. Segments are hypotheses about who writes reviews, not market shares. You do not know any specific reviewer.

Return exactly this JSON shape:
{{
  "product": "{product}",
  "segments": [{{"role_family": str, "motivation": str, "basis_ids": [str]}}],
  "tasks": [{{"action": str|null, "object": str|null, "context": str|null, "purpose": str|null, "basis_ids": [str]}}],
  "benefits": [{{"aspect": str, "claim": str, "basis_ids": [str]}}],
  "frictions": [{{"aspect": str, "claim": str, "basis_ids": [str]}}],
  "ease_of_use_probabilities_1_to_5": [p1, p2, p3, p4, p5],
  "unknowns": [str]
}}
Rules:
- segments: up to 3 reviewer role families with their motivation.
- tasks: exactly 5 distinct, concrete things reviewers use the product to do (action verb + object, with context/purpose when you can). If you cannot support a fifth task, use an entry with action null to abstain.
- benefits and frictions: up to 3 each, short claims about the product experience. Fewer is fine.
- ease_of_use_probabilities_1_to_5: probability that a reviewer gives each ease-of-use rating 1..5; five numbers in [0,1] summing to 1.
- basis_ids: IDs of evidence items in brackets below that support the item; [] if from general knowledge.
- State claims about the product itself; do not mention evidence sections or sources in the claim text.

Evidence:
"""

PACK_HEADINGS = {
    "M": "Product seed",
    "D": "Public product pages (target and competitors)",
    "O": "Occupational task statements (O*NET; occupation mapping is inferred)",
    "C": "Reviews of competitor products (mentions of the target product removed)",
    "T": "Reviews of the target product",
}


def load_packs(product: str) -> dict:
    return {k: read_json(PACKS / product / f"{k}.json") for k in "MDOCT" if (PACKS / product / f"{k}.json").exists()}


def build_predict_prompt(product: str, condition: str, packs: dict) -> str:
    parts = [PREDICT_INSTRUCTIONS.format(product=product)]
    for k in ["M"] + CONDITIONS[condition]:
        parts.append(f"## {PACK_HEADINGS[k]}\n{pack_text(k, packs[k])}\n")
    return "\n".join(parts)


def validate_prediction(obj) -> tuple[dict | None, list[str]]:
    errs = []
    if not isinstance(obj, dict):
        return None, ["not an object"]
    probs = obj.get("ease_of_use_probabilities_1_to_5")
    if not (isinstance(probs, list) and len(probs) == 5 and all(isinstance(x, (int, float)) for x in probs)):
        errs.append("ease probabilities missing/invalid")
    else:
        if any(x < 0 or x > 1 for x in probs):
            errs.append("probability outside [0,1]")
        elif abs(sum(probs) - 1) > 0.02:
            errs.append(f"probabilities sum to {sum(probs):.3f}")
        elif abs(sum(probs) - 1) > 1e-9:
            obj["ease_of_use_probabilities_1_to_5"] = [x / sum(probs) for x in probs]
            obj.setdefault("_notes", []).append("probabilities renormalized from sum %.4f" % sum(probs))
    tasks = obj.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 5:
        errs.append(f"expected 5 tasks, got {len(tasks) if isinstance(tasks, list) else 'none'}")
    for k, lim in (("segments", 3), ("benefits", 3), ("frictions", 3)):
        v = obj.get(k, [])
        if not isinstance(v, list):
            errs.append(f"{k} not a list")
        elif len(v) > lim:
            obj[k] = v[:lim]
            obj.setdefault("_notes", []).append(f"{k} trimmed to {lim}")
    return (obj if not errs else None), errs


def run_prediction(product: str, condition: str, rep: int, packs: dict) -> dict:
    user = build_predict_prompt(product, condition, packs)
    for attempt in range(2):
        rec = call_model("predict", PREDICT_MODEL, PREDICT_SYSTEM, user, temperature=PREDICT_TEMPERATURE,
                         seed=1000 * rep + attempt, max_tokens=8192, key_extra=f"{product}|{condition}|{rep}|{attempt}")
        obj, errs = validate_prediction(rec.get("json")) if not rec.get("error") else (None, [rec["error"]])
        if obj:
            break
    pred = {"product": product, "condition": condition, "replicate": rep, "model": PREDICT_MODEL,
            "temperature": PREDICT_TEMPERATURE, "seed": 1000 * rep + attempt, "attempts": attempt + 1,
            "request_hash": rec["request_hash"], "prompt_tokens_approx": approx_tokens(PREDICT_SYSTEM + user),
            "input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"],
            "cost_usd": rec["cost_usd"], "elapsed_s": rec["elapsed_s"],
            "valid": obj is not None, "errors": errs}
    if obj:
        pred.update({k: obj.get(k) for k in ("segments", "tasks", "benefits", "frictions",
                                              "ease_of_use_probabilities_1_to_5", "unknowns")})
        pred["notes"] = obj.get("_notes", [])
    return pred


def predict(conditions: list[str], reps: int, products: list[str]) -> None:
    for p in products:
        if not (PACKS / p / "O.json").exists() or read_json(PACKS / p / "O.json").get("status") != "ok":
            needs_o = [c for c in conditions if "O" in CONDITIONS[c]]
            if needs_o:
                sys.exit(f"pack O missing for {p}; run `onet` first (conditions {needs_o} need it)")
    existing = {(r["product"], r["condition"], r["replicate"]): r for r in read_jsonl(OUT / "predictions.jsonl")}
    for rep in range(1, reps + 1):
        for p in products:
            packs = load_packs(p)
            for c in conditions:
                if (p, c, rep) in existing and existing[(p, c, rep)]["valid"]:
                    continue
                try:
                    existing[(p, c, rep)] = run_prediction(p, c, rep, packs)
                except SpendCapExceeded as exc:
                    print(f"STOP: {exc}")
                    write_jsonl(OUT / "predictions.jsonl", sorted(existing.values(), key=_pred_order))
                    return
                r = existing[(p, c, rep)]
                print(f"{p:8s} {c} r{rep} valid={r['valid']} in={r['input_tokens']} out={r['output_tokens']} "
                      f"${r['cost_usd']:.4f} {r['errors'] or ''}")
                write_jsonl(OUT / "predictions.jsonl", sorted(existing.values(), key=_pred_order))


def _pred_order(r):
    return (r["replicate"], PRODUCTS.index(r["product"]), list(CONDITIONS).index(r["condition"]))


# ----------------------------------------------------------------------------- reference extraction

RUBRIC_VERSION = "v1-2026-10-17"
EXTRACT_SYSTEM = "You extract explicit claims from a single software review for an evaluation set. Return JSON only."
EXTRACT_RUBRIC = """Extract only what this review explicitly states. Rubric (frozen, {version}):
TASKS (max 3): concrete activities the reviewer says they or their team use the product to do. Each has
  action (verb), object (what is acted on), context (team/industry/situation stated in the review, else null),
  purpose (why, if stated, else null), span (exact verbatim substring of the review supporting it).
  - Do NOT infer a task from the job title, industry or company size.
  - Generic praise ("great software", "helps us stay organized", "manage everything") is not a task unless an object
    or activity is named (e.g. "track client onboarding steps" is a task).
  - Prefer the most specific tasks; merge near-identical ones.
BENEFITS (max 3): explicit positive experience claims about the product (aspect + short claim + span).
FRICTIONS (max 3): explicit negative experiences/limitations (aspect + short claim + span).
  - "No cons", "nothing", "none" are not frictions; return none.
aspect is one of: ease_of_use, interface, features, flexibility, collaboration, integrations, automation, reporting,
  mobile, performance, pricing, support, onboarding, notifications, other.
Spans must be copied character-for-character from the review text. Empty lists are correct when nothing qualifies.
Return {{"tasks": [{{"action","object","context","purpose","span"}}], "benefits": [{{"aspect","claim","span"}}],
"frictions": [{{"aspect","claim","span"}}]}}

Review of {product}:
{review}
"""


def review_for_extraction(r: dict) -> str:
    fields = [("review_title", "Title")] + [(f, f.replace("_", " ").capitalize()) for f in PROSE_FIELDS]
    return "\n".join(f"{label}: {clean(r.get(f))}" for f, label in fields if clean(r.get(f)))


def span_ok(span: str, text: str) -> bool:
    return bool(span) and norm_text(span) in norm_text(text)


def extract_references(part: str, products: list[str]) -> list[dict]:
    return [ref for p in products for ref in extract_references_rows(read_jsonl(HIDDEN / f"{part}_{p}.jsonl"), p, part)]


def extract_references_rows(rows: list[dict], p: str, part: str = "matched") -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(lambda r: _extract_one(r, p, part), rows))


def _extract_one(r: dict, p: str, part: str) -> dict:
    text = review_for_extraction(r)
    ref = {"review_id": r["review_id"], "product": p, "split": part, "rubric_version": RUBRIC_VERSION,
           "extraction": "machine-extracted", "extract_model": JUDGE_MODEL, "tasks": [], "benefits": [],
           "frictions": [], "invalid_span_items": 0, "error": None}
    ease = r.get("ease_of_use_rating")
    ref["ease_of_use_rating"] = int(ease) if isinstance(ease, (int, float)) and ease in (1, 2, 3, 4, 5) else None
    for f in ("reviewer_job_title", "reviewer_industry", "reviewer_company_size"):
        ref[f] = r.get(f)
    if text:
        rec = call_model("extract", JUDGE_MODEL, EXTRACT_SYSTEM,
                         EXTRACT_RUBRIC.format(version=RUBRIC_VERSION, product=p, review=text),
                         temperature=JUDGE_TEMPERATURE, seed=42, max_tokens=4096)
        if rec.get("error"):
            ref["error"] = rec["error"]
        else:
            j = rec["json"] or {}
            for k in ("tasks", "benefits", "frictions"):
                items = [x for x in (j.get(k) or []) if isinstance(x, dict)][:3]
                for x in items:
                    x["span_valid"] = span_ok(x.get("span", ""), text)
                ref["invalid_span_items"] += sum(not x["span_valid"] for x in items)
                ref[k] = [x for x in items if x["span_valid"]]
                ref[f"{k}_dropped_invalid_span"] = [x for x in items if not x["span_valid"]]
    ref["taskless"] = not ref["tasks"]
    return ref


# ----------------------------------------------------------------------------- role-family codebook
# Defined from development + evidence-pool job titles only (never test titles). Order matters: first match wins.
# Frozen before test scoring.
ROLE_FAMILIES = [
    ("executive_owner", r"\b(ceo|coo|cfo|cto|cio|cmo|founder|co-?founder|owner|president|partner|principal|chief|"
                        r"managing director|managing member|general manager|executive director|entrepreneur|board member)\b"),
    ("project_program_mgmt", r"\b(project|program|programme|pmo|scrum|agile|delivery|portfolio|producer)\b"),
    ("product_mgmt", r"\bproduct (manager|owner|lead|director|management)\b"),
    ("healthcare_wellness", r"\b(therapist|psycholog\w*|counselor|coach|doctor|nurse|health|clinical|medical|"
                            r"physician|dentist|pharmac\w*|psychotherapist)\b"),
    ("software_it_engineering", r"\b(developer|developper|engineer|engineering|software|devops|it\b|programmer|architect|"
                                r"technical|tech|qa|data|web|systems?|network|cto)\b"),
    ("marketing_creative_content", r"\b(marketing|marketer|content|social media|brand|seo|designer|design|creative|"
                                   r"writer|editor|copywriter|communications?|pr\b|media|video|art|artist|photographer|author|illustrator|"
                                   r"creator|presenter|ppc)\b"),
    ("sales_customer", r"\b(sales|account|customer|client|business development|success|support|realtor|"
                       r"real estate)\b"),
    ("operations_admin", r"\b(operations?|admin|administrator|administrative|assistant|coordinator|office|"
                         r"secretary|logistics|supply)\b"),
    ("finance_hr_legal", r"\b(finance|financial|accountant|accounting|controller|hr|human resources|recruit|"
                         r"talent|people|legal|attorney|lawyer|paralegal|compliance|human resources?|rh|recruiter|bookkeeper|billing)\b"),
    ("education_research_analysis", r"\b(teacher|professor|student|research|researcher|lecturer|educator|instructor|"
                           r"academic|scientist|phd|analyst|trainer)\b"),
    ("consultant_freelance", r"\b(consultant|consulting|freelance|freelancer|self-employed|contractor|advisor)\b"),
    ("general_team_mgmt", r"\b(manager|director|lead|leader|head|supervisor|vp|vice president|gerente|"
                          r"responsable|directeur|directora?)\b"),
]


def role_family(title: str | None) -> str:
    t = norm_text(title if isinstance(title, str) else "")
    if not t or t in {"n/a", "na", "none", "-", "unknown"}:
        return "unknown"
    for fam, pat in ROLE_FAMILIES:
        if re.search(pat, t):
            return fam
    return "unknown"


# ----------------------------------------------------------------------------- judging

JUDGE_SYSTEM = "You are a strict evaluator matching forecast claims to reference claims extracted from reviews. Return JSON only."
JUDGE_PROMPT = """Anonymous prediction set {set_id} for product {product}.

Scoring rubric (frozen):
TASK matches, score each (predicted task P, reference task R):
  2 = same action and object, and compatible material context/purpose.
  1 = correct broad task but misses distinguishing context (e.g. "manage projects" vs "collect client approval before publishing" is at most 1).
  0 = unrelated, generic, or incompatible.
CLAIM matches, for each (predicted claim Q, reference claim E):
  score 2 = same polarity and same specific experience; 1 = same polarity and aspect but vaguer/broader; 0 = otherwise.
  contradiction = true only if Q explicitly asserts the opposite of E (e.g. Q "easy to learn" vs E "steep learning curve").
  Opposite polarity on a different aspect is not a contradiction.

Predicted tasks:
{pred_tasks}

Reference tasks (id: action | object | context | purpose):
{ref_tasks}

Predicted claims (polarity, aspect, claim):
{pred_claims}

Reference claims (id: polarity, aspect, claim):
{ref_claims}

List ONLY pairs with score >= 1 or contradiction true:
{{"task_matches": [{{"pred": "P1", "ref": "R3", "score": 2}}],
  "claim_matches": [{{"pred": "Q1", "ref": "E4", "score": 1, "contradiction": false}}]}}
"""


def anon_id(pred: dict) -> str:
    return "set-" + sha(f"anon|{pred['product']}|{pred['condition']}|{pred['replicate']}")[:10]


def fmt_task(t: dict) -> str:
    return " | ".join(clean(t.get(k)) or "-" for k in ("action", "object", "context", "purpose"))


def judge_prediction(pred: dict, refs: list[dict]) -> dict:
    """Blind: anonymous id, no condition, no basis_ids, shuffled item order."""
    rng = random.Random(anon_id(pred))
    tasks = [(i, t) for i, t in enumerate(pred["tasks"] or []) if isinstance(t, dict) and t.get("action")]
    claims = [("benefit", i, c) for i, c in enumerate(pred.get("benefits") or []) if isinstance(c, dict) and c.get("claim")]
    claims += [("friction", i, c) for i, c in enumerate(pred.get("frictions") or []) if isinstance(c, dict) and c.get("claim")]
    rng.shuffle(tasks)
    rng.shuffle(claims)
    p_task = {f"P{j + 1}": i for j, (i, _) in enumerate(tasks)}
    p_claim = {f"Q{j + 1}": (pol, i) for j, (pol, i, _) in enumerate(claims)}
    r_task, r_claim = {}, {}
    for ri, ref in enumerate(refs):
        for ti, t in enumerate(ref["tasks"]):
            r_task[f"R{len(r_task) + 1}"] = (ri, ti)
        for pol in ("benefits", "frictions"):
            for ci, c in enumerate(ref[pol]):
                r_claim[f"E{len(r_claim) + 1}"] = (ri, pol[:-1], ci)
    prompt = JUDGE_PROMPT.format(
        set_id=anon_id(pred), product=pred["product"],
        pred_tasks="\n".join(f"{k}: {fmt_task(t)}" for k, (_, t) in zip(p_task, tasks)) or "(none)",
        ref_tasks="\n".join(f"{k}: {fmt_task(refs[ri]['tasks'][ti])}" for k, (ri, ti) in r_task.items()) or "(none)",
        pred_claims="\n".join(f"{k}: {pol}, {clean(c.get('aspect'))}, {clean(c.get('claim'))}"
                              for k, (pol, _, c) in zip(p_claim, claims)) or "(none)",
        ref_claims="\n".join(f"{k}: {pol}, {clean(refs[ri][pol + 's'][ci].get('aspect'))}, "
                             f"{clean(refs[ri][pol + 's'][ci].get('claim'))}" for k, (ri, pol, ci) in r_claim.items()) or "(none)",
    )
    for seed in (42, 43):  # one retry on a malformed (non-object) reply
        rec = call_model("judge", JUDGE_MODEL, JUDGE_SYSTEM, prompt, temperature=JUDGE_TEMPERATURE, seed=seed,
                         max_tokens=JUDGE_MAX_TOKENS, thinking_budget=JUDGE_THINKING_BUDGET)
        if not rec.get("error") and not isinstance(rec.get("json"), dict):
            rec = {**rec, "error": "judge reply was not a JSON object"}
        if not rec.get("error"):
            break
    j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
    tm, cm = [], []
    for m in j.get("task_matches") or []:
        if m.get("pred") in p_task and m.get("ref") in r_task and m.get("score") in (1, 2):
            ri, ti = r_task[m["ref"]]
            tm.append({"pred_task": p_task[m["pred"]], "review": ri, "ref_task": ti, "score": m["score"]})
    for m in j.get("claim_matches") or []:
        if m.get("pred") in p_claim and m.get("ref") in r_claim:
            pol, pi = p_claim[m["pred"]]
            ri, rpol, ci = r_claim[m["ref"]]
            score = m.get("score") if m.get("score") in (1, 2) and pol == rpol else 0
            cm.append({"pred_polarity": pol, "pred_claim": pi, "review": ri, "ref_polarity": rpol, "ref_claim": ci,
                       "score": score, "contradiction": bool(m.get("contradiction"))})
    return {"set_id": anon_id(pred), "product": pred["product"], "condition": pred["condition"],
            "replicate": pred["replicate"], "judge_model": JUDGE_MODEL, "request_hash": rec["request_hash"],
            "error": rec.get("error"), "task_matches": tm, "claim_matches": cm,
            "cost_usd": rec["cost_usd"], "input_tokens": rec["input_tokens"], "output_tokens": rec["output_tokens"]}


# ----------------------------------------------------------------------------- metrics


def best_assignment(n_pred: int, refs: list[int], scores: dict) -> list[int]:
    """One-to-one: maximize (#score-2, total score). refs = reference task indices for one review."""
    best, best_key = [0] * len(refs), (-1, -1)
    preds = list(range(n_pred)) + [None] * len(refs)
    for perm in set(permutations(preds, len(refs))):
        s = [scores.get((p, r), 0) if p is not None else 0 for p, r in zip(perm, refs)]
        key = (sum(x == 2 for x in s), sum(s))
        if key > best_key:
            best, best_key = s, key
    return best


def ease_metrics(probs: list[float], ratings: list[int]) -> dict:
    if not ratings or not probs:
        return {"ease_expected": None, "ease_mae": None, "ease_rps": None, "rating_n": len(ratings)}
    exp = sum((k + 1) * p for k, p in enumerate(probs))
    cum = np.cumsum(probs)
    rps = [sum((cum[k] - (y <= k + 1)) ** 2 for k in range(4)) / 4 for y in ratings]
    return {"ease_expected": exp, "ease_mae": float(np.mean([abs(exp - y) for y in ratings])),
            "ease_rps": float(np.mean(rps)), "rating_n": len(ratings)}


def product_metrics(pred: dict, judgment: dict, refs: list[dict], idx: list[int] | None = None) -> dict:
    """idx: review indices (for bootstrap resampling); default all."""
    idx = list(range(len(refs))) if idx is None else idx
    tasks = pred.get("tasks") or []
    n_pred = len(tasks)
    tscore = {}
    for m in judgment["task_matches"]:
        k = (m["review"], m["pred_task"], m["ref_task"])
        tscore[k] = max(tscore.get(k, 0), m["score"])
    strict, partial, confirmed = [], [], set()
    for ri in idx:
        nref = len(refs[ri]["tasks"])
        if nref == 0:
            continue
        sc = {(p, r): s for (rv, p, r), s in tscore.items() if rv == ri}
        best = best_assignment(n_pred, list(range(nref)), sc)
        strict.append(sum(x == 2 for x in best) / nref)
        partial.append(sum(x >= 1 for x in best) / nref)
    for (rv, p, r), s in tscore.items():
        if s == 2 and rv in idx:
            confirmed.add(p)
    m = {
        "task_recall_strict": float(np.mean(strict)) if strict else None,
        "task_recall_partial": float(np.mean(partial)) if partial else None,
        "task_bearing_n": len(strict), "null_tasks": sum(1 for t in tasks if not (isinstance(t, dict) and t.get("action"))),
        "sample_confirmed_task_fraction": len(confirmed) / 5,
    }
    m.update(ease_metrics(pred.get("ease_of_use_probabilities_1_to_5"),
                          [refs[i]["ease_of_use_rating"] for i in idx if refs[i]["ease_of_use_rating"]]))
    # claims
    cbest = {}
    contra = set()
    for c in judgment["claim_matches"]:
        k = (c["review"], c["ref_polarity"], c["ref_claim"])
        cbest[k] = max(cbest.get(k, 0), c["score"])
        if c["contradiction"]:
            contra.add((c["pred_polarity"], c["pred_claim"], c["review"]))
    recs, b_recs, f_recs = [], [], []
    for ri in idx:
        for pol, bucket in (("benefit", b_recs), ("friction", f_recs)):
            n = len(refs[ri][pol + "s"])
            if n:
                hit = sum(cbest.get((ri, pol, ci), 0) == 2 for ci in range(n))
                bucket.append(hit / n)
        n = len(refs[ri]["benefits"]) + len(refs[ri]["frictions"])
        if n:
            hit = sum(cbest.get((ri, pol, ci), 0) == 2 for pol in ("benefit", "friction")
                      for ci in range(len(refs[ri][pol + "s"])))
            recs.append(hit / n)
    pclaims = [("benefit", i) for i, c in enumerate(pred.get("benefits") or []) if isinstance(c, dict) and c.get("claim")]
    pclaims += [("friction", i) for i, c in enumerate(pred.get("frictions") or []) if isinstance(c, dict) and c.get("claim")]
    claim_reviews = [ri for ri in idx if refs[ri]["benefits"] or refs[ri]["frictions"]]
    pairs = len(pclaims) * len(claim_reviews)
    n_contra = sum(1 for (pol, pi, ri) in contra if ri in claim_reviews) if pairs else 0
    confirmed_claims = {(c["pred_polarity"], c["pred_claim"]) for c in judgment["claim_matches"]
                        if c["score"] == 2 and c["review"] in idx}
    m.update({
        "bf_recall_strict": float(np.mean(recs)) if recs else None,
        "benefit_recall_strict": float(np.mean(b_recs)) if b_recs else None,
        "friction_recall_strict": float(np.mean(f_recs)) if f_recs else None,
        "claim_bearing_n": len(recs),
        "contradiction_rate": n_contra / pairs if pairs else None,
        "unconfirmed_claim_rate": (1 - len(confirmed_claims) / len(pclaims)) if pclaims else None,
        "predicted_claims": len(pclaims),
    })
    # audience
    fams = {role_family(s.get("role_family")) for s in (pred.get("segments") or [])[:3] if isinstance(s, dict)}
    fams.discard("unknown")
    hidden = [role_family(refs[i]["reviewer_job_title"]) for i in idx]
    ev = [f for f in hidden if f != "unknown"]
    m["audience_top3_coverage"] = (sum(f in fams for f in ev) / len(ev)) if ev else None
    m["audience_evaluable_n"] = len(ev)
    m["predicted_role_families"] = "|".join(sorted(fams))
    return m


def numeric_baselines(product: str, refs: list[dict]) -> list[dict]:
    ratings = [r["ease_of_use_rating"] for r in refs if r["ease_of_use_rating"]]
    out = []
    splits = read_json(OUT / "splits.json")
    pool_ids = {x["review_id"] for x in splits["products"][product]["pool"]}
    df, _ = load_capterra()
    pool = df[df.review_id.isin(pool_ids)].ease_of_use_rating.dropna().astype(int).tolist()
    for name, src in (("BASE_C_pack_dist", "C"), ("BASE_T_pack_dist", "T")):
        vals = [int(x["ease_of_use_rating"]) for x in read_json(PACKS / product / f"{src}.json")["items"]
                if x.get("ease_of_use_rating") in (1, 2, 3, 4, 5)]
        out.append((name, vals))
    out.append(("BASE_T_full_pool_dist", pool))
    rows = []
    for name, vals in out + [("BASE_uniform", None)]:
        probs = [0.2] * 5 if vals is None else [vals.count(k) / len(vals) for k in range(1, 6)]
        rows.append({"product": product, "condition": name, "replicate": 0, "evidence_n": len(vals or []),
                     **ease_metrics(probs, ratings)})
    return rows


JUDGE_METRICS = {"task_recall_strict", "task_recall_partial", "sample_confirmed_task_fraction", "bf_recall_strict",
                 "benefit_recall_strict", "friction_recall_strict", "contradiction_rate", "unconfirmed_claim_rate"}
METRIC_COLS = ["task_recall_strict", "task_recall_partial", "sample_confirmed_task_fraction", "ease_mae", "ease_rps",
               "bf_recall_strict", "benefit_recall_strict", "friction_recall_strict", "contradiction_rate",
               "unconfirmed_claim_rate", "audience_top3_coverage"]


def score(products: list[str]) -> None:
    refs_path = OUT / "reference_audit.jsonl"
    refs_all = read_jsonl(refs_path)
    if not refs_all:
        refs_all = extract_references("test", products)
        audit = {p: [r["review_id"] for r in refs_all if r["product"] == p][:4] for p in products}
        for r in refs_all:
            r["audit_sample"] = r["review_id"] in audit[r["product"]]
            r["audit_status"] = "pending_human_review" if r["audit_sample"] else "not_sampled"
        write_jsonl(refs_path, refs_all)
    refs = {p: [r for r in refs_all if r["product"] == p] for p in products}
    preds = [p for p in read_jsonl(OUT / "predictions.jsonl") if p["valid"] and p["product"] in products]
    judged = {(j["product"], j["condition"], j["replicate"]): j for j in read_jsonl(OUT / "judgments.jsonl")}
    order = list(preds)
    random.Random(7).shuffle(order)  # randomized judging order
    todo = [pr for pr in order if (pr["product"], pr["condition"], pr["replicate"]) not in judged
            or judged[(pr["product"], pr["condition"], pr["replicate"])].get("error")]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(WORKERS) as pool:
        for j in pool.map(lambda pr: judge_prediction(pr, refs[pr["product"]]), todo):
            judged[(j["product"], j["condition"], j["replicate"])] = j
    write_jsonl(OUT / "judgments.jsonl", list(judged.values()))
    rows = []
    for pr in preds:
        j = judged[(pr["product"], pr["condition"], pr["replicate"])]
        m = product_metrics(pr, j, refs[pr["product"]])
        if j.get("error"):
            m = {k: (None if k in JUDGE_METRICS else v) for k, v in m.items()}
        rows.append({"product": pr["product"], "condition": pr["condition"], "replicate": pr["replicate"],
                     **m, "predict_input_tokens": pr["input_tokens"], "predict_output_tokens": pr["output_tokens"],
                     "predict_cost_usd": pr["cost_usd"], "judge_cost_usd": j["cost_usd"],
                     "elapsed_s": pr["elapsed_s"], "judge_error": j.get("error")})
    for p in products:
        rows += numeric_baselines(p, refs[p])
    cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("product", "condition", "replicate"), k))
    with (OUT / "metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    write_json(OUT / "bootstrap.json", bootstrap(preds, judged, refs))
    leakage_checks()
    print(f"scored {len(preds)} predictions; total spend ${spent_usd():.3f}")


def bootstrap(preds, judged, refs, n=1000) -> dict:
    """Within-product paired review bootstrap for each comparison (replicate 1). Conditional on these 20 reviews."""
    by = {(p["product"], p["condition"], p["replicate"]): p for p in preds}
    rng = np.random.default_rng(42)
    out = {}
    for a, b, _ in COMPARISONS:
        for prod in PRODUCTS:
            if (prod, a, 1) not in by or (prod, b, 1) not in by \
                    or judged[(prod, a, 1)].get("error") or judged[(prod, b, 1)].get("error"):
                continue
            res = {k: [] for k in ("task_recall_strict", "ease_mae", "ease_rps", "bf_recall_strict")}
            nrev = len(refs[prod])
            for _ in range(n):
                idx = rng.integers(0, nrev, nrev).tolist()
                ma = product_metrics(by[(prod, a, 1)], judged[(prod, a, 1)], refs[prod], idx)
                mb = product_metrics(by[(prod, b, 1)], judged[(prod, b, 1)], refs[prod], idx)
                for k in res:
                    if ma[k] is not None and mb[k] is not None:
                        res[k].append(ma[k] - mb[k])
            out[f"{a}-{b}|{prod}"] = {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None
                                      for k, v in res.items()}
    return out


# ----------------------------------------------------------------------------- report


def fmt(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def report() -> None:
    m = pd.read_csv(OUT / "metrics.csv")
    model_rows = m[m.condition.isin(CONDITIONS)]
    base_rows = m[~m.condition.isin(CONDITIONS)]
    preds = read_jsonl(OUT / "predictions.jsonl")
    calls = _ledger()
    total_cost = sum(r["cost_usd"] for r in calls if not r.get("cached"))
    # macro over products, then mean over replicates
    macro = model_rows.groupby(["condition", "replicate"])[METRIC_COLS + ["predict_cost_usd", "judge_cost_usd"]].mean(numeric_only=True)
    macro_cost = model_rows.groupby(["condition", "replicate"])[["predict_cost_usd", "judge_cost_usd"]].sum()
    agg = macro.groupby("condition").mean()
    cost = macro_cost.groupby("condition").mean()
    L = ["# Staged-context pilot: which customer-context data helps?", "",
         "_Auto-generated tables; interpretation is in the Findings section. All scores are machine-extracted and "
         "machine-judged (provisional) unless the audit file says otherwise._", "",
         "## Results (macro-average over 3 products; mean over replicates)", "",
         "| Condition | Task recall ↑ | Ease MAE ↓ | Ease RPS ↓ | Benefit/friction recall ↑ | Reference disagreement ↓ | Cost |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for c in CONDITIONS:
        if c not in agg.index:
            L.append(f"| {c} ({'+'.join(['M'] + CONDITIONS[c])}) | not run | | | | | |")
            continue
        r = agg.loc[c]
        L.append(f"| {c} ({'+'.join(['M'] + CONDITIONS[c])}) | {fmt(r.task_recall_strict)} | {fmt(r.ease_mae)} | "
                 f"{fmt(r.ease_rps)} | {fmt(r.bf_recall_strict)} | {fmt(r.contradiction_rate)} | "
                 f"${cost.loc[c].predict_cost_usd + cost.loc[c].judge_cost_usd:.4f} |")
    L += ["", "Task recall = strict (score-2) one-to-one recall per task-bearing review. Reference disagreement = share of "
          "(predicted claim × claim-bearing review) pairs judged an explicit contradiction. Cost = prediction + judging "
          "for that condition's 3 product calls (extraction shared, reported below).", ""]
    L += ["### Secondary metrics", "", "| Condition | Partial task recall | Sample-confirmed task fraction | Benefit recall | "
          "Friction recall | Unconfirmed claim rate | Audience top-3 coverage |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for c in CONDITIONS:
        if c in agg.index:
            r = agg.loc[c]
            L.append(f"| {c} | {fmt(r.task_recall_partial)} | {fmt(r.sample_confirmed_task_fraction, 2)} | "
                     f"{fmt(r.benefit_recall_strict)} | {fmt(r.friction_recall_strict)} | "
                     f"{fmt(r.unconfirmed_claim_rate)} | {fmt(r.audience_top3_coverage)} |")
    L += ["", "### Numeric rating baselines (no model)", "", "| Baseline | Ease MAE ↓ | Ease RPS ↓ |", "| --- | --- | --- |"]
    for c, g in base_rows.groupby("condition"):
        L.append(f"| {c} | {fmt(g.ease_mae.mean())} | {fmt(g.ease_rps.mean())} |")
    L += ["", "## Paired deltas per product (replicate 1; positive = later condition higher)", "",
          "| Comparison | Product | Δ task recall | Δ ease MAE | Δ ease RPS | Δ B/F recall | 95% review-bootstrap Δ task recall |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    boot = read_json(OUT / "bootstrap.json") if (OUT / "bootstrap.json").exists() else {}
    r1 = model_rows[model_rows.replicate == 1].set_index(["product", "condition"])
    for a, b, q in COMPARISONS:
        for p in PRODUCTS:
            if (p, a) in r1.index and (p, b) in r1.index:
                x, y = r1.loc[(p, a)], r1.loc[(p, b)]
                ci = boot.get(f"{a}-{b}|{p}", {}).get("task_recall_strict")

                def d(k):
                    return fmt(x[k] - y[k]) if pd.notna(x[k]) and pd.notna(y[k]) else "n/a"
                L.append(f"| {a}−{b} | {p} | {d('task_recall_strict')} | {d('ease_mae')} | {d('ease_rps')} | "
                         f"{d('bf_recall_strict')} | {('[' + fmt(ci[0]) + ', ' + fmt(ci[1]) + ']') if ci else 'n/a'} |")
    reps = model_rows.replicate.nunique()
    if reps > 1:
        L += ["", "## Replicate variability (macro task recall / ease MAE per replicate)", ""]
        for c in CONDITIONS:
            if c in macro.index.get_level_values(0):
                vals = macro.loc[c]
                L.append(f"- {c}: task recall {', '.join(fmt(v) for v in vals.task_recall_strict)}; "
                         f"MAE {', '.join(fmt(v) for v in vals.ease_mae)}")
    L += ["", "## Denominators", ""]
    for p in PRODUCTS:
        g = model_rows[(model_rows["product"] == p)]
        if len(g):
            r = g.iloc[0]
            L.append(f"- {p}: task-bearing reviews {int(r.task_bearing_n)}/20, rated reviews {int(r.rating_n)}, "
                     f"claim-bearing {int(r.claim_bearing_n)}, audience-evaluable titles {int(r.audience_evaluable_n)}")
    L += ["", "## Examples (auto-selected; audit before relying on them)", ""] + examples()
    stage_cost = {}
    for r in calls:
        if not r.get("cached"):
            stage_cost[r["stage"]] = stage_cost.get(r["stage"], 0) + r["cost_usd"]
    errors = [r for r in calls if r.get("error")]
    L += ["", "## Cost and errors", "", f"- Total uncached model spend: ${total_cost:.4f} "
          f"({', '.join(f'{k} ${v:.4f}' for k, v in stage_cost.items())})",
          f"- Prediction model: {PREDICT_MODEL} (temperature {PREDICT_TEMPERATURE}); judge/extractor: {JUDGE_MODEL}",
          f"- Valid predictions: {sum(p['valid'] for p in preds)}/{len(preds)}; call errors logged: {len(errors)} "
          f"(by stage: {dict(pd.Series([r['stage'] for r in errors]).value_counts()) if errors else {}}); "
          f"judge sets still failed after rerun: {sum(bool(j.get('error')) for j in read_jsonl(OUT / 'judgments.jsonl'))}"]
    L += ["", "## Leakage checks", "", "```", json.dumps(read_json(OUT / "leakage_checks.json"), indent=2), "```"]
    (OUT / "report_tables.md").write_text("\n".join(L) + "\n")
    audit_sheet()
    task_brief()
    print((OUT / "report_tables.md").read_text())


def audit_sheet() -> None:
    """Side-by-side excerpts for human inspection: every judged contradiction and every strict task win."""
    preds = {(p["product"], p["condition"], p["replicate"]): p for p in read_jsonl(OUT / "predictions.jsonl") if p["valid"]}
    refs = {p: [r for r in read_jsonl(OUT / "reference_audit.jsonl") if r["product"] == p] for p in PRODUCTS}
    L = ["# Audit sheet (machine-judged; verify each row)", "", "## Contradictions", "",
         "| Product | Cond | Rep | Predicted claim | Hidden reference claim | Hidden span |", "| --- | --- | --- | --- | --- | --- |"]
    wins = []
    for j in read_jsonl(OUT / "judgments.jsonl"):
        k = (j["product"], j["condition"], j["replicate"])
        if j.get("error") or k not in preds:
            continue
        pr, rf = preds[k], refs[j["product"]]
        for c in j["claim_matches"]:
            if c["contradiction"]:
                pc = pr[c["pred_polarity"] + "s"][c["pred_claim"]]
                rc = rf[c["review"]][c["ref_polarity"] + "s"][c["ref_claim"]]
                L.append(f"| {k[0]} | {k[1]} | {k[2]} | {clean(pc.get('claim'))} | {clean(rc.get('claim'))} | "
                         f"{clean(rc.get('span'))[:160]} |")
        for m in j["task_matches"]:
            if m["score"] == 2:
                wins.append((k, fmt_task(pr["tasks"][m["pred_task"]]), fmt_task(rf[m["review"]]["tasks"][m["ref_task"]]),
                             clean(rf[m["review"]]["tasks"][m["ref_task"]].get("span"))[:160]))
    L += ["", "## Strict (score-2) task matches", "", "| Product | Cond | Rep | Predicted task | Reference task | Hidden span |",
          "| --- | --- | --- | --- | --- | --- |"]
    L += [f"| {k[0]} | {k[1]} | {k[2]} | {pt} | {rt} | {sp} |" for k, pt, rt, sp in sorted(wins)]
    (OUT / "audit_side_by_side.md").write_text("\n".join(L) + "\n")


def task_brief() -> None:
    """Export the best-supported task hypotheses: tasks strictly confirmed by >=2 hidden test reviews, any condition."""
    preds = {(p["product"], p["condition"], p["replicate"]): p for p in read_jsonl(OUT / "predictions.jsonl") if p["valid"]}
    brief = {"format": "generic task brief (no Atelier schema exists in this repo)", "source": "staged-context pilot",
             "evidence_note": "tasks confirmed by machine-judged strict matches against hidden 2024-era Capterra reviews",
             "products": {}}
    for p in PRODUCTS:
        hits = {}
        for j in read_jsonl(OUT / "judgments.jsonl"):
            k = (j["product"], j["condition"], j["replicate"])
            if j["product"] != p or j.get("error") or k not in preds:
                continue
            per_task = {}
            for m in j["task_matches"]:
                if m["score"] == 2:
                    per_task.setdefault(m["pred_task"], set()).add(m["review"])
            for ti, revs in per_task.items():
                t = preds[k]["tasks"][ti]
                key = fmt_task(t)
                h = hits.setdefault(key, {"task": t, "confirming_reviews": set(), "conditions": set()})
                h["confirming_reviews"] |= revs
                h["conditions"].add(k[1])
        ranked = sorted(hits.values(), key=lambda h: -len(h["confirming_reviews"]))
        brief["products"][p] = [{"action": h["task"].get("action"), "object": h["task"].get("object"),
                                 "context": h["task"].get("context"), "purpose": h["task"].get("purpose"),
                                 "confirming_test_reviews": len(h["confirming_reviews"]),
                                 "conditions": sorted(h["conditions"])}
                                for h in ranked if len(h["confirming_reviews"]) >= 2][:6]
    write_json(OUT / "task_brief.json", brief)


def examples() -> list[str]:
    """Reference tasks newly strictly matched (improvement) or lost (regression) between comparison pairs."""
    preds = {(p["product"], p["condition"], p["replicate"]): p for p in read_jsonl(OUT / "predictions.jsonl") if p["valid"]}
    judged = {(j["product"], j["condition"], j["replicate"]): j for j in read_jsonl(OUT / "judgments.jsonl")}
    refs = {p: [r for r in read_jsonl(OUT / "reference_audit.jsonl") if r["product"] == p] for p in PRODUCTS}
    imp, reg = [], []
    for a, b, _ in COMPARISONS:
        added = sorted(set(CONDITIONS[a]) ^ set(CONDITIONS[b]))
        for prod in PRODUCTS:
            ka, kb = (prod, a, 1), (prod, b, 1)
            if ka not in judged or kb not in judged or judged[ka].get("error") or judged[kb].get("error"):
                continue

            def hits(k):
                return {(m["review"], m["ref_task"]): m["pred_task"] for m in judged[k]["task_matches"] if m["score"] == 2}
            ha, hb = hits(ka), hits(kb)
            for (ri, ti), pi in ha.items():
                if (ri, ti) not in hb:
                    imp.append((a, b, prod, ri, ti, pi, None, added))
            for (ri, ti), pi in hb.items():
                if (ri, ti) not in ha:
                    reg.append((a, b, prod, ri, ti, None, pi, added))
    L = []
    for label, items in (("Improvements", imp), ("Regressions", reg)):
        L.append(f"**{label}** ({len(items)} reference tasks changed strict-match status across comparisons)")
        picked, used = [], set()
        for want_new_product in (True, False):  # spread across comparisons, then products
            for it in items:
                if len(picked) < 3 and it not in picked and (it[0], it[1]) not in {(x[0], x[1]) for x in picked} \
                        and (not want_new_product or it[2] not in used):
                    picked.append(it)
                    used.add(it[2])
        for a, b, prod, ri, ti, pa, pb, added in picked:
            ref = refs[prod][ri]["tasks"][ti]
            before = fmt_task(preds[(prod, b, 1)]["tasks"][pb]) if pb is not None else "no strict match in " + b
            after = fmt_task(preds[(prod, a, 1)]["tasks"][pa]) if pa is not None else "no strict match in " + a
            L += [f"- {prod}, {b} → {a} (pack difference: {', '.join(added)}): before `{before}`; after `{after}`; "
                  f"hidden review span: \"{clean(ref.get('span'))[:200]}\""]
        if not items:
            L.append("- none observed")
    return L


# ----------------------------------------------------------------------------- smoke + estimate


def estimate() -> dict:
    """Projected spend from prompt sizes (approx tokens) before any test scoring."""
    out_pred, out_judge, out_extract = 3000, 3000, 1500  # incl. thinking tokens, conservative
    pin, pout = PRICES.get(PREDICT_MODEL, (0, 0))
    jin, jout = PRICES.get(JUDGE_MODEL, (0, 0))
    pred_in = sum(approx_tokens(PREDICT_SYSTEM + build_predict_prompt(p, c, load_packs(p)))
                  for p in PRODUCTS for c in CONDITIONS if all(k in load_packs(p) for k in CONDITIONS[c]))
    n_pred = 24
    pred_cost = pred_in / 1e6 * pin + n_pred * out_pred / 1e6 * pout
    ext_cost = 75 * (900 / 1e6 * jin + out_extract / 1e6 * jout)
    judge_cost = n_pred * (3500 / 1e6 * jin + out_judge / 1e6 * jout)
    onet_cost = 3 * (16000 / 1e6 * jin + 2000 / 1e6 * jout)
    est = {"predict_model": PREDICT_MODEL, "judge_model": JUDGE_MODEL, "prediction_input_tokens_1rep": pred_in,
           "per_rep_prediction_usd": round(pred_cost, 3), "extraction_usd": round(ext_cost, 3),
           "judging_usd_per_rep": round(judge_cost, 3), "onet_mapping_usd": round(onet_cost, 3),
           "total_1rep_usd": round(pred_cost + ext_cost + judge_cost + onet_cost, 3),
           "total_2rep_usd": round(2 * (pred_cost + judge_cost) + ext_cost + onet_cost, 3), "cap_usd": SPEND_CAP}
    write_json(OUT / "cost_estimate.json", est)
    return est


def smoke(product: str) -> None:
    """S0 and S4 on one product, scored against its development rows only."""
    packs = load_packs(product)
    preds = [run_prediction(product, c, 1, packs) for c in ("S0", "S4")]
    refs = extract_references("dev", [product])
    write_jsonl(OUT / "smoke" / "dev_references.jsonl", refs)
    res = []
    for pr in preds:
        if not pr["valid"]:
            res.append({"condition": pr["condition"], "valid": False, "errors": pr["errors"]})
            continue
        j = judge_prediction(pr, refs)
        res.append({"condition": pr["condition"], "valid": True, **product_metrics(pr, j, refs),
                    "predict_tokens": [pr["input_tokens"], pr["output_tokens"]], "predict_cost": pr["cost_usd"]})
    write_jsonl(OUT / "smoke" / "smoke_predictions.jsonl", preds)
    write_json(OUT / "smoke" / "smoke_result.json", {"product": product, "results": res, "spent_usd": spent_usd(),
                                                     "estimate": estimate()})
    print(json.dumps(read_json(OUT / "smoke" / "smoke_result.json"), indent=2, default=str))


# ----------------------------------------------------------------------------- CLI


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--seed", type=int, default=42)
    sub.add_parser("onet")
    sub.add_parser("estimate")
    s = sub.add_parser("smoke")
    s.add_argument("--product", default="Asana")
    p = sub.add_parser("predict")
    p.add_argument("--conditions", default="all")
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--products", default=",".join(PRODUCTS))
    p = sub.add_parser("score")
    p.add_argument("--products", default=",".join(PRODUCTS))
    sub.add_parser("report")
    sub.add_parser("check")
    sub.add_parser("baselines")
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(a.seed)
    elif a.cmd == "onet":
        build_onet()
    elif a.cmd == "estimate":
        print(json.dumps(estimate(), indent=2))
    elif a.cmd == "smoke":
        smoke(a.product)
    elif a.cmd == "predict":
        conds = list(CONDITIONS) if a.conditions == "all" else a.conditions.split(",")
        predict(conds, a.repetitions, a.products.split(","))
    elif a.cmd == "score":
        score(a.products.split(","))
    elif a.cmd == "report":
        report()
    elif a.cmd == "baselines":
        rows = []
        for prod in PRODUCTS:
            refs = [{"ease_of_use_rating": int(r["ease_of_use_rating"]) if r.get("ease_of_use_rating") in (1, 2, 3, 4, 5) else None}
                    for r in read_jsonl(HIDDEN / f"test_{prod}.jsonl")]
            rows += numeric_baselines(prod, refs)
        pd.DataFrame(rows).to_csv(OUT / "baselines_model_free.csv", index=False)
        print(pd.DataFrame(rows).to_string(index=False))
    elif a.cmd == "check":
        print(json.dumps(leakage_checks(), indent=2))


if __name__ == "__main__":
    main()
