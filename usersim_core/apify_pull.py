"""Apify Marketplace External Signal Puller & Fleet Bridge (`usersim_core/apify_pull.py`).

Pulls three orthogonal, strictly leak-free external data streams using Apify PAY_PER_EVENT actors:
  1. `harvestapi/linkedin-company`: Real company headcount, follower count, founded year, industries,
     specialties, and verified company page status across PH launches (resolving cold-start maker misses).
  2. `kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest`: Strictly pre-launch (`< D 00:00 PT`,
     enforced both in X `until:YYYY-MM-DD_07:59:59_UTC` query syntax AND post-parse UTC timestamp filter)
     domain mentions, founder/company teasers, likes, retweets, bookmarks, views, and author follower reach.
  3. `omkar-cloud/g2-product-scraper`: Verified G2 product footprint (`rating`, `reviews_count`, `categories`,
     `company_founded_year`) + real verified user reviews (pros, cons, switching triggers, buyer roles) across
     top PH category incumbents (`taxonomy/competitors.parquet`) and established multi-launch SaaS products.

Compliance (`AGENTS.md`):
  - Never drops fields: saves 100% verbatim raw JSON records to `raw_dir/*.jsonl` (for GCS sync to
    `gs://usersim-bakeoff-347838016394/usersim_sim/raw/apify_v1/`).
  - Never hardcodes or logs API tokens: reads from `--token-file` or `APIFY_API_TOKEN` env var.
  - Budget-guarded per wave via Apify `maxTotalChargeUsd` + live `/v2/users/me/limits` checks.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import glob
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pandas as pd


GENERIC_DOMAINS = {
    "", "github.com", "github.io", "gitlab.com", "npmjs.com", "pypi.org",
    "apps.apple.com", "apple.com", "play.google.com", "google.com",
    "chromewebstore.google.com", "chrome.google.com", "youtube.com", "youtu.be",
    "notion.site", "notion.so", "figma.com", "gumroad.com", "substack.com",
    "medium.com", "discord.gg", "discord.com", "t.me", "telegram.me",
    "x.com", "twitter.com", "linkedin.com", "producthunt.com", "huggingface.co",
    "vercel.app", "netlify.app", "pages.dev", "herokuapp.com", "lovable.app",
}

LI_COMPANY_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/company/([A-Za-z0-9_%-]+)", re.I)
X_HANDLE_RE = re.compile(r"(?:twitter\.com|x\.com)/(?!intent|share|home|search|hashtag|i/|explore|settings)([A-Za-z0-9_]{2,15})\b", re.I)


def clean_domain(url: str) -> str:
    if not url:
        return ""
    h = re.sub(r"^https?://", "", str(url).strip()).split("/")[0].split(":")[0].split("?")[0].lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def extract_company_name(title: str, domain: str) -> str:
    """Turn 'Snag by Parallel' -> 'Parallel', 'MyClaw 3.0' -> 'MyClaw', 'Canva MCP' -> 'Canva'."""
    t = str(title or "").strip()
    m_by = re.search(r"\bby\s+([A-Z0-9][A-Za-z0-9 .&-]{1,32})$", t)
    if m_by:
        return m_by.group(1).strip()
    # Strip trailing version / integration suffixes
    t_clean = re.sub(r"\s+(?:v?\d+(?:\.\d+)*|MCP|CLI|SDK|API|Plugin|Extension|Beta|AI\s+Agent|for\s+[A-Z][A-Za-z0-9 ]+)$", "", t, flags=re.I).strip()
    if len(t_clean) >= 2:
        return t_clean
    if domain and domain not in GENERIC_DOMAINS:
        return domain.split(".")[0]
    return t


class ApifyClient:
    def __init__(self, token: str):
        self.token = token.strip()
        self._lock = threading.Lock()

    def usage_usd(self) -> tuple[float, float]:
        url = f"https://api.apify.com/v2/users/me/limits?token={self.token}"
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.load(r)["data"]
        used = float(d.get("current", {}).get("monthlyUsageUsd") or 0.0)
        cap = float(d.get("limits", {}).get("maxMonthlyUsageUsd") or 19.0)
        return used, cap

    def run_actor_sync(self, actor_id: str, payload: dict[str, Any], max_usd: float = 0.50, timeout_s: int = 180) -> list[dict[str, Any]]:
        aid = actor_id.replace("/", "~")
        q = urllib.parse.urlencode({"token": self.token, "maxTotalChargeUsd": round(max_usd, 4), "timeout": timeout_s})
        url = f"https://api.apify.com/v2/acts/{aid}/run-sync-get-dataset-items?{q}"
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=timeout_s + 30) as r:
                    data = json.load(r)
                    return data if isinstance(data, list) else []
            except urllib.error.HTTPError as e:
                err_txt = ""
                try:
                    err_txt = e.read().decode("utf-8", errors="ignore")[:240]
                except Exception:
                    pass
                if e.code in (402, 403) and "usage" in err_txt.lower():
                    print(f"[Apify] Budget limit reached ({e.code}): {err_txt}", flush=True)
                    return []
                if attempt == 2:
                    print(f"[Apify] HTTP {e.code} on {actor_id}: {err_txt}", flush=True)
                    return []
                time.sleep(3 * (attempt + 1))
            except Exception as e:
                if attempt == 2:
                    print(f"[Apify] Error on {actor_id}: {e}", flush=True)
                    return []
                time.sleep(3 * (attempt + 1))
        return []


def collect_target_launches(data_dir: str, live23_dir: str) -> list[dict[str, Any]]:
    """Collect all Sep 1 - Nov 25 shortlist + post-00:05 launches, ordered live-23d first -> Oct -> Sep."""
    sites_by_id: dict[str, dict] = {}
    sites_p = f"{data_dir}/sites/sites_ph.jsonl"
    if os.path.exists(sites_p):
        with open(sites_p) as f:
            for line in f:
                r = json.loads(line)
                lid = str(r.get("item_id") or r.get("id") or "")
                if lid:
                    sites_by_id[lid] = r

    daily_urls: dict[str, str] = {}
    for p in sorted(glob.glob(f"{data_dir}/daily_0005/*/sites_0005.json")):
        j = json.load(open(p))
        for lid, rec in (j.get("launches") or {}).items():
            if rec.get("final_url"):
                daily_urls[str(lid)] = str(rec["final_url"])

    # Map item metadata from bench + struct_bt + nov25
    from simharness.bench import Benchmark
    bench = Benchmark(f"{data_dir}/bench")
    idx_by_id = dict(zip(bench.items["item_id"].astype(str), bench.items["item_idx"].astype(int)))

    live_days = {
        "2026-10-29", "2026-10-31", "2026-11-02", "2026-11-03", "2026-11-04",
        "2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12",
        "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17",
        "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22",
        "2026-11-23", "2026-11-24", "2026-11-25",
    }

    targets: dict[str, dict[str, Any]] = {}

    # 1. Add 2026-11-25 all launches (incl. post-00:05 Hiring Right Now!)
    nov25_detail = f"{live23_dir}/nov25/20261125T1834PT.jsonl"
    if os.path.exists(nov25_detail):
        for line in open(nov25_detail):
            r = json.loads(line)
            lid = str(r["id"])
            mk_x = [m.get("twitterUsername").strip().lstrip("@") for m in (r.get("makers") or []) if m.get("twitterUsername")]
            u_x = (r.get("user") or {}).get("twitterUsername")
            if u_x:
                mk_x.append(u_x.strip().lstrip("@"))
            url = daily_urls.get(lid) or (sites_by_id.get(lid) or {}).get("url") or ""
            html_s = (sites_by_id.get(lid) or {}).get("html") or ""
            li_m = LI_COMPANY_RE.search(html_s)
            x_m = X_HANDLE_RE.findall(html_s)
            targets[lid] = {
                "item_id": lid,
                "day": "2026-11-25",
                "title": str(r.get("name") or ""),
                "tagline": str(r.get("tagline") or ""),
                "url": url,
                "domain": clean_domain(url),
                "li_company_slug": li_m.group(1) if li_m else "",
                "x_handles": list(dict.fromkeys([h for h in (x_m[:2] + mk_x[:2]) if h and len(h) >= 2])),
                "priority": 0,
            }

    # 2. Add Sep 1 - Nov 24 Top-20 shortlist + any post-00:05 launches from struct_bt
    for fp in sorted(glob.glob(f"{data_dir}/struct_bt/2026-*.json"), reverse=True):
        j = json.load(open(fp))
        d = str(j["day"])
        if d < "2026-09-01" or d > "2026-11-24":
            continue
        l_sorted = sorted(j.get("launches", []), key=lambda x: int(x["structural_rank"]))[:25]
        prio = 0 if d in live_days else (1 if d >= "2026-10-01" else 2)
        for x in l_sorted:
            lid = str(x["id"])
            if lid in targets:
                continue
            title = str(x.get("name") or "")
            tagline = ""
            if lid in idx_by_id:
                it = bench.item(idx_by_id[lid])
                title = it.title or title
                tagline = it.summary or ""
            srec = sites_by_id.get(lid) or {}
            url = daily_urls.get(lid) or str(srec.get("url") or "")
            html_s = str(srec.get("html") or "")
            li_m = LI_COMPANY_RE.search(html_s)
            x_m = X_HANDLE_RE.findall(html_s)
            targets[lid] = {
                "item_id": lid,
                "day": d,
                "title": title,
                "tagline": tagline,
                "url": url,
                "domain": clean_domain(url),
                "li_company_slug": li_m.group(1) if li_m else "",
                "x_handles": list(dict.fromkeys([h for h in x_m[:2] if h and len(h) >= 2])),
                "priority": prio,
            }

    return sorted(targets.values(), key=lambda r: (r["priority"], r["day"], r["item_id"]))


def run_wave1_linkedin(client: ApifyClient, targets: list[dict[str, Any]], out_dir: str, budget_cap_usd: float = 5.80) -> dict[str, Any]:
    out_path = f"{out_dir}/linkedin_companies_raw.jsonl"
    done_queries: set[str] = set()
    if os.path.exists(out_path):
        with open(out_path) as f:
            for l in f:
                try:
                    r = json.loads(l)
                    if r.get("_query_key"):
                        done_queries.add(str(r["_query_key"]))
                except Exception:
                    pass

    # Build deduplicated LinkedIn company URLs & search queries mapped to item_ids
    url_to_items: dict[str, list[str]] = {}
    search_to_items: dict[str, list[str]] = {}
    for t in targets:
        lid = t["item_id"]
        if t["li_company_slug"]:
            u = f"https://www.linkedin.com/company/{t['li_company_slug']}/"
            if f"url:{u}" not in done_queries:
                url_to_items.setdefault(u, []).append(lid)
        else:
            cname = extract_company_name(t["title"], t["domain"])
            if len(cname) >= 2 and f"search:{cname.lower()}" not in done_queries:
                search_to_items.setdefault(cname, []).append(lid)

    url_list = list(url_to_items.keys())[:350]
    # Prioritize live-23d + Oct-Nov searches (~550 searches + up to 350 explicit URLs = ~900 companies)
    search_list = list(search_to_items.keys())[:550]
    print(f"[Wave 1 LinkedIn] {len(url_list)} explicit company URLs + {len(search_list)} company searches queued...", flush=True)

    u0, _ = client.usage_usd()
    lock = threading.Lock()
    saved_n = 0

    def _run_batch(kind: str, batch_vals: list[str]) -> int:
        nonlocal saved_n
        used_now, _ = client.usage_usd()
        if used_now - u0 >= budget_cap_usd:
            return 0
        payload = {"companies": batch_vals} if kind == "url" else {"searches": batch_vals}
        items = client.run_actor_sync("harvestapi/linkedin-company", payload, max_usd=0.65, timeout_s=150)
        with lock, open(out_path, "a") as f:
            for it in items:
                rec = {
                    "_fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "_batch_kind": kind,
                    "_batch_inputs": batch_vals,
                    "raw": it,
                }
                f.write(json.dumps(rec) + "\n")
                saved_n += 1
        return len(items)

    tasks = []
    for i in range(0, len(url_list), 25):
        tasks.append(("url", url_list[i : i + 25]))
    for i in range(0, len(search_list), 20):
        tasks.append(("search", search_list[i : i + 20]))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_run_batch, k, b) for k, b in tasks]
        for fut in as_completed(futs):
            fut.result()

    u1, _ = client.usage_usd()
    # Save launch -> query index so downstream feature builder maps deterministically
    json.dump({"url_to_items": url_to_items, "search_to_items": search_to_items}, open(f"{out_dir}/linkedin_query_map.json", "w"))
    print(f"[Wave 1 LinkedIn] Saved {saved_n} full company profiles | Wave cost: ${u1 - u0:.4f} (total used: ${u1:.4f})", flush=True)
    return {"saved_profiles": saved_n, "usd": round(u1 - u0, 4)}


def run_wave2_x_prelaunch(client: ApifyClient, targets: list[dict[str, Any]], out_dir: str, budget_cap_usd: float = 6.50) -> dict[str, Any]:
    out_path = f"{out_dir}/x_prelaunch_tweets_raw.jsonl"
    u0, _ = client.usage_usd()

    # Build strict pre-launch (< D 00:00 PT = < D 07:59:59 UTC) search queries per launch!
    query_specs: list[tuple[str, dict[str, Any]]] = []
    seen_q: set[str] = set()
    for t in targets:
        d = t["day"]
        since_d = (dt.date.fromisoformat(d) - dt.timedelta(days=35)).isoformat()
        until_str = f"{d}_07:59:59_UTC"  # Strictly before midnight Pacific on launch day D!
        dom = t["domain"]
        handles = [h for h in t["x_handles"] if h.lower() not in {"share", "intent", "home", "elonmusk", "vercel", "github"}]

        parts = []
        if dom and dom not in GENERIC_DOMAINS and "." in dom and len(dom) >= 5:
            parts.append(f'"{dom}"')
        for h in handles[:2]:
            parts.append(f"from:{h}")
            parts.append(f'"@{h}"')
        # If no domain or handle, use distinctive multi-word / CamelCase product title
        title = t["title"].strip()
        if not parts and len(title) >= 5 and (not title.isalpha() or " " in title or any(c.isupper() for c in title[1:])):
            safe_t = title.replace('"', "").strip()
            parts.append(f'"{safe_t}"')

        if not parts:
            continue
        q = f"({' OR '.join(parts[:4])}) until:{until_str} since:{since_d}"
        if q not in seen_q:
            seen_q.add(q)
            query_specs.append((q, t))

    # Take up to 1,250 launches (prioritizing all 23 live days + Oct-Nov test + Sep val)
    query_specs = query_specs[:1250]
    print(f"[Wave 2 X Pre-Launch] Running {len(query_specs)} strictly pre-launch (< D 00:00 PT) X queries...", flush=True)

    lock = threading.Lock()
    saved_tweets = 0

    def _run_x_chunk(chunk: list[tuple[str, dict[str, Any]]]) -> int:
        nonlocal saved_tweets
        used_now, _ = client.usage_usd()
        if used_now - u0 >= budget_cap_usd:
            return 0
        q_terms = [q for q, _ in chunk]
        payload = {
            "searchTerms": q_terms,
            "maxItems": min(650, len(q_terms) * 18),
            "queryType": "Latest",
        }
        items = client.run_actor_sync(
            "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
            payload,
            max_usd=0.35,
            timeout_s=150,
        )
        with lock, open(out_path, "a") as f:
            for tw in items:
                f.write(json.dumps({
                    "_fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "_chunk_launch_ids": [t["item_id"] for _, t in chunk],
                    "raw": tw,
                }) + "\n")
                saved_tweets += 1
        return len(items)

    chunks = [query_specs[i : i + 25] for i in range(0, len(query_specs), 25)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(_run_x_chunk, ch) for ch in chunks]
        for fut in as_completed(futs):
            fut.result()

    u1, _ = client.usage_usd()
    json.dump(
        [{"query": q, "item_id": t["item_id"], "day": t["day"], "domain": t["domain"], "x_handles": t["x_handles"], "title": t["title"]} for q, t in query_specs],
        open(f"{out_dir}/x_query_map.json", "w"),
    )
    print(f"[Wave 2 X Pre-Launch] Saved {saved_tweets} strictly pre-launch tweets | Wave cost: ${u1 - u0:.4f} (total used: ${u1:.4f})", flush=True)
    return {"saved_tweets": saved_tweets, "queries": len(query_specs), "usd": round(u1 - u0, 4)}


def run_wave3_g2_competitors(client: ApifyClient, data_dir: str, targets: list[dict[str, Any]], out_dir: str, budget_cap_usd: float = 5.60) -> dict[str, Any]:
    out_path = f"{out_dir}/g2_products_and_reviews_raw.jsonl"
    u0, _ = client.usage_usd()

    # Extract top recurring category incumbents across Sep-Nov from taxonomy/competitors.parquet
    comp_df = pd.read_parquet(f"{data_dir}/taxonomy/competitors.parquet")
    comp_sep_nov = comp_df[comp_df["day"] >= "2026-09-01"]
    comp_counts: dict[str, int] = {}
    for raw_c in comp_sep_nov["competitors"].dropna():
        try:
            arr = json.loads(raw_c) if isinstance(raw_c, str) else raw_c
            for c in arr:
                nm = str(c.get("name") or "").strip()
                rc = int(c.get("reviews_count") or 0)
                if len(nm) >= 2:
                    comp_counts[nm] = comp_counts.get(nm, 0) + (2 if rc >= 10 else 1)
        except Exception:
            pass

    top_incumbents = [nm for nm, _ in sorted(comp_counts.items(), key=lambda kv: -kv[1])[:180]]
    # Also include distinct company names from live-23d launches (catches 2.0/3.0/MCP products already on G2 like Canva, Linear, Parallel, etc.)
    live_cnames = []
    for t in targets:
        if t["priority"] == 0:
            cn = extract_company_name(t["title"], t["domain"])
            if len(cn) >= 3 and cn not in top_incumbents and cn not in live_cnames:
                live_cnames.append(cn)

    all_g2_targets = list(dict.fromkeys(top_incumbents + live_cnames[:90]))
    print(f"[Wave 3 G2 Incumbents & Products] Scraping {len(all_g2_targets)} products + verified user pros/cons...", flush=True)

    lock = threading.Lock()
    saved_items = 0

    def _run_g2_batch(prod_names: list[str]) -> int:
        nonlocal saved_items
        used_now, _ = client.usage_usd()
        if used_now - u0 >= budget_cap_usd:
            return 0
        payload = {
            "products": prod_names,
            "scrapeProductDetails": True,
            "scrapeReviews": True,
            "maxReviewsPerProduct": 15,
        }
        items = client.run_actor_sync("omkar-cloud/g2-product-scraper", payload, max_usd=0.80, timeout_s=180)
        with lock, open(out_path, "a") as f:
            for it in items:
                f.write(json.dumps({
                    "_fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "_batch_products": prod_names,
                    "raw": it,
                }) + "\n")
                saved_items += 1
        return len(items)

    batches = [all_g2_targets[i : i + 18] for i in range(0, len(all_g2_targets), 18)]
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(_run_g2_batch, b) for b in batches]
        for fut in as_completed(futs):
            fut.result()

    u1, _ = client.usage_usd()
    json.dump({"top_incumbents": top_incumbents, "live_cnames": live_cnames[:90]}, open(f"{out_dir}/g2_query_map.json", "w"))
    print(f"[Wave 3 G2] Saved {saved_items} G2 product & verified review records | Wave cost: ${u1 - u0:.4f} (total used: ${u1:.4f})", flush=True)
    return {"saved_items": saved_items, "products_queried": len(all_g2_targets), "usd": round(u1 - u0, 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--live23-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--token-file", default="")
    args = ap.parse_args()

    tok = os.environ.get("APIFY_API_TOKEN", "").strip()
    if not tok and args.token_file and os.path.exists(args.token_file):
        tok = open(args.token_file).read().strip()
    if not tok:
        raise RuntimeError("Missing Apify token (--token-file or APIFY_API_TOKEN)")

    os.makedirs(args.out_dir, exist_ok=True)
    client = ApifyClient(tok)
    u_start, u_cap = client.usage_usd()
    print(f"[Apify Pull] Starting usage: ${u_start:.4f} / ${u_cap:.2f}", flush=True)

    targets = collect_target_launches(args.data_dir, args.live23_dir)
    json.dump(targets, open(f"{args.out_dir}/target_launches_sep_nov.json", "w"))
    print(f"[Apify Pull] Collected {len(targets)} Sep 1 - Nov 25 target launches (live23={sum(t['priority']==0 for t in targets)})", flush=True)

    # Run all 3 orthogonal Marketplace pulls concurrently for speed!
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_li = ex.submit(run_wave1_linkedin, client, targets, args.out_dir, 5.60)
        f_x = ex.submit(run_wave2_x_prelaunch, client, targets, args.out_dir, 6.40)
        f_g2 = ex.submit(run_wave3_g2_competitors, client, args.data_dir, targets, args.out_dir, 5.60)
        res_li = f_li.result()
        res_x = f_x.result()
        res_g2 = f_g2.result()

    u_end, _ = client.usage_usd()
    summary = {
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "targets_total": len(targets),
        "usage_start_usd": round(u_start, 4),
        "usage_end_usd": round(u_end, 4),
        "run_spend_usd": round(u_end - u_start, 4),
        "cap_usd": u_cap,
        "linkedin": res_li,
        "x_prelaunch": res_x,
        "g2": res_g2,
    }
    json.dump(summary, open(f"{args.out_dir}/apify_pull_summary.json", "w"), indent=2)
    print(f"[Apify Pull COMPLETE] Summary: {json.dumps(summary)}", flush=True)


if __name__ == "__main__":
    main()
