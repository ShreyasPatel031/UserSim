"""PRODUCT-USE-1 control: the plain homepage prompt (e2e_vs_reviews/part1.py baseline, extended with comparisons and a would-use number),
on the same frozen line-up and frozen at the same time. Homepage via safe_fetch (no producthunt.com). Gemini 2.5 Flash, temperature 0.
  python control_homepage.py D [--rehearsal]   ->  results/calibration/D/product_use/control_homepage.json
"""
import asyncio, json, os, re, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "cohort_calibration"))
import sim_model  # noqa: E402
MAINWT = os.environ.get("PU_MAINWT") or os.path.join(os.environ.get("PU_WORK", "/tmp/pu"), "mainwt"); sys.path.insert(0, MAINWT)
from mvp.ph_site import safe_fetch  # noqa: E402
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; D = [a for a in sys.argv[1:] if not a.startswith("--")][0]; REH = "--rehearsal" in sys.argv
PUB = f"{B}/{'_rehearsal/' if REH else ''}results/calibration/{D}/product_use"
LU = json.loads(subprocess.run(["gsutil", "cat", f"{PUB}/lineup.json"], capture_output=True, check=True).stdout)
P = """Product: {n} ({u}). Text of its homepage:
{t}

Predict, for people who try this product for the first time: what they most often complain about, what they praise, and how they compare it
with alternatives; and how likely a typical Product Hunt member who tries it is to keep using it (0-1).
Return JSON only: {{"complaints": ["<under 16 words>", ...up to 8, most important first], "praise": ["<under 16 words>", ...up to 5],
"comparisons": ["<under 16 words>", ...up to 3], "would_use": 0.0-1.0}}"""
async def home(u):
    try:
        r = await safe_fetch.fetch(u); x = safe_fetch.extract(r.get("html") or "") if r.get("html") else {}
        return (" ".join([x.get("title", ""), x.get("description", ""), x.get("text", "")]) or r.get("text") or "")[:5000], r.get("status")
    except Exception as e: return f"(homepage not fetched: {e!r})"[:200], None
out = []
for l in LU["launches"]:
    t, st = asyncio.run(home(l["url"])) if l.get("url") else ("(no url)", None)
    r = sim_model.call(P.format(n=l["name"], u=l.get("url"), t=t), max_tokens=900, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
    try: j = json.loads(m.group(0))
    except Exception: j = {}
    out.append({"launch_id": l["id"], "structural_rank": l["structural_rank"], "fetch_status": st, **{k: j.get(k) for k in ("complaints", "praise", "comparisons", "would_use")}})
o = {"day": D, "rehearsal": REH, "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "lineup_frozen_at": LU["frozen_at"], "model": "gemini-2.5-flash", "launches": out}
p = f"/tmp/pu_ctrl_{D}.json"; json.dump(o, open(p, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", p, f"{PUB}/control_homepage.json"], check=True)
print(json.dumps({"day": D, "n": len(out), "fetched": sum(1 for x in out if str(x["fetch_status"]) == "200")}))
