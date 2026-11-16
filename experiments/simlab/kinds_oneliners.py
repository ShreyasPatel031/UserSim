"""Founder one-liners (user ask, Nov 16): for each product, (1) vet its 30 most similar past launches for TRUE competitors (a buyer would choose
between the two for the same job) with one Gemini call; (2) keep direct substitutes, rank by popularity (votes), take the top 3; (3) for each,
count its tracked backers and split them by leave-one-out taste: closer to this product or to the competitor; (4) read the competitor's REAL
non-team comments + description against the product's text for a concrete thing its backers valued that the product does not offer; (5) one line."""
import json, sys, re, numpy as np, pandas as pd, concurrent.futures as cf
SP, DAY = sys.argv[1:3]; OUT = f"{SP}/kinds"
sys.path.insert(0, "/home/user/UserSim/experiments"); sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
from pipeline import warehouse
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); P = pd.read_parquet(f"{OUT}/people.parquet").set_index("person_id")
C = json.load(open(f"{OUT}/compete_{DAY}.json")); Z = np.load(f"{OUT}/top10_emb_{DAY}.npy"); AC = pd.read_parquet(f"{OUT}/all_comments.parquet"); NT = AC[~AC.team]
W = warehouse.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); W["id"] = W.id.astype(str); W = W.set_index("id")
votes = pd.to_numeric(W.votes, errors="coerce"); rank = pd.to_numeric(W.daily_rank, errors="coerce")
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates(); del E
U["target_id"] = U.target_id.astype(str); li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day)); U = U[U.target_id.isin(set(L.id[L.day < "2026-11-13"])) & U.person_id.isin(set(P.index))].reset_index(drop=True)
pid = {p: i for i, p in enumerate(P.index)}; U["pi"] = U.person_id.map(pid); U["li"] = U.target_id.map(li)
S = np.zeros((len(P), X.shape[1]), np.float32); np.add.at(S, U.pi.values, X[U.li.values]); N = np.bincount(U.pi.values, minlength=len(P)).astype(np.float32); mu = (S / N[:, None]).mean(0)
voters = {k: np.unique(v) for k, v in U.groupby("target_id").pi.apply(list).items()}; cand = [l for l in L.id if len(voters.get(l, [])) >= 20 and day[l] < "2026-11-13"]; XC = X[[li[l] for l in cand]]
scrub = lambda t: re.sub(r"@[A-Za-z0-9_]{2,}", "", str(t))
def g(p, mt):
    try: return json.loads(llm.gemini_call(p, mt))
    except Exception: return None
def one(k):
    p = C["products"][k]; z = Z[k]; s = XC @ z; top = [cand[j] for j in np.argsort(-s)[:30]]
    ptxt = (f"NAME: {p['name']}\nTAGLINE: {p['tagline']}\nDESCRIPTION: {p['description']}\nMAKER'S LAUNCH NOTE: {scrub(p.get('maker_intro') or '')[:1500]}" + (f"\nFROM THE SITE: {p['site_text'][:1800]}" if p.get("site_text") else ""))
    vet = g("A founder launched the product below. For each candidate, decide whether it is a TRUE COMPETITOR: a buyer with the same job to be done would realistically choose between the two (a substitute), "
            "not merely a product in the same broad area, a complement, or a tool for a different user. Be strict.\nJSON only: {\"candidates\": [{\"n\": <number>, \"verdict\": \"direct\"|\"adjacent\"|\"no\", \"same_job\": \"<the shared job in 6 words, or ''>\"}]}\n\n"
            "PRODUCT\n" + ptxt + "\n\nCANDIDATES\n" + "\n".join(f"{n + 1}. {L.name[li[c]]}: {L.tagline[li[c]]}. {(L.description[li[c]] or '')[:260]}" for n, c in enumerate(top)), 2500) or {}
    direct = [(top[int(x["n"]) - 1], x.get("same_job")) for x in vet.get("candidates", []) if x.get("verdict") == "direct" and 1 <= int(x.get("n", 0)) <= len(top)]
    direct = sorted(direct, key=lambda x: -(votes.get(x[0], 0) if pd.notna(votes.get(x[0], np.nan)) else 0))[:3]
    res = {"id": p["id"], "rank": p["rank"], "name": p["name"], "votes": p["votes"], "n_candidates": len(top), "n_direct": len([x for x in vet.get("candidates", []) if x.get("verdict") == "direct"]), "competitors": []}
    if not direct: res["line"] = None; res["note"] = "no true competitor among the 30 most similar past launches"; return res
    blocks = []
    for c, job in direct:
        v = voters[c]; t = S[v] - X[li[c]]; n = N[v] - 1; ok = n > 0; t = t[ok] / n[ok][:, None] - mu; t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-9
        dc = t @ (z - X[li[c]]); toward = float((dc > 0).mean()); cm = [scrub(x)[:300] for x in NT[NT.launch_id == c].text.tolist()[:14]]
        info = {"id": c, "name": L.name[li[c]], "tagline": L.tagline[li[c]], "day": day[c], "votes": None if pd.isna(votes.get(c, np.nan)) else int(votes[c]), "daily_rank": None if pd.isna(rank.get(c, np.nan)) else int(rank[c]),
                "same_job": job, "tracked_backers": int(ok.sum()), "share_closer_to_you": round(toward, 2), "backers_closer_to_them": int(round((1 - toward) * ok.sum())), "real_comments_held": len(cm)}
        res["competitors"].append(info)
        blocks.append(f"COMPETITOR {info['name']} (ranked #{info['daily_rank']} with {info['votes']} votes on {info['day']}; {info['tracked_backers']} tracked backers, {info['backers_closer_to_them']} of them have tastes closer to it than to the founder's product)\n"
                      f"  Tagline: {info['tagline']}\n  Description: {(L.description[li[c]] or '')[:500]}\n  Real user comments on it: " + (" || ".join(cm) if cm else "(none held)"))
    out = g("Write founder one-liners. A founder launched PRODUCT. Below are its true competitors, with how many of each competitor's backers have tastes closer to the competitor than to the founder's product, "
            "and real user comments on each competitor.\nFor EACH competitor find ONE concrete thing its users valued or asked for (from the real comments if any, else from its description) that the founder's product text does NOT offer or mention, "
            "and that the founder could realistically add or state. It must be a specific capability, platform, integration, pricing term or guarantee - never 'better UX', 'more features', 'marketing' or anything about team, hunter or timing. "
            "If the founder's product already has it, or nothing concrete differs, say so and return line null for that competitor.\n"
            "Line format (max 32 words, plain words, no hype): '<N> people who backed <Competitor> lean away from you: they valued <specific thing> there, and your page doesn't mention it. <Imperative action>.'\n"
            "JSON only: {\"lines\": [{\"competitor\": \"...\", \"thing_valued\": \"...\", \"evidence\": \"<short paraphrase of the real comment or description phrase>\", \"evidence_source\": \"comment\"|\"description\", "
            "\"product_has_it\": \"no\"|\"partly\"|\"yes\", \"product_evidence\": \"<quote from the product text or 'not mentioned'>\", \"line\": \"<the one-liner or null>\"}], "
            "\"keep_line\": \"<one line, max 28 words: what the people who would NOT pick these competitors come to this product for, so the founder protects it>\"}\n\nPRODUCT\n" + ptxt + "\n\n" + "\n\n".join(blocks), 2500) or {}
    res["lines"] = out.get("lines"); res["keep_line"] = out.get("keep_line"); return res
with cf.ThreadPoolExecutor(5) as ex: R = list(ex.map(one, range(len(C["products"]))))
R = json.loads(re.sub(r"@[A-Za-z0-9_]{2,}", "", json.dumps(R)))
json.dump({"day": DAY, "products": R, "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}, open(f"{OUT}/oneliners_{DAY}.json", "w"), indent=1)
print("usd", round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3))
for r in R:
    print("\n#", r["rank"], r["name"], "| direct competitors found:", r["n_direct"], "of", r["n_candidates"], r.get("note") or "")
    for c in r["competitors"]: print("   ", c["name"], f"#{c['daily_rank']}, {c['votes']} votes |", c["same_job"], "| backers", c["tracked_backers"], "closer to them", c["backers_closer_to_them"], "| comments", c["real_comments_held"])
    for x in (r.get("lines") or []): print("   >", x.get("line"), "| has:", x.get("product_has_it"), "| src:", x.get("evidence_source"), "|", (x.get("evidence") or "")[:160])
    print("   KEEP:", r.get("keep_line"))
