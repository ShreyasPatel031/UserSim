"""Leak audit of the honest backtest's page/llm inputs (orchestrator 05:20Z Nov 12). Runs on the VM in experiments/ph_predict."""
import json, re, glob, os, sys, gzip, collections, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, ".")
import features as F
H = pd.read_parquet(sys.argv[1]); H["id"] = H.id.astype(str)
grp = lambda r: "winner" if r == 1 else ("top3 (2-3)" if r <= 3 else "rest")
H["grp"] = H.dailyRank.map(grp)
sites = {}
for l in open("data/sites.jsonl"):
    x = json.loads(l); sites[str(x["id"])] = x
stext = {}
for l in open("data/sites_text.jsonl"):
    x = json.loads(l); stext[str(x["id"])] = x.get("text") or ""
BROAD = re.compile(r"(?i)product\s*hunt|producthunt|product of the (day|week|month)|#\s*1\b|\b1st\b|top post|golden kitty|upvote|featured on|launched on|\bPOTD\b|\bPOTW\b")
STRONG = re.compile(r"(?i)product of the (day|week|month)|#\s*1\s*(product|of the)|\b1st\s*product|golden kitty|top post")
RESID = re.compile(r"(?i)#\s*1\b|\b1st\b|featured on|launched on|top post|golden kitty|\bof the (day|week|month)\b|\bPOTD\b")
rows = []
for r in H.itertuples():
    s = sites.get(r.id, {}); html = s.get("html") or ""; clean = F.site_text(html) if html else ""; st = stext.get(r.id, "")
    rows.append(dict(id=r.id, day=r.day, grp=r.grp, src=s.get("src", "none"), has_html=bool(html),
                     html_broad=bool(BROAD.search(html)), html_strong=bool(STRONG.search(html)),
                     ps_text_broad=bool(BROAD.search(st)), ps_text_strong=bool(STRONG.search(st)), ps_has=bool(st),
                     llm_clean700_resid=bool(RESID.search(clean[:700])), llm_clean_resid=bool(RESID.search(clean))))
D = pd.DataFrame(rows)
out = {"launches": len(D), "src_share": D.src.value_counts(normalize=True).round(4).to_dict()}
hit = {}
for c in ("html_broad", "html_strong", "ps_text_broad", "ps_text_strong", "llm_clean700_resid", "llm_clean_resid"):
    base = D[D.has_html] if c.startswith(("html", "llm")) else D[D.ps_has]
    hit[c] = {g: [round(100 * float(x.mean()), 1), int(len(x))] for g, x in base.groupby("grp")[c]}
out["hit_rate_pct_by_group"] = hit
# fetch timing: sites_r*.jsonl.gz fetch timestamps if present
ts = []
for fn in glob.glob("data/sites_r*.jsonl.gz"):
    for i, l in enumerate(gzip.open(fn, "rt")):
        try: x = json.loads(l)
        except ValueError: continue
        t = x.get("fetched_at") or x.get("ts") or x.get("time")
        if t: ts.append((x.get("url"), t))
        if i > 200000: break
out["sites_r_fetch_ts_found"] = len(ts)
out["file_mtimes"] = {f: dt.datetime.utcfromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d") for f in ["data/sites.jsonl", "data/sites_text.jsonl", "data/page_scores.jsonl", "data/page_scores_v2.jsonl"] + glob.glob("data/sites_r*.jsonl.gz")}
if ts:
    T = pd.DataFrame(ts, columns=["url", "t"]); T["t"] = pd.to_datetime(T.t, errors="coerce", utc=True); out["fetch_ts_range"] = [str(T.t.min()), str(T.t.median()), str(T.t.max())]
D.to_parquet("/tmp/leak_rows.parquet")
print(json.dumps(out, indent=1))
