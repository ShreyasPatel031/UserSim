"""Per product: (a) contrast among its 30 most similar past launches - those that drew a subgroup strongly vs those that did not - read by Gemini for
what the strong ones have that this product lacks; (b) founder-style interviews with personas built from REAL members (own upvote history + own
past comments); (c) judge: do the simulated concerns match the real comments on the product; (d) synthesis into specific actions."""
import json, sys, os, re, gzip, glob, html, numpy as np, pandas as pd, concurrent.futures as cf
SP, DAY = sys.argv[1:3]; OUT = f"{SP}/kinds"; rng = np.random.default_rng(1)
sys.path.insert(0, f"{SP}/phops/experiments/ph_predict"); import llm
C = json.load(open(f"{OUT}/compete_{DAY}.json")); G = json.load(open(f"{OUT}/regroup.json")); SUB = {s["id"]: s for s in G["subgroups"]}
L = pd.read_parquet(f"{OUT}/launches_k.parquet"); X = np.load(f"{OUT}/launch_emb.npy"); Z = np.load(f"{OUT}/top10_emb_{DAY}.npy"); PU = pd.read_parquet(f"{OUT}/people_units2.parquet").set_index("person_id"); A = pd.read_parquet(f"{OUT}/attrs.parquet")
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind", "target_id", "extra"]); U = E[E.kind == "upvote"][["person_id", "target_id"]].drop_duplicates()
CE = E[(E.kind == "comment") & E.person_id.isin(set(PU.index))][["person_id", "extra"]]; del E
U["target_id"] = U.target_id.astype(str); U = U[U.target_id.isin(set(L.id[L.day < "2026-11-13"])) & U.person_id.isin(set(PU.index))]; U["s"] = U.person_id.map(PU["sub"]); li = dict(zip(L.id, L.i)); day = dict(zip(L.id, L.day))
ct = pd.crosstab(U.target_id, U.s); ct = ct[ct.sum(1) >= 30]; base = ct.sum(0) / ct.values.sum(); LIFT = ((ct + 20 * base.values).div(ct.sum(1) + 20, axis=0)) / base.values; cand = list(LIFT.index); XC = X[[li[l] for l in cand]]
# all comments by tracked people, cached: person, launch id, text
cache = f"{OUT}/tracked_comments.parquet"
if os.path.exists(cache): TC = pd.read_parquet(cache)
else:
    CE["cid"] = CE.extra.map(lambda e: str(json.loads(e).get("comment_id")) if isinstance(e, str) and e.startswith("{") else None); c2p = dict(zip(CE.cid, CE.person_id)); rows = []
    for f in sorted(glob.glob(f"{SP}/cf/page*.jsonl.gz")):
        for line in gzip.open(f):
            try: p_ = json.loads(json.loads(line)["html"])["data"]["post"]
            except Exception: continue
            if not p_: continue
            def walk(nd):
                i = str(nd.get("id"))
                if i in c2p:
                    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", nd.get("bodyHtml") or ""))).strip()
                    if len(t) > 40: rows.append((c2p[i], str(p_["id"]), p_.get("name"), t[:400]))
                for e in ((nd.get("replies") or {}).get("edges") or []): walk(e["node"])
            for e in ((p_.get("threads") or {}).get("edges") or []): walk(e["node"])
    TC = pd.DataFrame(rows, columns=["person_id", "launch_id", "launch_name", "text"]); TC.to_parquet(cache)
TC["s"] = TC.person_id.map(PU["sub"]); pc = TC.groupby("person_id").size(); nvotes = U.groupby("person_id").size()
ROLE = ["developer", "founder", "marketer", "designer", "investor", "student", "product manager"]
J = lambda t: json.loads(t)
def ptext(p, n=2600):
    return (f"NAME: {p['name']}\nTAGLINE: {p['tagline']}\nTOPICS: {', '.join(p['topics'])}\nDESCRIPTION: {p['description']}\nMAKER'S LAUNCH NOTE: {(p.get('maker_intro') or '')[:1500]}" +
            (f"\nFROM THE PRODUCT SITE ({p['site_url']}): {p['site_text'][:n]}" if p.get("site_text") else ""))
def persona(pid):
    h = U[U.person_id == pid].assign(d=lambda x: x.target_id.map(day)).sort_values("d", ascending=False).head(14)
    cm = TC[TC.person_id == pid].head(3)
    return ("roles: " + (", ".join(r for r in ROLE if A.loc[pid, r]) or "not stated") + f"; votes on record: {int(nvotes.get(pid, 0))}\n   recently upvoted: " + "; ".join(f"{L.name[li[t]]} ({L.tagline[li[t]]})" for t in h.target_id) +
            ("\n   their own past comments: " + " || ".join(f"on {a}: \"{b[:260]}\"" for a, b in zip(cm.launch_name, cm.text)) if len(cm) else ""))
def one(pi):
    p = C["products"][pi]; z = Z[pi]; sim = XC @ z; nb = np.argsort(-sim)[:30]; nbl = LIFT.iloc[nb]; res = {"id": p["id"], "name": p["name"]}
    # (a) contrast sets
    cons = []
    for s in LIFT.columns:
        if "All-round" in SUB[s]["name"] or base[s] < 0.03: continue
        o = nbl[s].sort_values(ascending=False); top, bot = o.index[:8], o.index[-8:]; T, Bm = float(o[:8].mean()), float(o[-8:].mean()); pl = float(nbl[s].mean())
        if T >= 1.4 and T / max(Bm, 0.05) >= 1.6: cons.append({"sub_id": int(s), "subgroup": SUB[s]["name"], "parent": SUB[s]["parent_name"], "strong_mean_lift": round(T, 2), "weak_mean_lift": round(Bm, 2), "product_predicted_lift": round(pl, 2),
                                                               "subgroup_share_of_all_votes": round(float(base[s]), 3), "gain_points_if_matched": round(float(base[s] * (T - pl)) * 100, 1), "strong": list(top), "weak": list(bot)})
    cons = sorted(cons, key=lambda c: -c["gain_points_if_matched"])[:3]
    def lst(ids, s): return "\n".join(f"   - {L.name[li[i]]} ({L.tagline[li[i]]}) [pull {LIFT.loc[i, s]:.1f}x] {(L.description[li[i]] or '')[:260]}" for i in ids)
    blocks = []
    for c in cons:
        s = c["sub_id"]; cm = TC[(TC.s == s) & TC.launch_id.isin(set(c["strong"]))].head(8)
        blocks.append(f"SUBGROUP [{s}] {c['subgroup']} - {SUB[s]['goes_for']}\n  Similar launches that DREW them (mean pull {c['strong_mean_lift']}x):\n{lst(c['strong'], s)}\n  Similar launches that did NOT (mean pull {c['weak_mean_lift']}x):\n{lst(c['weak'], s)}\n"
                      "  Real comments by this subgroup's members on the launches that drew them: " + (" || ".join(f"on {a}: \"{b[:240]}\"" for a, b in zip(cm.launch_name, cm.text)) or "(none held)"))
    if cons:
        pr = ("A founder launched the product below on Product Hunt. For each voter subgroup, compare the similar past launches that drew that subgroup strongly with the similar ones that did not. "
              "Find the concrete PRODUCT or POSITIONING attribute that the strong set shares and the weak set lacks (a feature, platform, pricing model, openness, integration, audience named in the tagline...). "
              "Then check the founder's product text: does it already have that attribute? Quote the evidence. If the two sets do not differ in any concrete way, say so plainly - do not invent a pattern.\n"
              "JSON only: {\"contrasts\": [{\"sub_id\": <n>, \"what_strong_ones_share\": \"...\", \"examples\": [\"<launch>: <attribute>\", ...], \"founder_product_has_it\": \"yes|partly|no\", \"evidence\": \"<quote or 'not mentioned'>\", "
              "\"move\": \"<one specific thing to build, change or say; or 'none - no clear difference'>\", \"confidence\": \"low|medium|high\", \"why_confidence\": \"...\"}]}\n\nFOUNDER'S PRODUCT\n" + ptext(p) + "\n\n" + "\n\n".join(blocks))
        try: cr = {int(x["sub_id"]): x for x in J(llm.gemini_call(pr, 3500))["contrasts"]}
        except Exception: cr = {}
        for c in cons: c["reading"] = cr.get(c["sub_id"]); c["strong"] = [L.name[li[i]] for i in c["strong"]]; c["weak"] = [L.name[li[i]] for i in c["weak"]]
    res["contrasts"] = cons
    # (b) interviews: real members of the top-2 pulled subgroups and the contrast subgroups
    pull = [x for x in p["subgroup_pull"] if "All-round" not in x["subgroup"]]; targets = [(x["sub_id"], "already drawn to it") for x in pull[:2]] + [(c["sub_id"], "could be won") for c in cons if c["sub_id"] not in {x["sub_id"] for x in pull[:2]}][:2]
    comp = next((c for c in p["competitors"] if (c["daily_rank"] or 99) <= 5), p["competitors"][0]); people = []
    for s, why in targets:
        mem = PU.index[PU["sub"] == s]; mem = [m for m in mem if nvotes.get(m, 0) >= 12]; has_c = [m for m in mem if pc.get(m, 0) >= 1]; pool = has_c if len(has_c) >= 3 else mem
        for m in rng.choice(pool, min(3, len(pool)), replace=False): people.append((s, why, m))
    pr = ("You run user interviews for a founder. Below are real Product Hunt users (anonymous; known only by their upvote history and their own past comments). Answer AS each user would, in their own voice and priorities, "
          "grounded in their history - a user who has never backed this kind of product should say so and be lukewarm. Be specific to THIS product's actual features and text; no generic praise.\n"
          "For each user return: would_upvote (yes/maybe/no) and why in one sentence; what they use today for this job; between this product and the competitor, which they would pick and the deciding factor; "
          "the ONE change that would make them upvote or pay; their dealbreaker; the question they would ask the maker.\n"
          "JSON only: {\"interviews\": [{\"user\": <n>, \"would_upvote\": \"yes|maybe|no\", \"why\": \"...\", \"uses_today\": \"...\", \"pick_vs_competitor\": \"...\", \"one_change\": \"...\", \"dealbreaker\": \"...\", \"question\": \"...\"}]}\n\n"
          "THE PRODUCT\n" + ptext(p) + f"\n\nTHE COMPETITOR (a similar past launch that ranked #{comp['daily_rank']} with {comp['votes']} votes)\nNAME: {comp['name']}\nTAGLINE: {comp['tagline']}\nDESCRIPTION: {comp['description']}\n\nUSERS\n" +
          "\n".join(f"{k + 1}. subgroup: {SUB[s]['name']} ({SUB[s]['goes_for']})\n   {persona(m)}" for k, (s, why, m) in enumerate(people)))
    try: iv = J(llm.gemini_call(pr, 6000))["interviews"]
    except Exception: iv = []
    for x in iv:
        k = int(x.get("user", 0)) - 1
        if 0 <= k < len(people): x["subgroup"] = SUB[people[k][0]]["name"]; x["status"] = people[k][1]
    res["interviews"] = iv; res["interview_competitor"] = comp["name"]
    # (c) judge simulated concerns against the real comments
    real = [b for b in p["real_comments"] if len(b) > 40][:22]
    if real and iv:
        pr = ("REAL comments left on a Product Hunt launch (some are the maker's replies - ignore those) and concerns/questions raised by SIMULATED users for the same product.\n"
              "1) List the distinct concerns or questions real commenters raised (max 10). 2) For each, say whether any simulated user raised the same point (same substance, not just same topic). "
              "3) Count simulated points that no real commenter raised.\nJSON only: {\"real_points\": [{\"point\": \"...\", \"matched_by_simulation\": true|false}], \"simulated_points_total\": <n>, \"simulated_points_not_in_real\": <n>}\n\nREAL:\n" +
              "\n".join("- " + b[:350] for b in real) + "\n\nSIMULATED:\n" + "\n".join(f"- {x.get('dealbreaker')} | {x.get('question')} | {x.get('one_change')}" for x in iv))
        try: res["judge"] = J(llm.gemini_call(pr, 2500))
        except Exception: res["judge"] = None
    # (d) synthesis
    pr = ("You advise the founder of the product below, the day after its Product Hunt launch. Use ONLY the evidence given. Write at most 3 actions, each specific to this product: what to build, change or say; "
          "which voter subgroup it wins; the evidence (a number from the data and a quote from a real comment or an interview). Forbidden: generic advice (get a better hunter, post more, grow the team, improve marketing, engage the community). "
          "If the evidence for something is thin, say so. Also give one thing the data says is NOT worth doing.\n"
          "JSON only: {\"headline\": \"<one sentence: who this product pulls and who it misses>\", \"actions\": [{\"do\": \"...\", \"wins\": \"<subgroup>\", \"evidence\": \"...\", \"confidence\": \"low|medium|high\"}], \"not_worth_doing\": \"...\"}\n\n"
          "PRODUCT\n" + ptext(p, 1500) + f"\n\nRESULT: rank {p['rank']}, {p['votes']} votes, {p['comments']} comments\n\nPULL BY GROUP (1.0 = usual): " + json.dumps({g: v['lift'] for g, v in p['parent_pull'].items()}) +
          "\nSTRONGEST SUBGROUPS: " + json.dumps([(x['subgroup'], x['lift'], f"{round(100 * x['share'], 1)}% of voters") for x in p['subgroup_pull'][:4]]) + "\nWEAKEST: " + json.dumps([(x['subgroup'], x['lift']) for x in p['subgroup_pull'][-3:]]) +
          "\n\nCONTRAST WITH SIMILAR LAUNCHES: " + json.dumps([{k: c.get(k) for k in ("subgroup", "strong_mean_lift", "weak_mean_lift", "product_predicted_lift", "gain_points_if_matched", "reading")} for c in cons]) +
          "\n\nSIMULATED USER INTERVIEWS: " + json.dumps(iv) + "\n\nREAL COMMENTS ON THE LAUNCH: " + json.dumps(real[:14]))
    try: res["advice"] = J(llm.gemini_call(pr, 2500))
    except Exception: res["advice"] = None
    return res
with cf.ThreadPoolExecutor(5) as ex: R = list(ex.map(one, range(len(C["products"]))))
jr = [r["judge"] for r in R if r.get("judge")]; tot = sum(len(j["real_points"]) for j in jr); hit = sum(sum(bool(x.get("matched_by_simulation")) for x in j["real_points"]) for j in jr)
st = sum(int(j.get("simulated_points_total") or 0) for j in jr); sn = sum(int(j.get("simulated_points_not_in_real") or 0) for j in jr)
out = {"day": DAY, "interview_validity": {"products_judged": len(jr), "real_points": tot, "real_points_also_raised_by_simulation": hit, "recall": round(hit / max(1, tot), 3), "simulated_points": st,
       "simulated_points_not_in_real_comments": sn, "precision": round(1 - sn / max(1, st), 3)}, "products": R, "usd": round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)}
json.dump(out, open(f"{OUT}/interviews_{DAY}.json", "w"), indent=1); print(json.dumps(out["interview_validity"]), out["usd"])
for r in R:
    print("\n#", r["name"], "|", (r.get("advice") or {}).get("headline"))
    for c in r["contrasts"]: print("   CONTRAST", c["subgroup"], c["strong_mean_lift"], "vs", c["weak_mean_lift"], "| +", c["gain_points_if_matched"], "|", (c.get("reading") or {}).get("what_strong_ones_share"), "| has it:", (c.get("reading") or {}).get("founder_product_has_it"), "| conf", (c.get("reading") or {}).get("confidence"))
    print("   votes:", [(x.get("subgroup"), x.get("would_upvote")) for x in r["interviews"]])
    for a in (r.get("advice") or {}).get("actions", []): print("   DO:", a.get("do"), "| wins", a.get("wins"), "|", a.get("confidence"), "|", (a.get("evidence") or "")[:260])
    print("   NOT:", (r.get("advice") or {}).get("not_worth_doing"))
