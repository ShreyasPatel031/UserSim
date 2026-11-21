"""SENTIMENT (PREREG.md addendum): predicted say items vs real non-maker comments, per launch. Aggregates only.
Labels: Gemini 2.5 Flash, temperature 0, one call per launch per side (predicted / real), items shuffled, the model is not told which side it is.
    python sentiment.py <backtest_v1 dir> <scratchpad> <out json>"""
import concurrent.futures as cf, json, os, random, re, sys
import numpy as np, pandas as pd
D_, SP, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
CM = {r["launch_id"]: r for r in map(json.loads, open(f"{D_}/comments.jsonl"))}
PR = {r["launch_id"]: r for r in map(json.loads, open(f"{D_}/predictions.jsonl")) if r.get("explain") and (r["explain"].get("written_before_reveal") is not False)}
SCRUB = lambda t: re.sub(r"\s+", " ", re.sub(r"@\w+", "@user", str(t)))[:300]
PROMPT = """Label the sentiment of each short Product Hunt-style comment toward the product it is about: "pos", "neu" or "neg".
Questions asked neutrally are "neu"; concerns, doubts or complaints are "neg"; praise or excitement is "pos". JSON only: {{"labels": ["pos"|"neu"|"neg", ...]}} in order.
{items}"""
def label(items):
    items = [SCRUB(x) for x in items][:40]
    if not items: return []
    txt = llm.gemini_call(PROMPT.format(items="\n".join(f"{i+1}. {x}" for i, x in enumerate(items))), 1200)
    try: L = json.loads(txt)["labels"]; return [x for x in L if x in ("pos", "neu", "neg")][:len(items)]
    except Exception: return []
def pred_items(e):
    s = e.get("say") or {}; out = []
    for k in ("reactions", "top_concerns", "top_questions"):
        if isinstance(s.get(k), list): out += s[k]
    pp = e.get("persona_panel") or s.get("persona_panel") or {}
    for it in (pp.get("items") or [] if isinstance(pp, dict) else []):
        for k in ("reaction", "concern"):
            if it.get(k): out.append(it[k])
    return out
def one(lid):
    c = [x["text"] for x in CM.get(lid, {}).get("comments", []) if not x.get("is_maker") and x.get("text")]
    if len(c) < 5: return lid, None
    random.Random(int(lid)).shuffle(c); p = pred_items(PR[lid]["explain"])
    return lid, {"day": PR[lid]["day"], "real": label(c[:40]), "pred": label(p)}
with cf.ThreadPoolExecutor(6) as ex: RES = {k: v for k, v in ex.map(one, list(PR)) if v and v["real"] and v["pred"]}
dist = lambda L: np.array([L.count(k) for k in ("pos", "neu", "neg")], float) / max(len(L), 1)
def jsd(a, b):
    m = (a + b) / 2; kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
rows = []
days = sorted({v["day"] for v in RES.values()})
for lid, v in RES.items():
    earlier = [l for k, w in RES.items() if w["day"] < v["day"] for l in w["real"]]
    r_, p_ = dist(v["real"]), dist(v["pred"])
    row = {"day": v["day"], "launch_id": lid, "n_real": len(v["real"]), "n_pred": len(v["pred"]), "jsd_pred": jsd(p_, r_), "agree_majority": int(np.argmax(p_) == np.argmax(r_)),
           "real_pos": r_[0], "real_neg": r_[2], "pred_pos": p_[0], "pred_neg": p_[2]}
    if len(earlier) >= 50: b_ = dist(earlier); row.update({"jsd_base": jsd(b_, r_), "agree_base": int(np.argmax(b_) == np.argmax(r_))})
    rows.append(row)
R = pd.DataFrame(rows)
def boot(col, df):
    df = df.dropna(subset=[col]); d = sorted(df.day.unique())
    bs = [pd.concat([df[df.day == x] for x in rng.choice(d, len(d))])[col].mean() for _ in range(2000)]
    return [round(float(df[col].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(df)), len(d)]
S = R.dropna(subset=["jsd_base"]).copy(); S["d"] = S.jsd_pred - S.jsd_base
usd = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
out = {"prereg": "PREREG.md addendum (commit 141daf5d)", "launches": int(len(R)), "days": days, "usd": usd,
       "jsd predicted vs real": boot("jsd_pred", R), "majority agreement predicted": boot("agree_majority", R),
       "with baseline (launches whose earlier days hold >= 50 labelled comments)": {"jsd predicted": boot("jsd_pred", S), "jsd base": boot("jsd_base", S), "predicted minus base (paired)": boot("d", S),
                                                                                  "agreement predicted": boot("agree_majority", S), "agreement base": boot("agree_base", S)},
       "mean shares": {"real pos/neg": [round(R.real_pos.mean(), 3), round(R.real_neg.mean(), 3)], "predicted pos/neg": [round(R.pred_pos.mean(), 3), round(R.pred_neg.mean(), 3)]},
       "per_segment": "not scored in v1: comments.jsonl carries no commenter-to-person link (by design, no usernames); needs the matched-commenter join on the private side",
       "note": "[mean, day-bootstrap 2.5%, 97.5%, launches, days]. Explain days Nov 15-20 only (Nov 14 written after the reveal, excluded)."}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spend.jsonl"), "a").write(json.dumps({"t": "cohort_sentiment_backtest", "provider": "gcp", "usd": usd, "note": f"{len(R)} launches x 2 Gemini 2.5 Flash calls"}) + "\n")
