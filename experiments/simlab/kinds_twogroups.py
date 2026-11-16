"""Per product (a day's top 10): its market = people who voted for any of its 30 most similar earlier launches. Score d = taste . (z_product -
mean z_competitors): high = drawn to what is distinct about this product, low = drawn to what the competitors share and it lacks.
WIN group: top 15% of d in the market. LOSE group: bottom 15% of d among people who backed >= 2 of the competitors.
Profiles (size, roles vs market, which competitors each group backs more or less than the market, their own real comments on those
competitors), then Gemini interviews of 4 real members' profiles per group with founder questions, and a short synthesis."""
import json, sys, re, numpy as np, pandas as pd, concurrent.futures as cf
SP, DAY = sys.argv[1:3]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(3)
sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
C = json.load(open(f"{OUT}/compete_{DAY}.json")); Z = np.load(f"{OUT}/top10_emb_{DAY}.npy"); TC = pd.read_parquet(f"{OUT}/tracked_comments.parquet")
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day)); U = U[U.target_id.isin(set(L.id[L.day < "2026-11-13"])) & U.person_id.isin(set(P.index))].reset_index(drop=True)
pid = {p: i for i, p in enumerate(P.index)}; U["pi"] = U.person_id.map(pid); U["li"] = U.target_id.map(li)
S = np.zeros((len(P), X.shape[1]), np.float32); np.add.at(S, U.pi.values, X[U.li.values]); N = np.bincount(U.pi.values, minlength=len(P)).astype(np.float32)
T = S / N[:, None]; T -= T.mean(0); T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9
voters = {k: np.unique(v) for k, v in U.groupby("target_id").pi.apply(list).items()}; big = [l for l in L.id if len(voters.get(l, [])) >= 30 and day[l] < "2026-11-13"]; XB = X[[li[l] for l in big]]
pids = np.array(P.index); ROLE = ["developer", "founder", "marketer", "designer", "investor", "student", "product manager"]; scrub = lambda t: re.sub(r"@[A-Za-z0-9_]{2,}", "", str(t))
TC = TC[TC.person_id.isin(set(P.index))]; pcnt = TC.groupby("person_id").size()
def g(p, mt):
    try: return json.loads(llm.gemini_call(p, mt))
    except Exception: return None
def one(k):
    p = C["products"][k]; z = Z[k]; s = XB @ z; comp = [big[j] for j in np.argsort(-s)[:30]]
    cnt = np.zeros(len(P), int)
    for c in comp: cnt[voters[c]] += 1
    mk = np.flatnonzero(cnt > 0); zc = X[[li[c] for c in comp]].mean(0); d = T[mk] @ (z - zc)
    win = mk[d >= np.quantile(d, 0.85)]; lp = mk[(cnt[mk] >= 2)]; dl = T[lp] @ (z - zc); lose = lp[dl <= np.quantile(dl, 0.15)]
    def prof(grp):
        ppl = pids[grp]; rl = (A.loc[ppl, ROLE].mean() / A.loc[pids[mk], ROLE].mean()).round(2)
        rate = {c: len(np.intersect1d(voters[c], grp)) / len(grp) for c in comp}; mrate = {c: len(np.intersect1d(voters[c], mk)) / len(mk) for c in comp}
        rel = sorted(((c, rate[c] / max(mrate[c], 1e-9)) for c in comp if mrate[c] > 0), key=lambda x: -x[1])
        cm = TC[TC.person_id.isin(set(ppl)) & TC.launch_id.isin(set(comp))]
        return {"people": int(len(grp)), "roles_vs_market": {r: float(v) for r, v in rl.items() if abs(v - 1) >= 0.15}, "median_votes": float(np.median(N[grp])),
                "competitors_backed_more": [(L.name[li[c]], round(v, 2)) for c, v in rel[:5]], "competitors_backed_less": [(L.name[li[c]], round(v, 2)) for c, v in rel[-5:]],
                "their_comments_on_competitors": [f"on {a}: {scrub(b)[:260]}" for a, b in zip(cm.launch_name, cm.text)][:10]}
    PW, PL = prof(win), prof(lose)
    def pick(grp, key):
        c = [i for i in grp if N[i] >= 12]; c = sorted(c, key=key)[:40]; hc = [i for i in c if pcnt.get(pids[i], 0) >= 1]; pool = hc if len(hc) >= 4 else c
        return list(rng.choice(pool, min(4, len(pool)), replace=False))
    dm = dict(zip(mk, T[mk] @ (z - zc)))
    pw = pick(win, lambda i: -dm[i]); pl = pick(lose, lambda i: (-cnt[i], dm[i]))
    def persona(i, comps_voted):
        h = U[U.pi == i].assign(d=lambda x: x.target_id.map(day)).sort_values("d", ascending=False).head(12); cm = TC[TC.person_id == pids[i]].head(2)
        return ("roles: " + (", ".join(r for r in ROLE if A.loc[pids[i], r]) or "not stated") + "; recently upvoted: " + "; ".join(f"{L.name[li[t]]} ({L.tagline[li[t]]})" for t in h.target_id) +
                (f"; among this product's competitors they upvoted: {', '.join(comps_voted)}" if comps_voted else "; upvoted none of this product's close competitors") +
                ("; their own past comments: " + " || ".join(f"\"{scrub(b)[:200]}\"" for b in cm.text) if len(cm) else ""))
    cv = lambda i: [L.name[li[c]] for c in comp if i in set(voters[c])][:4]
    ptxt = (f"NAME: {p['name']}\nTAGLINE: {p['tagline']}\nDESCRIPTION: {p['description']}\nMAKER'S LAUNCH NOTE: {scrub(p.get('maker_intro') or '')[:1400]}" +
            (f"\nFROM THE SITE: {p['site_text'][:1800]}" if p.get("site_text") else ""))
    comps_txt = "\n".join(f"- {L.name[li[c]]}: {L.tagline[li[c]]}. {(L.description[li[c]] or '')[:220]}" for c in comp[:8])
    pr = ("You run founder interviews. Below is a product, its closest competitors, and two groups of real Product Hunt users (anonymous, known by upvote history, which competitors they backed, and their own past comments).\n"
          "GROUP A = users strongly drawn to what is DIFFERENT about this product and who mostly skip the competitors. GROUP B = users who backed several competitors but are drawn away from this product.\n"
          "Answer AS each user, grounded in their own history; be concrete about this product's actual features and the named competitors; no generic praise. "
          "For A ask: why this over the competitors you skipped; the one thing that makes it different for you; what would make you drop it. "
          "For B ask: what the competitor you backed has that this lacks; what would make you switch; your dealbreaker with this product.\n"
          "JSON only: {\"A\": [{\"user\": <n>, \"verdict\": \"<one sentence>\", \"why_this\": \"...\", \"the_difference\": \"...\", \"would_drop_it_if\": \"...\"}], "
          "\"B\": [{\"user\": <n>, \"verdict\": \"...\", \"competitor_has\": \"...\", \"would_switch_if\": \"...\", \"dealbreaker\": \"...\"}], "
          "\"synthesis\": {\"who_you_uniquely_win\": \"<one sentence, from A>\", \"what_wins_them\": \"<the specific feature or trait>\", \"who_you_lose_and_to_whom\": \"<one sentence naming competitors, from B>\", "
          "\"what_loses_them\": \"<the specific missing thing>\", \"move\": \"<one concrete change that wins B without losing A, or 'none clear'>\"}}\n\n"
          "PRODUCT\n" + ptxt + "\n\nCLOSEST COMPETITORS\n" + comps_txt +
          "\n\nGROUP A\n" + "\n".join(f"{n + 1}. {persona(i, cv(i))}" for n, i in enumerate(pw)) + "\n\nGROUP B\n" + "\n".join(f"{n + 1}. {persona(i, cv(i))}" for n, i in enumerate(pl)))
    iv = g(pr, 6000) or {}
    return {"id": p["id"], "rank": p["rank"], "name": p["name"], "tagline": p["tagline"], "market_people": int(len(mk)), "win": {**PW, "interviews": iv.get("A")}, "lose": {**PL, "interviews": iv.get("B")}, "synthesis": iv.get("synthesis")}
with cf.ThreadPoolExecutor(5) as ex: R = list(ex.map(one, range(len(C["products"]))))
s = json.dumps(R); s = re.sub(r"@[A-Za-z0-9_]{2,}", "", s); R = json.loads(s)
json.dump({"day": DAY, "products": R, "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}, open(f"{OUT}/twogroups_{DAY}.json", "w"), indent=1)
print("usd", round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3))
for r in R:
    print("\n#", r["rank"], r["name"], "| market", r["market_people"], "| WIN", r["win"]["people"], r["win"]["roles_vs_market"], "| LOSE", r["lose"]["people"], r["lose"]["roles_vs_market"])
    print("  win skips:", r["win"]["competitors_backed_less"][:3], "| lose backs:", r["lose"]["competitors_backed_more"][:3])
    print("  SYN:", json.dumps(r.get("synthesis"))[:900])
