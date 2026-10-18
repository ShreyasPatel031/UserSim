"""M/D/P/O/C/T/Q packets for the v2 cases (5 products x 5), same recipe and helpers as build_packets.py.

Peers for D and C come from the same 5-product set: work-management products are each other's peers;
Pipedrive (CRM) has no CRM peer in the set, so its peers are the two closest pipeline/sheet tools.
Writes v2/packets/<case_id>.json (gitignored: quotes evidence prose) and v2/packets/manifest.json.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import build_packets as BP

HERE = Path(__file__).resolve().parent
V2 = HERE / "v2"

M_TEXT = {
    **BP.M_TEXT,
    "Notion": "Notion is a web-based workspace for notes, documents, wikis, databases and project tracking.",
    "Smartsheet": "Smartsheet is a web-based, spreadsheet-style platform for planning, tracking and managing work.",
    "Pipedrive": "Pipedrive is a web-based sales CRM for managing leads, deals and sales pipelines.",
}
PAGES = {
    **BP.PAGES,
    "Notion": {"landing": ("https://www.notion.so/", "www.notion.so_.html", 2800),
               "feature": ("https://www.notion.so/product", "www.notion.so_product.html", 3600),
               "overview": ("https://www.notion.so/", "www.notion.so_.html", 1800)},
    "Smartsheet": {"landing": ("https://www.smartsheet.com/", "www.smartsheet.com_.html", 2800),
                   "feature": ("https://www.smartsheet.com/platform", "www.smartsheet.com_platform.html", 3600),
                   "overview": ("https://www.smartsheet.com/platform", "www.smartsheet.com_platform.html", 1800)},
    "Pipedrive": {"landing": ("https://www.pipedrive.com/", "www.pipedrive.com_.html", 2800),
                  "feature": ("https://www.pipedrive.com/en/features", "www.pipedrive.com_en_features.html", 3600),
                  "overview": ("https://www.pipedrive.com/en/features", "www.pipedrive.com_en_features.html", 1800)},
}
PEERS = {"Asana": ["ClickUp", "Notion"], "ClickUp": ["Asana", "Notion"], "Notion": ["Asana", "ClickUp"],
         "Smartsheet": ["Asana", "ClickUp"], "Pipedrive": ["Smartsheet", "ClickUp"]}


def build_d(product: str) -> dict:
    a, b = PEERS[product]
    parts = []
    for label, (prod, key) in {"target landing": (product, "landing"), "target feature page": (product, "feature"),
                               f"peer overview: {a}": (a, "overview"), f"peer overview: {b}": (b, "overview")}.items():
        url, fname, budget = PAGES[prod][key]
        text, truncated = BP.page_passages(fname, budget)
        parts.append({"label": label, "product": prod, "url": url, "capture_date": BP.CAPTURE_DATE,
                      "text": text, "truncated": truncated})
    text = "\n\n".join(f"## {p['label']} ({p['url']}, captured {p['capture_date']})\n{p['text']}" for p in parts)
    return {"pack": "D", "sources": [{k: v for k, v in p.items() if k != "text"} for p in parts],
            "text": text, "tokens_est": BP.tok(text)}


def reviews(pack: str, products: list[str], strip: list[str]) -> dict:
    rows, ids, trunc, removed = [], [], 0, 0
    for prod in products:
        for line in (V2 / "evidence" / f"{prod}.jsonl").read_text().splitlines()[:10]:
            r = json.loads(line)
            text, t, rm = BP.serialize_review(r, strip)
            rows.append(text); ids.append(r["evidence_id"]); trunc += t; removed += rm
    text = "\n".join(rows)
    return {"pack": pack, "evidence_ids": ids, "text": text, "tokens_est": BP.tok(text),
            "truncated_reviews": trunc, "sentences_removed_naming_target": removed}


async def main() -> None:
    cases = {c["case_id"]: c for c in map(json.loads, (V2 / "inputs/cases.jsonl").open())}
    tasks = [json.loads(l) for l in (V2 / "inputs/e2e_tasks.jsonl").open()]
    out = V2 / "packets"
    out.mkdir(exist_ok=True)
    onet = BP.onet_tables()
    d_cache = {p: build_d(p) for p in PEERS}
    manifest = {"token_estimate": "chars/4", "capture_date": BP.CAPTURE_DATE, "onet_version": "31.0", "cases": {}}
    for t in tasks:
        case = cases[t["case_id"]]
        prod = case["product"]
        prof = {k: case["profile"].get(k) for k in BP_PROFILE}
        p_text = "\n".join(f"{k.replace('reviewer_', '').replace('_', ' ')}: {v if v is not None else 'unknown'}"
                           for k, v in prof.items())
        q = BP.build_q({**t, "limits": {**t["limits"], "max_minutes": t["limits"].get("max_minutes", 10)}})
        packets = {"M": {"pack": "M", "product": prod, "url": case["url"], "text": f"{prod} ({case['url']}): {M_TEXT[prod]}"},
                   "D": d_cache[prod], "P": {"pack": "P", "fields": list(prof), "text": p_text},
                   "O": await BP.build_o(prof, onet), "C": reviews("C", PEERS[prod], [prod]),
                   "T": reviews("T", [prod], []), "Q": q}
        for v in packets.values():
            v.setdefault("tokens_est", BP.tok(v["text"]))
            v["sha256"] = BP.sha(v["text"])
        (out / f"{t['case_id']}.json").write_text(json.dumps(packets, indent=1, ensure_ascii=False))
        manifest["cases"][t["case_id"]] = {"product": prod, "packets": {k: {kk: vv for kk, vv in v.items() if kk != "text"}
                                                                         for k, v in packets.items()}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print("packets", len(manifest["cases"]))


BP_PROFILE = ["reviewer_job_title", "reviewer_industry", "reviewer_company_size", "reviewer_time_used_product"]

if __name__ == "__main__":
    asyncio.run(main())
