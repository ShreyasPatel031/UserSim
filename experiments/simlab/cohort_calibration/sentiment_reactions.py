"""Sentiment of predicted REACTIONS only (say.reactions; the concerns/questions lists are critical/neutral by construction) vs real comments,
Nov 15-20, out of sample; compared with raw all-items and with the earlier-days real mix (cached labels from sentiment_tune.py).
    python sentiment_reactions.py <backtest_v1 dir> <scratchpad> <out json>"""
import concurrent.futures as cf, json, os, sys
import numpy as np, pandas as pd
D_, SP, OUT = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
G = {"__file__": os.path.join(HERE, "sentiment.py")}; sys.argv = ["x", D_, SP, OUT]
exec(open(os.path.join(HERE, "sentiment.py")).read().split("with cf.ThreadPoolExecutor")[0], G)
PR, label, llm = G["PR"], G["label"], G["llm"]
DAY = {r["launch_id"]: r["day"] for r in map(json.loads, open(f"{D_}/launches.jsonl"))}
lab = json.load(open(os.path.join(SP, "sent_labels.json")))
rx = lambda e: [x for x in ((e.get("say") or {}).get("reactions") or []) if isinstance(x, str)]
RXC = os.path.join(SP, "sent_labels_rx.json")
if os.path.exists(RXC): RX = json.load(open(RXC))
else:
    with cf.ThreadPoolExecutor(6) as ex: RX = dict(ex.map(lambda l: (l, label(rx(PR[l]["explain"]))), list(PR)))
    json.dump(RX, open(RXC, "w"))
dist = lambda L: np.array([L.count(k) for k in ("pos", "neu", "neg")], float) / max(len(L), 1)
def jsd(a, b):
    a = a + 1e-12; b = b + 1e-12; a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2; kl = lambda x, y: np.sum(x * np.log2(x / y)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
REAL = {l[1:]: dist(v) for l, v in lab.items() if l[0] == "r" and v}; rows = []
for l, v in RX.items():
    if not v or l not in REAL or not lab.get("p" + l): continue
    D = PR[l]["day"]; er = [REAL[k] for k in REAL if DAY.get(k, "9") < D]
    if len(er) < 20: continue
    b = np.mean(er, 0); p = dist(v); a = dist(lab["p" + l]); r = REAL[l]; n = len(v)
    rows.append({"n": n, "p": p, "b": b, "r": r, "day": D, "rx": jsd(p, r), "all": jsd(a, r), "base": jsd(b, r), "agree_rx": int(np.argmax(p) == np.argmax(r)), "agree_base": int(np.argmax(b) == np.argmax(r)), "pos_rx": p[0], "pos_real": r[0], "neg_rx": p[2], "neg_real": r[2]})
R = pd.DataFrame(rows)
# shrinkage toward the earlier-days real mix: (n*p + k*b)/(n+k); k chosen leave-one-day-out on a grid (the other test days only)
K = [0, 1, 2, 4, 8, 16, 32, 64]; sh = lambda x, k: jsd((x.n * x.p + k * x.b) / (x.n + k), x.r)
KS = {}
for d in R.day.unique():
    o = R[R.day != d]; KS[d] = K[int(np.argmin([np.mean([sh(x, k) for x in o.itertuples()]) for k in K]))]
R["shr"] = [sh(x, KS[x.day]) for x in R.itertuples()]; R["d_shr_base"] = R.shr - R.base; R["d_shr_all"] = R.shr - R["all"]
R["d_all"] = R.rx - R["all"]; R["d_base"] = R.rx - R.base; rng = np.random.default_rng(0)
def boot(c):
    d = sorted(R.day.unique()); bs = [pd.concat([R[R.day == x] for x in rng.choice(d, len(d))])[c].mean() for _ in range(2000)]
    return [round(float(R[c].mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(R)), len(d)]
usd = round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
out = {"usd": usd, "jsd reactions only": boot("rx"), "jsd all say items": boot("all"), "jsd base (earlier real mix)": boot("base"), "reactions minus all": boot("d_all"),
       "reactions minus base": boot("d_base"), "jsd reactions shrunk to earlier mix (k leave-one-day-out)": boot("shr"), "shrunk minus base": boot("d_shr_base"), "shrunk minus all items (raw)": boot("d_shr_all"), "k by held-out day": KS,
       "agree reactions": boot("agree_rx"), "agree base": boot("agree_base"),
       "pos/neg reactions": [round(R.pos_rx.mean(), 3), round(R.neg_rx.mean(), 3)], "pos/neg real": [round(R.pos_real.mean(), 3), round(R.neg_real.mean(), 3)]}
json.dump(out, open(OUT, "w"), indent=1, default=int); print(json.dumps(out, indent=1))
open(os.path.join(os.path.dirname(HERE), "spend.jsonl"), "a").write(json.dumps({"t": "cohort_sentiment_reactions", "provider": "gcp", "usd": usd}) + "\n")
