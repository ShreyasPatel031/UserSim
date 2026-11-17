import json, os, re, sys, gzip, glob, html, collections
SP, STAGE, EXCL = sys.argv[1], sys.argv[2], set(json.loads(sys.argv[3])); OUT = f"{SP}/chain"
sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
scrub = lambda s: re.sub(r"@\w+", "", s) if isinstance(s, str) else s
D = json.load(open(f"{OUT}/out{STAGE}.json")); CFG = json.load(open(f"{OUT}/stage{STAGE}.json")); COMP = [c for c in D["competitors"] if c["name"] not in EXCL]
# real comments on competitors' launches, by name match in held captures
names = {c["name"] for c in COMP if c["source"] == "held"} | set(CFG.get("extra_comment_names", [])); raw = collections.defaultdict(dict); team = collections.defaultdict(set)
clean = lambda b: re.sub(r"@\w+", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b or "")))).strip()
for f in sorted(glob.glob(f"{SP}/rb/h25data/comments/*.jsonl.gz")):
    with gzip.open(f, "rt") as fh:
        for line in fh:
            try: post = json.loads(json.loads(line)["html"])["data"]["post"]
            except Exception: continue
            if not post or post.get("name") not in names: continue
            def add(n):
                u = n.get("user") or {}; bl = json.dumps(n.get("badges") or []).lower()
                if "maker" in bl or "hunter" in bl or str(u.get("id")) == str((post.get("user") or {}).get("id")): team[post["name"]].add(u.get("id"))
                raw[post["name"]][n["id"]] = (u.get("id"), clean(n.get("body") or n.get("bodyHtml")))
            for e in post["threads"]["edges"]:
                add(e["node"])
                for e2 in (e["node"].get("replies") or {}).get("edges") or []: add(e2["node"])
code = {}; lines = []
for nm in raw:
    for cid, (u, t) in raw[nm].items():
        if u in team[nm] or len(t) <= 15: continue
        lines.append(f"[{code.setdefault((nm, u), f'c{len(code) + 1}')} | {nm}] {t[:600]}")
CM = {"products": sorted(raw), "n_commenters": len(code), "themes": []}
if lines:
    PR = """Below are real comments left by Product Hunt users on the launches of several products that do a similar job. Team replies are removed.
Each line: [commenter code | product] comment.
Group what the commenters said into themes. A theme has a kind: "asked" (a feature or answer they asked for), "complained" (a complaint, doubt or worry) or "praised" (something they liked).
A theme must be specific to what the product does (not congratulations). Merge near-duplicates aggressively: aim for at most 14 themes. For each theme list every commenter code that raised it.
Return JSON: {"themes": [{"kind": "...", "theme": "<under 16 words, plain language, no person names>", "commenters": ["c1", ...], "products": ["..."]}]}
Do not name any person.

"""
    try:
        th = json.loads(re.search(r"\{.*\}", llm.gemini_call(PR + "\n".join(lines[:260]), 6000), re.S).group(0))["themes"]
        CM["themes"] = sorted([{"kind": t["kind"], "theme": scrub(t["theme"]), "n": len(set(t.get("commenters", [])) & set(code.values())), "products": sorted(set(t.get("products", [])))} for t in th], key=lambda t: -t["n"])
    except Exception as ex_: CM["error"] = str(ex_)[:100]

D["comments"] = CM; json.dump(D, open(f"{OUT}/out{STAGE}.json", "w"), indent=1)
print("COMMENTS", CM["products"], CM["n_commenters"])
for t in CM["themes"]: print(f"  {t['n']:>2} {t['kind']:<10} {t['theme']} {t['products']}")
