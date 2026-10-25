"""Segments v2: one detailed profile per Product Hunt commenter from every source collected:
Product Hunt profile (bio, current product, stats), profile tabs (tools used, products reviewed with ratings and
complaint tags, dated activity), X profile (bio, location), LinkedIn (pilot only: headline, location, about,
experience, education). Claude on Vertex labels each person; activity stats are computed, not guessed.
Output data/segments2.jsonl. Research data: reduce to segment counts before any ongoing pipeline."""
import gzip, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import llm

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = f"{D}/segments2.jsonl"
PROMPT = """Build a profile for each Product Hunt user from everything below. Use only the evidence given; write
"unknown" when it isn't there.

Fields:
- role: founder_exec | engineer | data_ml | designer | product | marketing_growth | sales_bd | investor | creator |
  student | operations | other | unknown
- seniority: founder_c_level | senior_lead | mid | junior | student | unknown
- company_type: own_startup | startup_employee | big_tech | enterprise | agency_consulting | freelancer | academic | unknown
- company_stage: idea_pre_seed | seed_series_a | growth | public_large | not_applicable | unknown
- domain: ai_ml | developer_tools | saas_b2b | marketing | design | fintech | ecommerce | health | education |
  media_content | crypto_web3 | hardware | gaming | consumer_apps | other | unknown
- tech_level: builds_software | technical_non_dev | non_technical | unknown
- country: country name if stated anywhere (LinkedIn, X location, bio), else "unknown"
- interests: up to 5 product categories they care about, from the tools they use and products they review
- buyer_type: what they'd adopt a new product as: individual_prosumer | team_lead_buyer | developer_adopter |
  enterprise_buyer | casual_consumer | unknown
- summary: one sentence describing this person as a user

People:
{items}

Reply with JSON only: {{"<username>": {{"role": "...", "seniority": "...", "company_type": "...", "company_stage": "...",
"domain": "...", "tech_level": "...", "country": "...", "interests": ["..."], "buyer_type": "...", "summary": "..."}}, ...}}"""


def jl(path):
    op = gzip.open if path.endswith(".gz") else open
    out = []
    if os.path.exists(path):
        with op(path, "rt") as f:
            for l in f:
                try:
                    out.append(json.loads(l))
                except ValueError:
                    pass
    return out


def load():
    prof = {p["username"]: p for p in jl(f"{D}/ph_profiles2.jsonl.gz")}
    tabs = {t["username"]: t for t in jl(f"{D}/profile_tabs.jsonl.gz")}
    X = {x["handle"].lower(): (x.get("profile") or {}) for x in jl(f"{D}/commenter_x.jsonl.gz")}
    LI = {r["ph"]: r.get("sections") or {} for r in jl(f"{D}/linkedin_pilot.jsonl.gz")}
    return prof, tabs, X, LI


def evidence(u, prof, tabs, X, LI):
    p, t = prof.get(u, {}), tabs.get(u, {}) or {}
    x = X.get((p.get("twitter") or "").lower(), {})
    li = {k: (v or "").split("More profiles for you")[0] for k, v in LI.get(u, {}).items()}  # drop LinkedIn's sidebar
    revs = [f"{r.get('product_name')} {r.get('rating')}/5" + (f" (cons: {', '.join(r['cons'])})" if r.get("cons") else "")
            for r in (t.get("reviews") or [])[:12]]
    parts = [f"[{u}]",
             f"PH headline: {p.get('headline') or ''}", f"PH bio: {(p.get('about') or '')[:300]}",
             f"current product: {p.get('current_product') or ''}; products made: {p.get('products_made')}; hunted: {p.get('hunted')}",
             f"PH stats: followers {p.get('followers')}, total upvotes {p.get('upvotes_total')}, joined {(p.get('joined') or '')[:4]}",
             f"tools used: {', '.join(s.get('name') or '' for s in (t.get('stacks') or [])[:15])}",
             f"reviews written: {'; '.join(revs)}"]
    if x:
        parts.append(f"X bio: {(x.get('description') or '')[:160]}; X location: {x.get('location') or ''}; X followers {x.get('followers')}")
    if li:
        parts.append(f"LinkedIn profile: {(li.get('main') or '')[:600]}")
        parts.append(f"LinkedIn experience: {(li.get('experience') or '')[:700]}")
        parts.append(f"LinkedIn education: {(li.get('education') or '')[:300]}")
    return "\n  ".join(parts)


def batch(rows):
    txt = llm.call(PROMPT.format(items="\n\n".join(rows)), max_tokens=170 * len(rows) + 400)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


def stats(p, t):
    acts = (t or {}).get("activity") or []
    return {"followers": p.get("followers"), "upvotes_total": p.get("upvotes_total"), "joined": (p.get("joined") or "")[:10],
            "products_made": p.get("products_made"), "hunted": p.get("hunted"), "reviews": p.get("reviews_count"),
            "visit_streak_days": p.get("visit_streak_days"), "verified": p.get("verified"),
            "n_tools": len((t or {}).get("stacks") or []), "tools": [s.get("slug") for s in (t or {}).get("stacks") or []],
            "reviewed": [r.get("product_slug") for r in (t or {}).get("reviews") or []],
            "last_active": max((a["occurred"][:10] for a in acts), default=None),
            "comments_recent": sum(a.get("subject_type") == "Comment" for a in acts)}


if __name__ == "__main__":
    only = sys.argv[2:]  # optional usernames (e.g. a single person to check)
    prof, tabs, X, LI = load()
    users = only or sorted(prof)
    done = set() if only else ({json.loads(l)["username"] for l in open(OUT)} if os.path.exists(OUT) else set())
    users = [u for u in users if u not in done]
    ev = {u: evidence(u, prof, tabs, X, LI) for u in users}
    chunks = [users[i:i + 20] for i in range(0, len(users), 20)]
    with open(OUT if not only else f"{D}/segments2_check.jsonl", "a" if not only else "w") as f, \
            ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 5) as ex:
        for ch, res in zip(chunks, ex.map(lambda c: batch([ev[u] for u in c]), chunks)):
            for u in ch:
                f.write(json.dumps({"username": u, "labels": res.get(u), "stats": stats(prof.get(u, {}), tabs.get(u)),
                                    "sources": {"linkedin": u in LI, "x": bool(X.get((prof.get(u, {}).get("twitter") or "").lower())),
                                                "tabs": u in tabs}}) + "\n")
            f.flush()
    print("done", len(users))
