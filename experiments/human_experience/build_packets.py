"""Build the frozen M/D/P/O/C/T/Q evidence packets for the phase-B cases.

Reads only permitted inputs: pack/inputs, pack/evidence, public pages cached
under cache/pages, and O*NET 31.0 under cache/onet. Never reads
pack/evaluator_only. Writes packets/<case_id>.json and packets/manifest.json.

Token counts are chars/4 estimates (documented in the manifest); the forecast
call's own usageMetadata records the real prompt size.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

import llm

HERE = Path(__file__).resolve().parent
PACK = HERE / "pack"
CACHE = HERE / "cache"
OUT = HERE / "packets"
PRODUCTS = ["Asana", "Trello", "ClickUp"]

M_TEXT = {
    "Asana": "Asana is a web-based work and project management application for organizing tasks, projects and team workflows.",
    "Trello": "Trello is a web-based board-and-card application for organizing tasks and projects.",
    "ClickUp": "ClickUp is a web-based work management application that combines tasks, projects, documents and team collaboration tools.",
}

# (url, cached file, char budget). Target gets its landing + one feature page;
# each peer contributes one overview. 10,000 chars ~= the 2,500-token cap.
PAGES = {
    "Asana": {
        "landing": ("https://asana.com/", "asana.com_.html", 2800),
        "feature": ("https://asana.com/features", "asana.com_features.html", 3600),
        "overview": ("https://asana.com/features", "asana.com_features.html", 1800),
    },
    "Trello": {
        "landing": ("https://trello.com/", "trello.com_.html", 2800),
        "feature": ("https://trello.com/tour", "trello.com_tour.html", 3600),
        # trello.com is mostly sign-up form and testimonials; the tour is its overview.
        "overview": ("https://trello.com/tour", "trello.com_tour.html", 1800),
    },
    "ClickUp": {
        "landing": ("https://clickup.com/", "clickup.com_.html", 2800),
        "feature": ("https://clickup.com/features", "clickup.com_features.html", 3600),
        "overview": ("https://clickup.com/features", "clickup.com_features.html", 1800),
    },
}
CAPTURE_DATE = "2026-10-18"

# Testimonials, ratings, review snippets, popularity and adoption numbers.
_DROP = re.compile(
    r"\d+(\.\d+)?\s*%|\b\d[\d,.]*\+?\s*(million|customers|companies|teams|users|organizations|enterprises)\b|"
    r"\bmillions\b|\btrusted by\b|\btrust (asana|trello|clickup)\b|\brated\b|\breview|\bstars?\b|\bg2\b|capterra|"
    r"\baward|\bleader in\b|\bcustomers (say|chose|report)|\btestimonial|privacy policy|accurate as of|"
    r"\b(director|manager|officer|ceo|cto|vp|head of|founder|lead)\b.{0,40}\bat\b|"
    r"^[A-Z][\w.&,' -]{0,60}(Officer|Director|Manager|Engineer|Designer|Lead|COS)$",
    re.I,
)


def tok(text: str) -> int:
    return (len(text) + 3) // 4


def sha(obj) -> str:
    return hashlib.sha256(llm.dumps(obj).encode()).hexdigest()


def page_passages(fname: str, budget: int) -> tuple[str, bool]:
    html = (CACHE / "pages" / fname).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        t.decompose()
    lines, seen, used = [], set(), 0
    truncated = False
    for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):
        x = " ".join(el.get_text(" ", strip=True).split())
        if len(x) < 25 or x in seen or _DROP.search(x):
            continue
        seen.add(x)
        if used + len(x) + 1 > budget:
            truncated = True
            break
        lines.append(x)
        used += len(x) + 1
    return "\n".join(lines), truncated


def build_d(product: str) -> dict:
    peers = [p for p in PRODUCTS if p != product]
    parts = []
    for label, (prod, key) in {
        "target landing": (product, "landing"),
        "target feature page": (product, "feature"),
        f"peer overview: {peers[0]}": (peers[0], "overview"),
        f"peer overview: {peers[1]}": (peers[1], "overview"),
    }.items():
        url, fname, budget = PAGES[prod][key]
        text, truncated = page_passages(fname, budget)
        parts.append({"label": label, "product": prod, "url": url, "capture_date": CAPTURE_DATE,
                      "text": text, "truncated": truncated})
    text = "\n\n".join(f"## {p['label']} ({p['url']}, captured {p['capture_date']})\n{p['text']}" for p in parts)
    return {"pack": "D", "sources": [{k: v for k, v in p.items() if k != "text"} for p in parts],
            "text": text, "tokens_est": tok(text)}


REVIEW_FIELDS = [("pros", "pros"), ("cons", "cons"), ("general_comments", "comments"),
                 ("reasons_for_choosing", "reasons for choosing"), ("reasons_for_switching", "reasons for switching")]


def _num(v: str) -> str:
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return "n/a"


def serialize_review(r: dict, strip_names: list[str]) -> tuple[str, bool, int]:
    """Fixed serialization, <=250 tokens. Sentences naming ``strip_names`` are removed."""
    removed = 0
    body = []
    for key, label in REVIEW_FIELDS:
        text = " ".join(str(r.get(key) or "").split())
        if not text:
            continue
        if strip_names:
            sents = re.split(r"(?<=[.!?])\s+", text)
            keep = [s for s in sents if not any(re.search(rf"\b{re.escape(n)}\b", s, re.I) for n in strip_names)]
            removed += len(sents) - len(keep)
            text = " ".join(keep)
        if text:
            body.append(f"{label}: {text}")
    head = (
        f"[{r['evidence_id']}] product={r['product_name']} | role={r['reviewer_job_title'] or 'n/a'}; "
        f"industry={r['reviewer_industry'] or 'n/a'}; size={r['reviewer_company_size'] or 'n/a'}; "
        f"used={r['reviewer_time_used_product'] or 'n/a'} | ratings: overall {_num(r['overall_rating'])}, "
        f"ease {_num(r['ease_of_use_rating'])}, functionality {_num(r['functionality_rating'])}, "
        f"value {_num(r['value_for_money_rating'])}"
    )
    text = head + " | " + " | ".join(body)
    truncated = len(text) > 1000
    if truncated:
        text = text[:997].rsplit(" ", 1)[0] + "..."
    return text, truncated, removed


def evidence(product: str) -> list[dict]:
    return [json.loads(l) for l in (PACK / "evidence" / "reviews" / f"{product}.jsonl").read_text().splitlines() if l]


def build_reviews(pack: str, products: list[str], strip_names: list[str]) -> dict:
    rows, ids, trunc, removed = [], [], 0, 0
    for prod in products:
        for r in evidence(prod)[:10]:
            text, t, rm = serialize_review(r, strip_names)
            rows.append(text)
            ids.append(r["evidence_id"])
            trunc += t
            removed += rm
    text = "\n".join(rows)
    return {"pack": pack, "evidence_ids": ids, "text": text, "tokens_est": tok(text),
            "truncated_reviews": trunc, "sentences_removed_naming_target": removed}


def onet_tables():
    occ = {r["O*NET-SOC Code"]: r["Title"] for r in csv.DictReader((CACHE / "onet" / "occupation_data.csv").open())}
    tasks: dict[str, list[dict]] = {}
    for r in csv.DictReader((CACHE / "onet" / "task_statements.csv").open()):
        tasks.setdefault(r["O*NET-SOC Code"], []).append(r)
    importance: dict[str, float] = {}
    for r in csv.DictReader((CACHE / "onet" / "task_ratings.csv").open()):
        if r["Scale ID"] == "IM":
            importance[r["Task ID"]] = float(r["Data Value"])
    return occ, tasks, importance


ONET_PROMPT = """Map a software reviewer's recorded job title to O*NET-SOC occupations.
Use only the job title, industry and company size below. Choose at most three plausible
occupations from the list. If the title is too vague or generic to map, return an empty list.

Job title: {title}
Industry: {industry}
Company size: {size}

O*NET occupations (code | title):
{occupations}

JSON: {{"occupations": [{{"code": "..", "why": "at most 12 words"}}]}}"""


async def build_o(profile: dict, onet) -> dict:
    occ, tasks, importance = onet
    listing = "\n".join(f"{c} | {t}" for c, t in occ.items())
    res = await llm.call(ONET_PROMPT.format(
        title=profile.get("reviewer_job_title") or "n/a",
        industry=profile.get("reviewer_industry") or "n/a",
        size=profile.get("reviewer_company_size") or "n/a",
        occupations=listing,
    ))
    picked = [o for o in (res["json"] or {}).get("occupations", []) if o.get("code") in occ][:3]
    statements, used = [], 0
    for o in picked:
        core = [t for t in tasks.get(o["code"], []) if t["Task Type"] == "Core"] or tasks.get(o["code"], [])
        core.sort(key=lambda t: -importance.get(t["Task ID"], 0.0))
        for t in core[:4]:
            line = f"[{o['code']} {occ[o['code']]} | task {t['Task ID']}] {t['Task']}"
            if used + len(line) + 1 > 4000:
                break
            statements.append({"code": o["code"], "task_id": t["Task ID"], "line": line})
            used += len(line) + 1
    text = "\n".join(s["line"] for s in statements)
    return {"pack": "O", "status": "ok" if statements else "missing_role_mapping",
            "onet_version": "31.0", "mapping": picked,
            "task_ids": [s["task_id"] for s in statements], "text": text, "tokens_est": tok(text),
            "mapping_call": {"model": res["model"], "model_version": res["model_version"], "usage": res["usage"]}}


def build_q(task: dict) -> dict:
    fx = task["fixture"]
    text = (
        f"Goal: {task['goal']}\n"
        f"Synthetic fixture: {fx['instructions']} Use only these synthetic names: {', '.join(fx['names'])}.\n"
        f"Success checks: {'; '.join(task['success_criteria'])}\n"
        f"Limits: at most {task['limits']['max_minutes']} minutes and {task['limits']['max_actions']} actions; "
        f"no purchases, no real invites or external messages."
    )
    return {"pack": "Q", "text": text, "tokens_est": tok(text),
            "fields": ["goal", "fixture.instructions", "fixture.names", "success_criteria", "limits"]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-12", action="store_true", help="also build the extended task cases")
    a = ap.parse_args()
    cases = {c["case_id"]: c for c in map(json.loads, (PACK / "inputs" / "cases.jsonl").read_text().splitlines())}
    tasks = [json.loads(l) for l in (PACK / "inputs" / "e2e_tasks.jsonl").read_text().splitlines() if l]
    tasks = [t for t in tasks if a.all_12 or t["core_smoke_subset"]]
    OUT.mkdir(exist_ok=True)
    onet = onet_tables()
    d_cache = {p: build_d(p) for p in PRODUCTS}
    manifest = {"token_estimate": "chars/4", "capture_date": CAPTURE_DATE, "onet_version": "31.0",
                "source_sha256": json.loads((PACK / "config" / "source.json").read_text())["sha256"], "cases": {}}
    for t in tasks:
        case = cases[t["case_id"]]
        prod = case["product"]
        peers = [p for p in PRODUCTS if p != prod]
        prof = {k: case["profile"].get(k) for k in
                ["reviewer_job_title", "reviewer_industry", "reviewer_company_size", "reviewer_time_used_product"]}
        p_text = "\n".join(f"{k.replace('reviewer_', '').replace('_', ' ')}: {v if v is not None else 'unknown'}"
                           for k, v in prof.items())
        packets = {
            "M": {"pack": "M", "product": prod, "url": case["url"], "text": f"{prod} ({case['url']}): {M_TEXT[prod]}"},
            "D": d_cache[prod],
            "P": {"pack": "P", "fields": list(prof), "text": p_text, "status": case["profile_status"]},
            "O": await build_o(prof, onet),
            "C": build_reviews("C", peers, [prod]),
            "T": build_reviews("T", [prod], []),
            "Q": build_q(t),
        }
        for k, v in packets.items():
            v.setdefault("tokens_est", tok(v["text"]))
            v["sha256"] = sha(v["text"])
        (OUT / f"{t['case_id']}.json").write_text(json.dumps(packets, indent=1, ensure_ascii=False))
        manifest["cases"][t["case_id"]] = {
            "product": prod, "core": t["core_smoke_subset"],
            "packets": {k: {kk: vv for kk, vv in v.items() if kk != "text"} for k, v in packets.items()},
        }
        print(t["case_id"], prod, {k: v["tokens_est"] for k, v in packets.items()}, packets["O"]["status"])
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
