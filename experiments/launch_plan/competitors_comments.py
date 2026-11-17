"""Real comments on competitors' Product Hunt launches, from held comment captures (no new requests). Team comments (hunter, makers) are dropped.
Each remaining comment is tagged by Gemini to a theme and a kind (asked for / complained or doubted / praised); themes are counted by distinct
commenters. Comment text and identities are not saved; only theme counts are."""
import gzip, json, glob, re, sys, os, html, collections
SP = sys.argv[1]; sys.path.insert(0, f"{SP}/rb/pp"); os.environ.setdefault("H25_DATA", f"{SP}/rb/h25data"); import llm
JOB = {"try": ["firstpass", "articos", "articos-mcp", "product-hunt-visual-launch-editor"], "board": ["nodus-ph-radar-for-product-hunt", "phbench-2"],
       "panel": ["sapien-9c8e5a42-2442-4af7-80c3-5ceb4034d612", "theysaid-4-0", "articos", "articos-mcp"], "pack": ["spira-for-product-hunt-makers", "submit-diy", "shippedit-me", "scroll-launch"]}
want = {s for v in JOB.values() for s in v}; raw = collections.defaultdict(dict); team = collections.defaultdict(set); name = {}
clean = lambda b: re.sub(r"@\w+", "", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b or "")))).strip()
def add(slug, n, post):
    u = n.get("user") or {}; bl = json.dumps(n.get("badges") or []).lower()
    if "maker" in bl or "hunter" in bl or str(u.get("id")) == str((post.get("user") or {}).get("id")): team[slug].add(u.get("id"))
    raw[slug][n["id"]] = (u.get("id"), clean(n.get("body") or n.get("bodyHtml")))
for f in sorted(glob.glob(f"{SP}/rb/h25data/comments/*.jsonl.gz")):
    with gzip.open(f, "rt") as fh:
        for line in fh:
            try: r = json.loads(line)
            except Exception: continue
            m = re.search(r"slug%22%3A%22([^%]+)%22", r["url"])
            if not m or m.group(1) not in want: continue
            try: post = json.loads(r["html"])["data"]["post"]
            except Exception: continue
            name[m.group(1)] = post["name"]
            for e in post["threads"]["edges"]:
                add(m.group(1), e["node"], post)
                for e2 in (e["node"].get("replies") or {}).get("edges") or []: add(m.group(1), e2["node"], post)
OUT = {"coverage": {}, "jobs": {}}
for s in want:
    users = {u for u, _ in raw[s].values()} - team[s]; OUT["coverage"][name.get(s, s)] = {"comments_held": len(raw[s]), "non_team_comments": sum(1 for u, t in raw[s].values() if u not in team[s] and len(t) > 15), "distinct_non_team_commenters": len(users)}
PROMPT = """Below are real comments left by Product Hunt users on the launches of several products that do a similar job. Team replies are removed.
Each line: [commenter code | product] comment.
Group what the commenters said into themes. A theme has a kind: "asked" (a feature or answer they asked for), "complained" (a complaint, doubt or worry) or "praised" (something they liked).
A theme must be specific to what the product does (not "congrats on the launch", not "good luck"). Merge near-duplicates. For each theme list every commenter code that raised it.
Return JSON: {"themes": [{"kind": "...", "theme": "<under 16 words, plain language, no person names>", "commenters": ["c1", ...], "products": ["..."]}]}
Ignore comments that only congratulate. Do not name any person.

"""
for job, slugs in JOB.items():
    code = {}; lines = []
    for s in slugs:
        for cid, (u, t) in raw[s].items():
            if u in team[s] or len(t) <= 15: continue
            c = code.setdefault((s, u), f"c{len(code) + 1}"); lines.append(f"[{c} | {name.get(s, s)}] {t[:600]}")
    if not lines: OUT["jobs"][job] = {"n_commenters": 0, "themes": []}; continue
    txt = llm.gemini_call(PROMPT + "\n".join(lines), 6000)
    try: th = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))["themes"]
    except Exception as e: OUT["jobs"][job] = {"error": str(e)[:100], "n_commenters": len(code)}; continue
    T = [{"kind": t["kind"], "theme": re.sub(r"@\w+", "", t["theme"]), "n_commenters": len(set(t.get("commenters", [])) & set(code.values())), "products": sorted(set(t.get("products", [])))} for t in th]
    OUT["jobs"][job] = {"products": [name.get(s, s) for s in slugs if raw[s]], "n_commenters": len(code), "n_comments": len(lines), "themes": sorted([t for t in T if t["n_commenters"]], key=lambda t: -t["n_commenters"])}
OUT["usd"] = round(llm.USAGE["in"] / 1e6 * .3 + llm.USAGE["out"] / 1e6 * 2.5, 3)
json.dump(OUT, open(f"{SP}/comp/comment_themes.json", "w"), indent=1)
print(json.dumps(OUT["coverage"])); print(OUT["usd"])
for j, v in OUT["jobs"].items():
    print("#####", j, v.get("products"), v.get("n_commenters"), v.get("n_comments"), v.get("error"))
    for t in v.get("themes", []): print(f"  {t['n_commenters']:>2} {t['kind']:<10} {t['theme']} {t['products']}")
