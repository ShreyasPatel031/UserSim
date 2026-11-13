"""Comment inputs at a cut for every 2026 launch (orchestrator 20:16Z Nov 13; counts only, no usernames written).
Columns: id, th_n_pre (distinct non-hunter commenters <= 00:05), nu, nc, mrep_h (log1p, <= T). usage: python cm_feats.py <minutes> <out.parquet>"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from pipeline import warehouse as W
mins, out = int(sys.argv[1]), sys.argv[2]
L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, poster FROM launches WHERE day >= '2026-01-01'", do_sync=False)
L["poster"] = L.poster.fillna("").str.lower()
K, _ = CF.load_comments(); K = K.merge(L, on="slug")
K["d0"] = [pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
K["is_h"] = K.user == K.poster
pre, C = K[K.ts <= K.d0 + pd.Timedelta(minutes=5)], K[K.ts <= K.d0 + pd.Timedelta(minutes=mins)]
has = set(K.slug)
X = L[L.slug.isin(has) | (L.day <= "2026-10-24")].copy()   # launches with a dump; zero comments counts as 0
X["th_n_pre"] = X.id.map(pre[~pre.is_h].groupby("id").user.nunique()).fillna(0)
X["nu"] = np.log1p(X.id.map(C[~C.is_h].groupby("id").user.nunique()).fillna(0))
X["nc"] = np.log1p(X.id.map(C.groupby("id").size()).fillna(0))
X["mrep_h"] = np.log1p(X.id.map(C[C.is_h & (C.depth > 0)].groupby("id").size()).fillna(0))
X[["id", "th_n_pre", "nu", "nc", "mrep_h"]].to_parquet(out)
print(len(X), X.day.min(), X.day.max(), (X.nc > 0).mean().round(3))
