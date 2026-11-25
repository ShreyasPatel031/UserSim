"""PRODUCT-USE-0 line-up (orchestrator 02:01Z Nov 25; PREREG addendum 12): back-test the product-use harness on products with
post-cutoff PH review truth (simharness/taxonomy/review_truth.parquet, frozen sha256 0d81ad09...).
Products: truth products with >= 10 reviews dated 2025+ and a usable homepage that the homepage-only baseline scored, most-reviewed
first. Each product is one "launch" with no competitors; 3 users each, drawn per product (md5 seed) from the pre-day profiles of the
Nov 20-24 person-built panel pools; task = the product's own PH category's frozen core task (category_tasks.json, v2 prompt).
Writes tmp/e5/private/product_use/pu0/lineup_full.json in the runner's format (run: runner.py pu0 --max-launches K).
"""
import hashlib, io, json, os, re, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "cohort_calibration"))
import sim_model  # noqa: E402
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; PRIV = f"{B}/tmp/e5/private/product_use"; TX = f"{B}/simharness/taxonomy"
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
pq = lambda p: pd.read_parquet(io.BytesIO(cat(p)))
T = pq(f"{TX}/review_truth.parquet"); H = pq(f"{TX}/review_truth_wip/homepages.parquet"); S = pq(f"{TX}/review_truth_wip/baseline_scores.parquet")
H = H[H["drop"].isna()].drop_duplicates("product")
P = T[(T.n_reviews_2025 >= 10) & T["product"].isin(H["product"]) & T["product"].isin(S["product"])].sort_values(["n_reviews_2025", "product"], ascending=[False, True])
url = dict(zip(H["product"], [f or u for f, u in zip(H.final_url, H.url)]))
host = lambda u: re.sub(r"^www\.", "", re.sub(r"^https?://", "", str(u)).split("/")[0].lower())
P = P.assign(_k=P["product"].str.lower(), _h=P["product"].map(lambda x: host(url[x]))).drop_duplicates("_k").drop_duplicates("_h")   # same product twice (slug case / same site)
# category core tasks (shared with PRODUCT-USE-1; v2 prompt; written once per category, then frozen)
TK = json.loads(cat(f"{PRIV}/category_tasks.json") or b"{}")
CATS = {json.loads(l)["name"]: json.loads(l)["description"] for l in cat(f"{TX}/ph_categories_pasted.jsonl").decode().splitlines() if l.strip()}
def task(c):
    if c not in TK:
        p = (f"Product category: {c}\nCategory description: {CATS.get(c, '')}\n\nWrite ONE first-use task that a new user could do on EVERY product "
             "in this category (each product does some version of it), in the first 10 minutes, without paying, and that reaches the category's "
             "first moment of value (the point where the user gets the result this kind of product exists to give). Keep it at the level of the "
             "category's shared job, not one product's feature. Do not name any product. Also state, in one sentence, what counts as reaching "
             'that moment of value. Reply as JSON only: {"task": "...", "value_moment": "..."}')
        r = sim_model.call(p, max_tokens=400, temperature=0.0); m = re.search(r"\{.*\}", r or "", re.S)
        TK[c] = dict(json.loads(m.group(0)) if m else {"task": None}, written_at=pd.Timestamp.now(tz="UTC").isoformat(), model="gemini-2.5-flash", prompt_version=2)
    return TK[c]
# user pool: pre-day profiles from recent person-built panels (quoted comments removed; person ids hashed, never published)
def profile(prompt):
    h = prompt.split("THIS MEMBER'S HISTORY", 1)[-1].split("TODAY'S LAUNCH", 1)[0].split("Recent comments they wrote:", 1)[0]
    return re.sub(r"@\w+", "", h).strip(" :\n")
pool = {}
for d in pd.date_range("2026-11-20", "2026-11-24").strftime("%Y-%m-%d"):
    b = cat(f"{PRIV.rsplit('/product_use', 1)[0]}/person_panel/{d}.parquet")
    if not b: continue
    X = pd.read_parquet(io.BytesIO(b)); X = X[X["drop"].isna() | (X["drop"].astype(str).str.strip() == "")]
    for pid, pr in zip(X.person_id, X.prompt): pool.setdefault(str(pid), profile(pr))
keys = sorted(pool); print("user pool", len(keys), "products", len(P))
L, USERS = [], {}
for k, r in enumerate(P.itertuples()):
    c = list(r.categories)[0] if len(r.categories) else "Productivity"; t = task(c)
    L.append({"id": r.product, "structural_rank": k + 1, "name": r.product, "tagline": "", "description": "", "topics": [], "url": url[r.product],
              "url_source": "review_truth_wip/homepages", "category": c, "category_source": r.category_source, "core_task": t.get("task"),
              "value_moment": t.get("value_moment"), "competitors": [], "n_reviews_2025": int(r.n_reviews_2025)})
    seed = int(hashlib.md5(r.product.encode()).hexdigest(), 16); pick = []
    while len(pick) < 3: j = keys[seed % len(keys)]; seed //= 7; pick += [j] if j not in pick else []
    USERS[r.product] = [{"user_key": hashlib.sha256((j + "|pu0").encode()).hexdigest()[:12], "profile": pool[j]} for j in pick]
out = {"day": "pu0", "frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "truth_sha256_prefix": "0d81ad0965c5", "launches": L, "users": USERS,
       "code_commit": subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()}
for name, obj in (("pu0/lineup_full.json", out), ("category_tasks.json", TK)):
    f = f"/tmp/pu0_{name.replace('/', '_')}"; json.dump(obj, open(f, "w"), indent=1); subprocess.run(["gsutil", "-q", "cp", f, f"{PRIV}/{name}"], check=True)
print(json.dumps({"products": len(L), "categories": len({l["category"] for l in L}), "top": [l["id"] for l in L[:5]]}))
