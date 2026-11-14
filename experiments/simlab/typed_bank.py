"""Typed concerns / questions bank (orchestrator 00:47Z Nov 14), step 1: non-team comments from the backtest thread dumps.
Team = launch hunter (warehouse poster) or comment badge maker/hunter. Comments are scratch-only (texts never committed).
Writes <scratch>/typed/bank.parquet: id, day, comment_id, parent(bool), text (cleaned, <= 600 chars).
    python typed_bank.py <scratchpad>
"""
import glob, gzip, html, json, re, sys
import pandas as pd
SP = sys.argv[1]
L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/early/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str)
bys = {s: (i, d, str(p).lower()) for s, i, d, p in zip(L.slug, L.id, L.day, L.poster)}; rows = []; seen = set()
clean = lambda t: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
    for line in gzip.open(f):
        x = json.loads(line)
        try: p_ = json.loads(x["html"])["data"]["post"]
        except Exception: continue
        if not p_ or p_.get("slug") not in bys: continue
        i, d, hun = bys[p_["slug"]]
        def walk(n, top):
            u = ((n.get("user") or {}).get("username") or "").lower(); b = n.get("badges") or []
            cid = n.get("id")
            if cid and cid not in seen and u != hun and not any(z in ("maker", "hunter") for z in b):
                t = clean(n.get("body"))
                if len(t) > 15: rows.append((i, d, cid, top, t[:600])); seen.add(cid)
            for e in ((n.get("replies") or {}).get("edges") or []): walk(e["node"], False)
        for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"], True)
B = pd.DataFrame(rows, columns=["id", "day", "comment_id", "top", "text"]); B.to_parquet(f"{SP}/typed/bank.parquet")
n = B.groupby("id").size(); print("comments", len(B), "launches", B.id.nunique(), "launches >=5", int((n >= 5).sum()), "months", sorted(B.day.str[:7].unique()))
