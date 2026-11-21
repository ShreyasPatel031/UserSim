"""PREREG addendum 2, sentiment re-weight. Labels (Gemini 2.5 Flash, as sentiment.py) for real comments on all backtest_v1 days and predicted say on Nov 15-20.
r = real mean share (days < test day, all earlier labelled launches) / predicted mean share (other explain days, leave-one-day-out: no pre-Nov 15 predictions exist).
    python sentiment_tune.py <backtest_v1 dir> <scratchpad> <out json>"""
import concurrent.futures as cf, json, os, random, sys
import numpy as np, pandas as pd
sys.argv = [sys.argv[0], *sys.argv[1:]]; D_, SP, OUT = sys.argv[1:4]
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import importlib.util
spec = importlib.util.spec_from_file_location("S0", os.path.join(HERE, "sentiment.py"))
src = open(os.path.join(HERE, "sentiment.py")).read().split("with cf.ThreadPoolExecutor")[0]
G = {"__file__": os.path.join(HERE, "sentiment.py")}; sys.argv = ["x", D_, SP, OUT]; exec(src, G)
CM, PR, label, pred_items, llm = G["CM"], G["PR"], G["label"], G["pred_items"], G["llm"]
DAY = {r["launch_id"]: r["day"] for r in map(json.loads, open(f"{D_}/launches.jsonl"))}
CACHE = os.path.join(SP, "sent_labels.json"); lab = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
def real(lid):
    c = [x["text"] for x in CM.get(lid, {}).get("comments", []) if not x.get("is_maker") and x.get("text")]
    if len(c) < 5: return lid, None
    random.Random(int(lid)).shuffle(c); return lid, label(c[:40])
todo = [l for l in CM if "r" + l not in lab]
with cf.ThreadPoolExecutor(6) as ex:
    for l, v in ex.map(real, todo): lab["r" + l] = v
with cf.ThreadPoolExecutor(6) as ex:
    for l, v in ex.map(lambda l: (l, label(pred_items(PR[l]["explain"]))), [l for l in PR if "p" + l not in lab]): lab["p" + l] = v
json.dump(lab, open(CACHE, "w"))
dist = lambda L: np.array([L.count(k) for k in ("pos", "neu", "neg")], float) / max(len(L), 1)
def jsd(a, b):
    a = a / a.sum(); b = b / b.sum(); m = (a + b) / 2; kl = lambda x, y: np.sum(np.where(x > 0, x * np.log2(np.where(x > 0, x, 1) / np.where(y > 0, y, 1)), 0)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
REAL = {l[1:]: dist(v) for l, v in lab.items() if l[0] == "r" and v}; PRED = {l[1:]: dist(v) for l, v in lab.items() if l[0] == "p" and v}
rows = []
for l in PRED:
    if l not in REAL: continue
    D = PR[l]["day"]; er = [REAL[k] for k in REAL if DAY.get(k, "9") < D]; op = [PRED[k] for k in PRED if PR[k]["day"] != D]
    if len(er) < 20: continue
    r = np.mean(er, 0) / np.maximum(np.mean(op, 0), 1e-3); adj = PRED[l] * r; adj = adj / adj.sum() if adj.sum() else np.mean(er, 0)
    rows.append({"day": D, "raw": jsd(PRED[l] + 1e-9, REAL[l]), "adj": jsd(adj + 1e-9, REAL[l]), "base": jsd(np.mean(er, 0), REAL[l]),
                 "agree_raw": int(np.argmax(PRED[l]) == np.argmax(REAL[l])), "agree_adj": int(np.argmax(adj) == np.argmax(REAL[l])), "pos_adj": adj[0], "pos_real": REAL[l][0], "pos_raw": PRED[l][0]})
R = pd.DataFrame(rows); R["d_raw"] = R.adj - R.raw; R["d_base"] = R.adj - R.base; rng = np.random.default_rng(0)
def boot(c):
    d = sorted(R.day.unique()); bs = [pd.concat([R[R.day == x] for x in rng.choice(d, len(d))])[c].mean() for _ in range(2000)]
    return [round(float(R[c].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(R)), len(d)]
usd = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
out = {"prereg": "PREREG.md addendum 2", "usd": usd, "real_launches_labelled": len(REAL), "jsd raw": boot("raw"), "jsd adjusted": boot("adj"), "jsd base (earlier real mix)": boot("base"),
       "adjusted minus raw": boot("d_raw"), "adjusted minus base": boot("d_base"), "agree raw": boot("agree_raw"), "agree adjusted": boot("agree_adj"),
       "pos share raw/adj/real": [round(R.pos_raw.mean(), 3), round(R.pos_adj.mean(), 3), round(R.pos_real.mean(), 3)],
       "pass (adjusted minus raw upper < 0)": bool(boot("d_raw")[2] < 0), "note": "[mean, day-boot 2.5%, 97.5%, launches, days]; r uses leave-one-day-out predicted shares (no pre-Nov 15 predictions)"}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": "cohort_sentiment_tune", "provider": "gcp", "usd": usd}) + "\n")
