"""Competitors for every launch, chosen the better way (comp_gemini.py: Gemini naming competitors found 29% of the
alternatives real users name, vs 14% for meaning similarity). For each launch: Gemini names its 5 main competitors from
its own knowledge; any that launched on Product Hunt at least 2 days earlier (name match) are kept; Gemini then picks
from the 50 nearest earlier launches by meaning to fill up to 5. Output data/comp_lists.json {launch_id: {"named":
[names], "ids": [up to 5 earlier launch ids]}}; cmp_features.py uses it with COMP_LIST=1.
usage: python comp_lists.py [threads] -> data/comp_lists.json (resumable)"""
import glob, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import numpy as np
import llm

D = "data"; OUT = f"{D}/comp_lists.json"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def main(threads=16):
    L = {}
    for f in glob.glob(f"{D}/days/*.json"):
        for p in json.load(open(f)):
            L[str(p["id"])] = {"day": f[-15:-5], "name": p["name"], "tagline": p.get("tagline") or "", "description": (p.get("description") or "")[:500]}
    Z = np.load(f"{D}/emb.npz"); ids = [str(x) for x in Z["launch_ids"]]
    V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True); ix = {x: k for k, x in enumerate(ids)}
    od = np.array([date.fromisoformat(L[x]["day"]).toordinal() if x in L else 10**9 for x in ids])
    by_name = {}
    for x in sorted(L, key=lambda x: L[x]["day"]):
        by_name.setdefault(norm(L[x]["name"]), []).append(x)
    done = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [x for x in L if x not in done and x in ix]
    print("launches", len(todo), flush=True)

    def one(x):
        me = L[x]; d0 = date.fromisoformat(me["day"]).toordinal()
        desc = f"{me['name']}: {me['tagline']}. {me['description']}"
        r = llm.call(f"Product: {desc}\n\nName this product's 5 main competitors (products a user would choose instead). "
                     'Reply with JSON only: {"competitors": ["name", ...]}', max_tokens=150)
        mm = re.search(r'"competitors"\s*:\s*\[([^\]]*)\]', r or "")
        named = re.findall(r'"([^"]+)"', mm.group(1))[:5] if mm else []
        keep = []
        for n in named:   # named competitors that launched on Product Hunt at least 2 days before
            for y in by_name.get(norm(n), []):
                if y != x and date.fromisoformat(L[y]["day"]).toordinal() <= d0 - 2 and y not in keep:
                    keep.append(y); break
        if len(keep) < 5:
            s = V @ V[ix[x]]; s[od > od[ix[x]] - 2] = -9
            cands = [ids[j] for j in np.argsort(-s)[:50] if s[j] > -9 and ids[j] not in keep and norm(L[ids[j]]["name"]) != norm(me["name"])]
            if cands:
                lst = "\n".join(f"{n + 1}. {L[c]['name']}: {L[c]['tagline']}" for n, c in enumerate(cands))
                r2 = llm.call(f"Product: {desc}\n\nCandidates:\n{lst}\n\nWhich {5 - len(keep)} candidates are this product's most direct "
                              'competitors (a user would choose one instead of the other)? Reply with JSON only: {"picks": [candidate numbers]}', max_tokens=100)
                m2 = re.search(r'"picks"\s*:\s*\[([^\]]*)\]', r2 or "")
                for t in (re.findall(r"\d+", m2.group(1)) if m2 else []):
                    if 1 <= int(t) <= len(cands) and cands[int(t) - 1] not in keep:
                        keep.append(cands[int(t) - 1])
                    if len(keep) == 5:
                        break
        return x, {"named": named, "ids": keep[:5]}
    with ThreadPoolExecutor(threads) as ex:
        for k, (x, v) in enumerate(ex.map(one, todo)):
            done[x] = v
            if k % 500 == 0:
                json.dump(done, open(OUT, "w")); print(k, "usd", round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 2), flush=True)
    json.dump(done, open(OUT, "w"))
    print("done", len(done), "usd", round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 2), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 16)
