"""Raw-field sweep, extraction (read-only, VM). Every field in the raw PH day records (data/days/<d>.json for 2026, ~/w/ph_history/2025/<d>.json),
flattened and turned into numbers mechanically, plus a few derived timing/slug fields; written for the stored (after-close) record and,
for nights with a 00:05 snapshot (data/today/<d>.json, Oct 25 - Nov 13), for the 00:05 record. Outcome fields (votes, comments, ranks)
are extracted too, only so the knowability check marks them leaky.
Rules: scalar number -> value; bool -> 0/1; string -> length (+ word count for long text, + "nonempty"); list -> length;
list of dicts -> per sub-key: count non-empty, and for numeric sub-keys mean and max; dict -> recursed.
usage: /opt/exp/bin/python3 -I rawfield_extract.py <out_dir>"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
D26 = os.path.expanduser("~/w/experiments/ph_predict/data"); D25 = os.path.expanduser("~/w/ph_history/2025")


def flat(r, p=""):
    o = {}
    for k, v in r.items():
        n = p + k
        if isinstance(v, dict): o.update(flat(v, n + "."))
        elif isinstance(v, bool): o[n] = float(v)
        elif isinstance(v, (int, float)) and v is not None: o[n] = float(v)
        elif isinstance(v, str):
            o[n + ":len"] = float(len(v)); o[n + ":nonempty"] = float(len(v.strip()) > 0)
            if len(v) > 40: o[n + ":words"] = float(len(v.split()))
        elif isinstance(v, list):
            o[n + ":n"] = float(len(v))
            if v and all(isinstance(x, dict) for x in v):
                keys = set().union(*[x.keys() for x in v])
                for sk in keys:
                    vals = [x.get(sk) for x in v]
                    o[f"{n}[].{sk}:nonempty"] = float(sum(1 for x in vals if x not in (None, "", [], {})))
                    num = [float(x) for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool)]
                    if num: o[f"{n}[].{sk}:mean"] = float(np.mean(num)); o[f"{n}[].{sk}:max"] = float(np.max(num))
                    if all(isinstance(x, dict) for x in vals if x is not None):
                        for x in vals:
                            if isinstance(x, dict):
                                for k2, v2 in x.items():
                                    if isinstance(v2, str):
                                        o[f"{n}[].{sk}.{k2}:nonempty"] = o.get(f"{n}[].{sk}.{k2}:nonempty", 0.0) + float(len(v2.strip()) > 0)
        elif v is None: o[n + ":null"] = 1.0
    return o


def derived(r):
    o = {}
    ts = lambda s: pd.Timestamp(s).tz_convert("America/Los_Angeles") if s else None
    c, f = ts(r.get("createdAt")), ts(r.get("featuredAt"))
    if c is not None: o["drv.created_min_pt"] = c.hour * 60 + c.minute + c.second / 60
    if c is not None and f is not None: o["drv.featured_minus_created_h"] = (f - c).total_seconds() / 3600
    s = r.get("slug") or ""; m = re.search(r"-(\d+)$", s); o["drv.slug_suffix_n"] = float(m.group(1)) if m else 0.0
    o["drv.name_has_digit"] = float(bool(re.search(r"\d", r.get("name") or "")))
    u = r.get("user") or {}
    if u.get("createdAt") and c is not None: o["drv.hunter_age_d_at_create"] = (c - ts(u["createdAt"])).total_seconds() / 86400
    o["drv.hunter_has_twitter"] = float(bool((u.get("twitterUsername") or "").strip()))
    o["drv.hunter_headline_len"] = float(len(u.get("headline") or ""))
    return o


def rows(path, day, kind):
    out = []
    for r in json.load(open(path)):
        out.append({"id": str(r.get("id")), "day": day, "kind": kind, **flat(r), **derived(r)})
    return out


R = []
for f in sorted(glob.glob(f"{D25}/*.json")):
    R += rows(f, os.path.basename(f)[:10], "stored")
for f in sorted(glob.glob(f"{D26}/days/*.json")):
    R += rows(f, os.path.basename(f)[:10], "stored")
for f in sorted(glob.glob(f"{D26}/today/*.json")):
    d = os.path.basename(f)[:10]
    if "2026-10-25" <= d <= "2026-11-13": R += rows(f, d, "t0005")
X = pd.DataFrame(R); X.columns = [str(c) for c in X.columns]
X.to_parquet(f"{OUT}/rawfields.parquet"); print(json.dumps({"rows": len(X), "fields": len(X.columns) - 3, "by_kind": X.kind.value_counts().to_dict()}))
