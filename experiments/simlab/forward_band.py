"""Forward test of page reads at launch (orchestrator 08:56Z Nov 12, task A). Run once per day shortly after launch.
For each of today's launches with a product URL known without loading a Product Hunt page:
  URL source (in order): (1) resolved product URL if a field carries it (none yet); (2) the first non-PH link in a top-level comment
  created <= now in live/comments_ts.jsonl (API-sourced; most are the maker's intro). Never a producthunt.com request.
  Fetch + read ONCE through the site's own code (try_sim.step_page: safe_fetch rules, READ_PROMPT on gemini-2.5-flash-lite), capturing
  the raw HTML of that single fetch; then the site's step_reactions and step_launch (band v1 as served).
  Frozen the same hour from the stored inputs: band v2 run 1 (sklearn retrieval), run 2 (servable retrieval), facts-only stack,
  using models trained on launches <= Aug 31 (forward/frozen_run{1,2}.pkl, as tested in band_facts.py).
Writes gs://.../usersim_sim/tmp/e5/band/forward/<day>/<launch id>.json.gz (raw html, read, reactions, band v1, v2 scores, fetched_at,
url source) and <day>/_summary.json (counts, cost estimate). Scoring vs final ranks: forward_score.py once ranks land.
    python forward_band.py <day> <scratchpad> <ph-website worktree>
"""
import asyncio, gzip, json, os, pickle, re, subprocess, sys, time
import numpy as np, pandas as pd
DAY, SP, WT = sys.argv[1:4]; BK = "gs://usersim-bakeoff-347838016394/usersim_sim"; OUTG = os.environ.get("FWD_OUT") or f"{BK}/tmp/e5/band/forward/{DAY}"
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(SP, "gcp_key.json"))
os.environ["TRY_SIGNING_KEY"] = "local-dummy-key-for-offline-eval-0123456789"; os.environ["TRY_LOCAL_LIMITS"] = "1"; os.environ.setdefault("TRY_GLOBAL_DAY", "5000")
sys.path[:0] = [WT, os.path.join(WT, "src"), os.path.dirname(os.path.abspath(__file__))]
from mvp.ph_site import try_sim, safe_fetch  # noqa: E402
import frozen_band as FB  # noqa: E402
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
T0 = json.loads(cat(f"{BK}/raw/daily/{DAY}/today_0005.json") or "[]")
ids = {str(x["id"]): x for x in T0}
URL = re.compile(r"https?://[^\s<>\"')\]]+")
BAD = re.compile(r"producthunt\.com|ph-files|twitter\.com|//x\.com|linkedin\.com|youtube\.com|youtu\.be|discord|instagram\.com|tiktok\.com|facebook\.com|reddit\.com|loom\.com|imgur|calendly|cal\.com")
now = pd.Timestamp.now(tz="UTC"); urls = {}
for l in cat(f"{BK}/raw/ph_at_launch/{DAY}/live/comments_ts.jsonl").splitlines():
    c = json.loads(l); i = str(c.get("launch_id"))
    if i not in ids or c.get("parent_id") or not c.get("body"): continue
    ts = pd.Timestamp(c["created_at"])
    if ts > now: continue
    u = next((u.rstrip(".,;:!") for u in URL.findall(c["body"]) if not BAD.search(u)), None)
    if u and (i not in urls or ts < urls[i][1]): urls[i] = (u, ts)
src = {i: "comment_link" for i in urls}
# (0) the Data Feeder's resolved URLs, when the file exists (orchestrator 08:59Z: preferred source)
for l in cat(f"{BK}/raw/ph_at_launch/{DAY}/website_urls.jsonl").splitlines():
    try: x = json.loads(l)
    except Exception: continue
    i, u = str(x.get("launch_id") or x.get("id")), x.get("url") or x.get("website_url")
    if i in ids and u and not BAD.search(u): urls[i] = (u, now); src[i] = "website_urls"
# (0b) the Data Feeder's resolved redirect targets in raw/sites_ph.jsonl (status 200, non-PH url; fetched by the Feeder, not here)
for l in cat(f"{BK}/raw/sites_ph.jsonl").splitlines():
    try: x = json.loads(l)
    except Exception: continue
    i, u = str(x.get("id")), x.get("url")
    if i in ids and x.get("status") == 200 and u and not BAD.search(u) and src.get(i) != "website_urls": urls[i] = (u, now); src[i] = "sites_ph_resolved"
# https only in this environment: upgrade plain-http links
urls = {i: (("https://" + u[len("http://"):]) if u.startswith("http://") else u, t) for i, (u, t) in urls.items()}
# (2) a bare domain in the launch's own description / tagline (e.g. "try it at foo.ai")
DOM = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|ai|io|app|co|dev|so|xyz|net|org|tech|me|sh|tools|site|page|gg|cc|ly|to))\b(/[^\s]*)?", re.I)
for i, x in ids.items():
    if i in urls: continue
    m = next((m for m in DOM.finditer(f"{x.get('tagline') or ''} {x.get('description') or ''}") if not BAD.search(m.group(0))), None)
    if m: urls[i] = ("https://" + m.group(0).rstrip(".,;:!)"), now); src[i] = "description_domain"
print(json.dumps({"day": DAY, "launches_0005": len(ids), "with_url": len(urls), "by_source": {k: list(src.values()).count(k) for k in set(src.values())}}), flush=True)
CAP = {}
_orig = safe_fetch.fetch
async def _cap(url):
    r = await _orig(url); CAP.setdefault("main", r); return r
safe_fetch.fetch = _cap
F1, F2 = pickle.load(open(os.path.join(SP, "forward/frozen_run1.pkl"), "rb")), pickle.load(open(os.path.join(SP, "forward/frozen_run2.pkl"), "rb"))
done = set(p.rsplit("/", 1)[-1].split(".")[0] for p in subprocess.run(["gsutil", "ls", f"{OUTG}/"], capture_output=True, text=True).stdout.split())
summary = {"day": DAY, "launches": len(ids), "with_url": len(urls), "url_source_by_id": src, "all_ids": list(ids), "ok": 0, "fail": {}, "chars_in": 0, "chars_out": 0}

async def one(i, u):
    CAP.clear(); t0 = time.time(); rec = {"id": i, "url": u[0], "url_source": src[i], "flag": ("fetched 1-2 h after launch, self-selected" if src[i] not in ("website_urls", "sites_ph_resolved") else "") + (" LATE: fetched days after launch" if os.environ.get("FWD_LATE") else ""), "url_comment_created": str(u[1]), "fetched_at": str(pd.Timestamp.now(tz="UTC")),
                                         "hours_after_launch": round((pd.Timestamp.now(tz="UTC") - pd.Timestamp(DAY + " 00:01", tz="America/Los_Angeles")).total_seconds() / 3600, 2)}
    try:
        pg = await try_sim.step_page(u[0], "10.0.0.%d" % (hash(i) % 250)); a = pg["analysis"]; tok = pg["token"]
        rec["read"] = a; rec["html"] = (CAP.get("main") or {}).get("html", ""); rec["final_url"] = (CAP.get("main") or {}).get("final_url")
        try: rec["reactions"] = await try_sim.step_reactions(tok)
        except Exception as e: rec["reactions_error"] = str(e)[:200]
        ln = try_sim.step_launch(tok); rec["band_v1"] = {k: ln[k] for k in ("percentile", "decile", "rank_band", "votes_band", "share_top3", "share_top10")}
        rec["band_v2"] = {"run1": FB.score(F1, a, rec["html"], DAY), "run2": FB.score(F2, a, rec["html"], DAY)}
        summary["ok"] += 1; summary["chars_in"] += 9000 + 2500 + 4000; summary["chars_out"] += 3000
    except Exception as e:
        rec["fail"] = str(e)[:200]; k = type(e).__name__; summary["fail"][k] = summary["fail"].get(k, 0) + 1
    rec["sec"] = round(time.time() - t0, 1); p = os.path.join(SP, f"forward/{DAY}_{i}.json.gz")
    with gzip.open(p, "wt") as f: json.dump(rec, f, default=str)
    subprocess.run(["gsutil", "-q", "cp", p, f"{OUTG}/{i}.json.gz"])

async def main():
    for i, u in list(urls.items())[:int(os.environ.get("FWD_LIMIT", 40))]:
        if i in done: continue
        await one(i, u)
asyncio.run(main())
# gemini-2.5-flash-lite read + gemini-2.5-flash reactions: rough list-price estimate from characters / 4
summary["cost_usd_est"] = round(summary["ok"] * (0.004 + 0.003), 3)
json.dump(summary, open(os.path.join(SP, f"forward/{DAY}_summary.json"), "w")); subprocess.run(["gsutil", "-q", "cp", os.path.join(SP, f"forward/{DAY}_summary.json"), f"{OUTG}/_summary.json"])
print(json.dumps(summary))
