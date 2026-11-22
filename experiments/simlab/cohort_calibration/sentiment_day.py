"""Daily sentiment line (reactions only, orchestrator 10:30Z Nov 21): predicted say.reactions in the frozen explain file vs the day's real non-maker
comments (results/calibration/<day>/truth.json), with the earlier-days real mix (cached labels, days < D) as the published base line.
    python sentiment_day.py <day> <scratchpad> <truth.json> <out json>"""
import concurrent.futures as cf, json, os, random, subprocess, sys
import numpy as np
D, SP, TR, OUT = sys.argv[1:5]; HERE = os.path.dirname(os.path.abspath(__file__))
G = {"__file__": os.path.join(HERE, "sentiment.py")}; BT = os.path.join(SP, "bt1"); sys.argv = ["x", BT, SP, OUT]
exec(open(os.path.join(HERE, "sentiment.py")).read().split("with cf.ThreadPoolExecutor")[0], G); label, llm = G["label"], G["llm"]
DAY = {r["launch_id"]: r["day"] for r in map(json.loads, open(f"{BT}/launches.jsonl"))}
lab = json.load(open(os.path.join(SP, "sent_labels.json")))
dist = lambda L: np.array([L.count(k) for k in ("pos", "neu", "neg")], float) / max(len(L), 1)
def jsd(a, b):
    a = a + 1e-12; b = b + 1e-12; a, b = a / a.sum(), b / b.sum(); m = (a + b) / 2; kl = lambda x, y: np.sum(x * np.log2(x / y)); return float(np.sqrt(max(0.5 * kl(a, m) + 0.5 * kl(b, m), 0)))
base = np.mean([dist(v) for k, v in lab.items() if k[0] == "r" and v and DAY.get(k[1:], "9") < D], 0)
T = json.load(open(TR))["by_launch"]
EX = json.loads(subprocess.run(["gsutil", "cat", f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/explain/{D}.json"], capture_output=True, text=True).stdout or "{}").get("launches", {})
def one(l):
    c = [x["text"] for x in T[l].get("comments", []) if not x.get("is_maker") and x.get("text")]
    rx = [x for x in ((EX.get(l) or {}).get("say") or {}).get("reactions") or [] if isinstance(x, str)]
    if len(c) < 5 or not rx: return l, None
    random.Random(int(l)).shuffle(c); return l, (label(c[:40]), label(rx))
with cf.ThreadPoolExecutor(6) as ex: R = {l: v for l, v in ex.map(one, list(T)) if v and v[0] and v[1]}
rows = [{"jsd_rx": jsd(dist(p), dist(r)), "jsd_base": jsd(base, dist(r)), "agree_rx": int(np.argmax(dist(p)) == np.argmax(dist(r))), "agree_base": int(np.argmax(base) == np.argmax(dist(r))), "pos_rx": dist(p)[0], "pos_real": dist(r)[0]} for r, p in R.values()]
m = lambda k: round(float(np.mean([x[k] for x in rows])), 3) if rows else None
d = np.array([x["jsd_rx"] - x["jsd_base"] for x in rows]); rng = np.random.default_rng(0)
ci = [round(float(d.mean()), 3)] + [round(float(np.percentile([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)], q)), 3) for q in (2.5, 97.5)] if len(d) > 1 else None
out = {"day": D, "launches": len(rows), "base mix (earlier real labels)": [round(float(x), 3) for x in base], "jsd reactions": m("jsd_rx"), "jsd base (published line)": m("jsd_base"),
       "reactions minus base [mean, launch-boot 95%]": ci, "agree reactions / base": [m("agree_rx"), m("agree_base")], "pos share reactions / real": [m("pos_rx"), m("pos_real")],
       "sources not scorable today": {"(a) ~20 P3-persona reactions": "not generated in the nightly yet", "(b) plugin in-product feedback": "plugin_runs/2026-11-21_personas.json holds outcomes only (gave_up/blocked/...), no feedback text"},
       "usd": round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)}
json.dump(out, open(OUT, "w"), indent=1); print(json.dumps(out, indent=1))
