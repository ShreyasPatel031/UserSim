"""Which mixture of review data sources predicts held-out people best?

Sources (each target product's own reviews are always excluded):
  C  FreshCrawl Capterra snapshot (same-category products)        G  FreshCrawl G2 snapshot (same-category products)
  L  live scrape (G2 + Capterra + TrustRadius + Gartner) of the 3 competitors the model names for the target
Mixtures: C, G, L, CG, CL, GL, CGL (+ agent alone, no data).
Eval sets (held-out people):
  capterra  router_eval TEST products, 12 people each        g2  g2_merge test products, 10 people each
  live      10 products in neither snapshot, scraped live now, 10 people each (G2/Capterra/TrustRadius reviewers)
One package builder for every mixture; per source the people-like-them estimate is computed, and the mixture's
estimate is the plain mean over its sources (each source one vote). Strategy per output (averages / blend /
agent_full) is chosen on half A of each eval set's products and scored on half B, and vice versa.

    python experiments/staged_context/mixture.py scrape     # live eval products + every target's competitors
    python experiments/staged_context/mixture.py run        # packages, predictions, judging, report
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus as C  # noqa: E402
import experiment as E  # noqa: E402
import g2_merge as G  # noqa: E402
import live as L  # noqa: E402
import matched as MT  # noqa: E402
import per_person as PP  # noqa: E402
import predictability as PR  # noqa: E402
import router_eval as RE  # noqa: E402
import ux_mcp as U  # noqa: E402

MOUT = E.OUT / "mixture"
FLASH = "gemini-2.5-flash"
N_COMP = 3
LIVE_PER_PRODUCT = 10
# Products in neither snapshot, one or two per Capterra category.
LIVE_TARGETS = {
    "Copper": "https://www.copper.com/", "Gorgias": "https://www.gorgias.com/", "Teamwork.com": "https://www.teamwork.com/",
    "GetResponse": "https://www.getresponse.com/", "Personio": "https://www.personio.com/", "Zoho Books": "https://www.zoho.com/books/",
    "Sisense": "https://www.sisense.com/", "Mattermost": "https://mattermost.com/", "Bitwarden": "https://bitwarden.com/",
    "Ecwid": "https://www.ecwid.com/",
}
G2_URLS = {  # g2_merge test products, for the competitor-naming call
    "Freshdesk": "https://www.freshworks.com/freshdesk/", "1Password": "https://1password.com/",
}
MIXES = ["C", "G", "L", "CG", "CL", "GL", "CGL"]
SRC = {"C": "capterra", "G": "g2", "L": "live"}


# ----------------------------------------------------------------------------- targets + live data

def g2_test() -> tuple[list[dict], list[str]]:
    gp, _, g_test = G.g2_people()
    return [r for r in gp if r["product"] in g_test], g_test


def targets() -> dict[str, str]:
    """name -> URL for every eval product (the URL feeds category classification and competitor naming)."""
    _, g_test = g2_test()
    out = {p: RE.URLS[p] for p in RE.TEST}
    for p in g_test:
        out[p] = RE.URLS.get(p) or G2_URLS.get(p) or E.read_json(MOUT / "g2_urls.json")[p]
    return out | LIVE_TARGETS


def competitors_of(name: str, url: str) -> list[str]:
    page = ""
    try:
        page = U.classify(url)["page_text"]
    except Exception:  # noqa: BLE001  (page fetch blocked: name competitors from the product name alone)
        pass
    return L.named_competitors(name, url, page, n=5)


def scrape_all() -> None:
    tg = targets()
    pool = ThreadPoolExecutor(4)
    comps = dict(zip(tg, pool.map(lambda kv: competitors_of(*kv), tg.items())))
    E.write_json(MOUT / "competitors.json", comps)
    names = list(LIVE_TARGETS) + sorted({c for v in comps.values() for c in v[:N_COMP]})
    print(f"{len(names)} scrapes; competitors: {json.dumps(comps, indent=1)}", flush=True)

    def one(n):
        try:
            items = L.scrape(n)
            return n, len(items), None
        except Exception as exc:  # noqa: BLE001
            return n, 0, str(exc)[:200]
    res = list(pool.map(one, names))
    for n, k, err in res:
        print(f"{n}: {k} reviews" + (f"  ERROR {err}" if err else ""), flush=True)
    E.write_json(MOUT / "scrapes.json", {n: {"reviews": k, "error": err} for n, k, err in res})


def live_pool(target: str, comps: dict) -> pd.DataFrame:
    """Live reviews of the target's first N_COMP named competitors that returned reviews (backfilled from the
    4th/5th name only when an earlier one has none). Reviews without pros/cons/text are dropped."""
    frames = []
    for c in comps[target]:
        if len(frames) == N_COMP:
            break
        if not (L.LIVE / f"{L.slug(c)}.json").is_file():
            continue
        f = L.frame(c)
        if len(f):
            frames.append(f)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ----------------------------------------------------------------------------- package for a mixture

def _est_one(df: pd.DataFrame, person: dict, attrs: list[str]) -> tuple[dict, list[str]]:
    est, lines = {}, []
    for r, (lo, hi) in U.RATINGS.items():
        col = df[r] if r in df else pd.Series(dtype=float)
        col = col.dropna()
        if not len(col):
            continue
        mu, dev, parts = float(col.mean()), 0.0, []
        for a in attrs:
            v = person.get(a)
            if v is None:
                continue
            g = df.loc[(df[a] == v) & df[r].notna(), r]
            if len(g):
                dev += (g.sum() + U.SHRINK * mu) / (len(g) + U.SHRINK) - mu
                parts.append(f"{a} '{v}': {g.mean():.2f} (n={len(g)})")
        est[r] = float(np.clip(mu + dev, lo, hi))
        lines.append(f"- {r}: all reviewers {mu:.2f}; " + "; ".join(parts) + f"; combined estimate {est[r]:.2f}")
    return est, lines


def package(person: dict, category: str | None, mix: str, exclude: str, mask: str | None, live: pd.DataFrame) -> dict:
    """Same sections as corpus.sections, for any mixture of C / G / L."""
    snap = {SRC[s] for s in mix if s in "CG"}
    per, lines = {}, []
    if snap:
        for src in sorted(snap):
            e, ln = C.estimates(person, {src}, exclude)
            for r, v in e.items():
                per.setdefault(r, []).append(v)
            lines += ln
    if "L" in mix and len(live):
        lp = person | {"industry": L.industry(person.get("industry"))}
        e, ln = _est_one(live, lp, ["role_family", "size3", "industry"])
        for r, v in e.items():
            per.setdefault(r, []).append(v)
        lines += [ln_.replace("- ", "- [live competitors] ", 1) for ln_ in ln]
    est = {r: float(np.mean(v)) for r, v in per.items()}
    parts = []
    if snap:
        df = C.corpus()
        df = df[df.source.isin(snap) & (df["product"] != exclude)]
        parts.append(df[df.category == category] if category else df)
    if "L" in mix and len(live):
        parts.append(live.assign(industry_raw=live.industry))
    comp = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["product", "pros", "cons"])
    cons = comp.cons.fillna("").astype(str).str.lower()
    cons = cons[cons != ""]
    topics = "\n".join(f"- {k.replace('complaint_', '')}: {cons.str.contains(p, regex=True).mean():.1%} mention it"
                       for k, p in PR.TOPICS.items()) if len(cons) else "(no cons text)"
    rat = "; ".join(f"{r} {comp[r].mean():.2f}" for r in U.RATINGS if r in comp and comp[r].notna().any())
    pool = comp[comp.pros.notna() & comp.cons.notna()]
    ind = L.industry(person.get("industry"))
    score = (3 * (pool.role_family == person.get("role_family"))
             + 2 * ((pool.size_fine == person.get("size_fine")) | (pool.size3 == person.get("size3")))
             + (pool.time_used == person.get("time_used")) + (pool.industry.map(L.industry) == ind))
    cut = score.nlargest(8).min() if len(score) else 0
    cand = pool[score >= cut].assign(_s=score[score >= cut])
    key = json.dumps(person, sort_keys=True, default=str)
    cand = cand.assign(_t=cand.rid.map(lambda i: E.sha(f"42|mix|{key}|{i}")))
    revs = []
    import re
    for r in cand.sort_values(["_s", "_t"], ascending=[False, True]).head(8).to_dict("records"):
        site = r.get("site") if isinstance(r.get("site"), str) else r["source"]
        fields = [("Source", site), ("Role family", r["role_family"]), ("Company size", r.get("size_fine") or r.get("size3")),
                  ("Time used", r.get("time_used")), ("Overall rating", r.get("overall_rating")), ("Liked", r["pros"]),
                  ("Disliked", r["cons"])]
        text = "\n".join(f"{k}: {E.clean(v)}" for k, v in fields if E.clean(v) and E.clean(v) not in ("nan", "None"))
        if mask:
            text = re.sub(mask, "[target product]", text, flags=re.I)
        revs.append(f"[{r['product']}]\n{text[:1000]}")
    label = "+".join(sorted(SRC[s] for s in mix))
    names = sorted(comp["product"].unique())
    return {"estimates": est, "sections": {
        "averages": f"## People like this person (other software products; {label})\n" + "\n".join(lines),
        "competitors": f"## Competitors ({label}): {', '.join(names[:25])} ({len(comp)} reviews)\nAverage ratings: {rat}\n"
                       f"Complaint topics in their cons:\n{topics}",
        "similar_reviews": "## Reviews of competitor products by the most similar people\n" + "\n\n".join(revs)}}


# ----------------------------------------------------------------------------- people

def live_people(comps: dict) -> list[dict]:
    out = []
    for p in LIVE_TARGETS:
        f = L.frame(p)
        f = f[f.overall_rating.notna() & (f.role_family != "unknown")
              & (f.pros.notna() & f.cons.notna() | f.review_text.notna())]
        f = f.assign(_h=f.rid.map(lambda i: E.sha(f"42|live|{p}|{i}"))).sort_values("_h").head(LIVE_PER_PRODUCT)
        out += [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()} for r in f.to_dict("records")]
    return out
