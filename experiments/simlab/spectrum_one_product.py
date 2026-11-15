"""One-product spectrum panel + likely commenters (user ask 19:50Z Nov 15)."""
import json, os, subprocess, sys
import numpy as np, pandas as pd
SP, D, LID = sys.argv[1:4]; HERE = "/home/user/UserSim/experiments/simlab"; sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm, segments_lib  # noqa
B = "gs://usersim-bakeoff-347838016394/usersim_sim"; gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
lab, prof = segments_lib.load(SP); J = json.loads(gcat(f"{B}/results/web/segments/latest.json"))
X = json.load(open(f"{SP}/segments/expected_sub_{D}.json")); t = X["launches"][LID]; bs = X["base_share"]; tot = t["tracked_total"]
LEAF = [l for l, v in prof.items() if "subgroup_size" in v] + [l for l, v in prof.items() if "subgroup_size" not in v and not any(k.startswith(l + " / ") for k in prof)]
interest = lambda L: "high" if L >= 1.5 else ("medium" if L >= 0.67 else "low")
rows = []
for l in LEAF:
    e = float(t["groups"].get(l, 0.0)); sh = e / tot if tot else 0; b = float(bs.get(l, 0)); L = sh / b if b else 0
    rows.append({"segment": l, "n_people": prof[l].get("subgroup_size") or prof[l]["group_size"], "expected_voters": round(e, 1), "share": round(sh, 3),
                 "base_share": round(b, 3), "lift": round(L, 2), "interest": interest(L), "segment_profile": prof[l],
                 "median_upvotes_last_30_days": 0, "topic_shares": [], "products_they_commonly_upvoted": []})
rows.sort(key=lambda r: -r["lift"])
p = {str(x["id"]): x for x in json.loads(gcat(f"{B}/raw/daily/{D}/today_0005.json"))}[LID]
import importlib.util as u; s_ = u.spec_from_file_location("pp", f"{HERE}/persona_prompt.py"); pm = u.module_from_spec(s_); s_.loader.exec_module(pm)
topics = ", ".join(e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or []))
txt = llm.gemini_call(pm.PROMPT.format(name=p["name"], tagline=p.get("tagline"), desc=(p.get("description") or "")[:1200], topics=topics,
                      groups="\n".join(pm.gtxt(i, g) for i, g in enumerate(rows))), max(3000, 300 * len(rows)))
R = {int(r["group"]) - 1: r for r in json.loads(txt)["reactions"]}
for i, r in enumerate(rows): r.update({k: (R.get(i) or {}).get(k) for k in ("reaction", "concern", "question")})
# likely commenters: P(comment) = recalibrated P(vote) x person's own past comment-per-upvote rate (launch days before D, smoothed)
F = pd.read_parquet(f"{SP}/bp/backer_arms_{D}.parquet"); F = F[(F.arm == "CF-only") & (F.launch_id.astype(str) == LID)][["person_id", "p"]]
E = pd.read_parquet(f"{SP}/store_live/events.parquet", columns=["person_id", "kind"]); E = E[E.person_id.isin(set(F.person_id))]
n = E.groupby(["person_id", "kind"]).size().unstack(fill_value=0); cm = n.get("comment", 0); up = n.get("upvote", 0)
F["comment_rate"] = F.person_id.map((cm + 0.05 * 10) / (up + 10)).fillna(0.05); F["p_comment"] = F.p * F.comment_rate
F["unit"] = F.person_id.map(lab); F = F.sort_values("p_comment", ascending=False)
top = F.head(15).assign(person=[f"person #{i + 1}" for i in range(15)])
out = {"launch": {"name": p["name"], "tagline": p.get("tagline"), "topics": topics}, "expected_voters_tracked": round(tot, 1),
       "panel": [{k: v for k, v in r.items() if k not in ("segment_profile", "median_upvotes_last_30_days", "topic_shares", "products_they_commonly_upvoted")} for r in rows],
       "likely_commenters": [{"person": a, "unit": b, "p_vote": round(c, 3), "past_comments_per_upvote": round(d, 3), "p_comment": round(e, 4)}
                             for a, b, c, d, e in zip(top.person, top.unit, top.p, top.comment_rate, top.p_comment)],
       "expected_commenters_tracked": round(float(F.p_comment.sum()), 1), "usd": round(llm.USAGE["in"] / 1e6 * 0.3 + llm.USAGE["out"] / 1e6 * 2.5, 4)}
json.dump(out, open(f"{SP}/one_product_{LID}.json", "w"), indent=1); print(json.dumps(out, indent=1))
