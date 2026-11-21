"""HOW (trace realism) scorecard v1: simulated plugin traces vs real human computer-use traces.

Human: AgentNet/OpenCUA ubuntu 5k (MIT; action mix, step counts) and VideoCUA (MIT; ms-timestamped actions).
Sim:   Atelier Sim plugin runs (run JSON per simulated user + the run's stream.jsonl for per-step wall-clock).
Metrics (bootstrap 95% CI over traces):
  action_mix_js      Jensen-Shannon distance (sqrt of JS divergence, base 2) between action-type mixes. Target <= 0.10
  step_timing_ks     KS statistic of inter-action seconds, sim vs VideoCUA.                           Target <= 0.15
  giveup_gap_pts     sim give-up rate minus human rate, percentage points.                             Target |gap| <= 5
  classifier_auc     logistic regression human-vs-sim on per-trace features, 5-fold CV by trace.     Target <= 0.65
Usage: python how_scorecard.py <sim_runs_dir>[,<more>] <agentnet.jsonl> <videocua_dir> <out.json>
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy.stats import ks_2samp
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

VOCAB = ["click", "type", "key", "scroll", "drag", "wait", "navigate", "other"]
RNG = np.random.default_rng(7)


def norm(kind: str) -> str:
    k = (kind or "").lower()
    if k in ("click", "double_click", "right_click", "doubleclick", "rightclick", "triple_click", "tripleclick"):
        return "click"
    if k in ("type", "write", "typewrite", "typing"):
        return "type"
    if k in ("key", "press", "hotkey", "keydown", "keyup"):
        return "key"
    if k in ("scroll", "hscroll", "vscroll"):
        return "scroll"
    if k in ("drag", "dragto", "drag_to", "mousedown", "mouseup"):
        return "drag"
    if k in ("wait", "sleep"):
        return "wait"
    if k in ("navigate", "goto", "reload", "back"):
        return "navigate"
    return "other"


# ---------------- sim ----------------
def sim_traces(dirs):
    out = []
    for runs_dir in dirs:
        for d in sorted(glob.glob(os.path.join(runs_dir, "*"))):
            secs = defaultdict(dict)  # session_id -> {step: seconds_left}
            study_of = {}  # study_id -> session_id
            sp = os.path.join(d, "stream.jsonl")
            if os.path.exists(sp):
                for line in open(sp):
                    line = line.replace('\\"', '"')
                    for m in re.finditer(r'"session_id": "([0-9a-f]{32})", "step": (\d+).{0,4000}?"seconds_left": (\d+)', line):
                        secs[m.group(1)][int(m.group(2))] = int(m.group(3))
                    for m in re.finditer(r'"session_id": "([0-9a-f]{32})".{0,2000}?study=([0-9a-f-]{36})', line):
                        study_of.setdefault(m.group(2), m.group(1))
            for f in sorted(glob.glob(os.path.join(d, ".atelier-sim", "*", "*.json"))):
                try:
                    r = json.load(open(f))
                except ValueError:
                    continue
                acts, hs = [], []
                for s in r.get("steps") or []:
                    if isinstance(s.get("human_s"), (int, float)) and 0 <= s["human_s"] < 600:
                        hs.append(float(s["human_s"]))
                    a = s.get("action")
                    if isinstance(a, str) and a.startswith("{"):
                        try:
                            a = json.loads(a)
                        except ValueError:
                            a = {}
                    kind = a.get("type") if isinstance(a, dict) else str(a or "")
                    acts.append(norm(kind))
                mw = re.search(r"study=([0-9a-f-]{36})", r.get("watch_url") or "") or re.search(r"([0-9a-f-]{36})", r.get("study_id") or "")
                best = secs.get(study_of.get(mw.group(1)) if mw else "", {})
                dts = []
                steps = sorted(best)
                for a, b in zip(steps, steps[1:]):
                    dt = best[a] - best[b]
                    if 0 <= dt < 600:
                        dts.append(float(dt))
                timing_src = "wallclock"
                if len(hs) >= max(2, len(acts) // 2):
                    dts, timing_src = hs[1:], "human_s"
                out.append({"src": "sim", "id": f, "acts": acts, "dts": dts, "timing_src": timing_src,
                            "outcome": r.get("outcome"), "task": (r.get("task") or "")[:80]})
    return out


# ---------------- human ----------------
def agentnet_traces(path, limit=1500):
    out = []
    for i, line in enumerate(open(path)):
        if i >= limit:
            break
        d = json.loads(line)
        acts = []
        for st in d.get("traj") or []:
            code = ((st.get("value") or {}).get("code") or "")
            for m in re.finditer(r"pyautogui\.(\w+)|computer\.(\w+)", code):
                k = (m.group(1) or m.group(2) or "").lower()
                if k in ("moveto", "move", "position"):
                    continue
                if k in ("terminate",):
                    continue
                acts.append(norm(k))
        if acts:
            out.append({"src": "agentnet", "id": d.get("task_id"), "acts": acts, "dts": [],
                        "completed": bool(d.get("task_completed")), "domain": d.get("domain")})
    return out


def videocua_traces(root):
    out = []
    for f in sorted(glob.glob(os.path.join(root, "*", "action_log.json"))):
        d = json.load(open(f))
        evs = [e for e in d.get("action_log") or [] if (e.get("action_type") or "").upper() not in ("MOVE_TO", "MOUSE_MOVE")]
        acts = [norm(e.get("action_type")) for e in evs]
        ts = [float(e.get("timestamp") or 0) for e in evs]
        dts = [b - a for a, b in zip(ts, ts[1:]) if 0 <= b - a < 600]
        if acts:
            out.append({"src": "videocua", "id": str(d.get("task_id")), "acts": acts, "dts": dts, "app": d.get("platform")})
    return out


def opera_traces(root):
    import pandas as pd
    files = glob.glob(os.path.join(root, "*.parquet"))
    d = pd.concat([pd.read_parquet(f, columns=["session_id", "timestamp", "action_type", "click_type"]) for f in files])
    d["t"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    out = []
    for sid, g in d.sort_values("t").groupby("session_id"):
        kinds = g["action_type"].tolist()
        acts = [norm({"input": "type"}.get(k, k)) for k in kinds if k != "terminate"]
        ts = [x.timestamp() for x, k in zip(g["t"], kinds) if k != "terminate" and x == x]
        dts = [b - a for a, b in zip(ts, ts[1:]) if 0 <= b - a < 600]
        bought = bool((g["click_type"] == "purchase").any())
        if acts:
            out.append({"src": "opera", "id": sid, "acts": acts, "dts": dts, "gave_up": not bought})
    return out


# ---------------- metrics ----------------
def mix(traces):
    c = Counter(a for t in traces for a in t["acts"])
    v = np.array([c[k] for k in VOCAB], float) + 1e-9
    return v / v.sum()


def js_distance(p, q):
    m = (p + q) / 2
    kl = lambda x, y: float(np.sum(x * np.log2(x / y)))
    return float(np.sqrt(0.5 * kl(p, m) + 0.5 * kl(q, m)))


def boot(fn, a, b, n=1000):
    vals = []
    for _ in range(n):
        aa = [a[i] for i in RNG.integers(0, len(a), len(a))]
        bb = [b[i] for i in RNG.integers(0, len(b), len(b))]
        try:
            vals.append(fn(aa, bb))
        except Exception:  # noqa: BLE001
            pass
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)] if vals else None


def feats(t):
    n = len(t["acts"])
    m = Counter(t["acts"])
    rep = sum(1 for a, b in zip(t["acts"], t["acts"][1:]) if a == b) / max(1, n - 1)
    return [np.log1p(n), rep] + [m[k] / n for k in VOCAB]


def score(sim, an, vc, op):
    human = an + vc + op
    res = {"n": {"sim": len(sim), "agentnet": len(an), "videocua": len(vc), "opera": len(op)}}
    res["action_mix"] = {
        "sim": dict(zip(VOCAB, np.round(mix(sim), 3).tolist())),
        "human_pooled": dict(zip(VOCAB, np.round(mix(human), 3).tolist())),
        "js_vs_pooled": round(js_distance(mix(sim), mix(human)), 4),
        "js_vs_pooled_ci95": boot(lambda a, b: js_distance(mix(a), mix(b)), sim, human, 400),
        "js_vs_opera_web": round(js_distance(mix(sim), mix(op)), 4),
        "js_vs_opera_web_ci95": boot(lambda a, b: js_distance(mix(a), mix(b)), sim, op, 400),
        "js_vs_agentnet": round(js_distance(mix(sim), mix(an)), 4),
        "js_vs_videocua": round(js_distance(mix(sim), mix(vc)), 4), "target": 0.10}
    th = vc + op
    sd = [x for t in sim for x in t["dts"]]
    hd = [x for t in th for x in t["dts"]]
    st = [t for t in sim if t["dts"]]
    res["step_timing"] = {
        "ks": round(float(ks_2samp(sd, hd).statistic), 4) if sd else None,
        "ks_ci95": boot(lambda a, b: ks_2samp([x for t in a for x in t["dts"]], [x for t in b for x in t["dts"]]).statistic, st, th, 300) if sd else None,
        "ks_vs_opera_web": round(float(ks_2samp(sd, [x for t in op for x in t["dts"]]).statistic), 4) if sd else None,
        "sim_median_s": round(float(np.median(sd)), 2) if sd else None, "human_median_s": round(float(np.median(hd)), 2),
        "sim_timing_source": dict(Counter(t.get("timing_src") for t in sim)), "target": 0.15}
    s_ok = [t for t in sim if t["outcome"] in ("completed", "gave_up")]
    s_rate = sum(t["outcome"] == "gave_up" for t in s_ok) / max(1, len(s_ok))
    h_rate = sum(t["gave_up"] for t in op) / max(1, len(op))
    res["giveup"] = {
        "sim_rate": round(s_rate, 3), "sim_n": len(s_ok), "sim_blocked_excluded": sum(t["outcome"] == "blocked" for t in sim),
        "human_rate_opera": round(h_rate, 3), "human_n": len(op), "gap_pts": round(100 * (s_rate - h_rate), 1),
        "gap_ci95_pts": boot(lambda a, b: 100 * (sum(t["outcome"] == "gave_up" for t in a) / max(1, len(a))
                                                - sum(t["gave_up"] for t in b) / max(1, len(b))), s_ok, op, 1000),
        "target_abs_pts": 5,
        "caveat": "human = OPeRA real shopper sessions ending without a purchase (natural abandonment, shopping intent); "
                  "sim blocked runs (test limits) excluded"}
    X = np.array([feats(t) for t in sim + human])
    y = np.array([1] * len(sim) + [0] * len(human))
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced"))
    p = cross_val_predict(clf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=7), method="predict_proba")[:, 1]
    aucs = []
    for _ in range(500):
        idx = RNG.integers(0, len(y), len(y))
        if len(set(y[idx])) == 2:
            aucs.append(roc_auc_score(y[idx], p[idx]))
    res["classifier"] = {"auc": round(float(roc_auc_score(y, p)), 4),
                         "auc_ci95": [round(float(np.percentile(aucs, 2.5)), 4), round(float(np.percentile(aucs, 97.5)), 4)],
                         "split": "one row per trace, stratified 5-fold, no task shared between sets", "target": 0.65}
    res["pass"] = {"action_mix": res["action_mix"]["js_vs_pooled"] <= 0.10,
                   "step_timing": (res["step_timing"]["ks"] or 1) <= 0.15,
                   "giveup": abs(res["giveup"]["gap_pts"]) <= 5, "classifier": res["classifier"]["auc"] <= 0.65}
    return res


def main():
    # usage: how_scorecard.py name=dir1[,dir2] [name=dir ...] --agentnet F --videocua D --opera D --out F
    args = sys.argv[1:]
    kv = dict(zip(args[args.index("--agentnet")::2], args[args.index("--agentnet") + 1::2]))
    sets = [a for a in args[:args.index("--agentnet")]]
    an, vc, op = agentnet_traces(kv["--agentnet"]), videocua_traces(kv["--videocua"]), opera_traces(kv["--opera"])
    res = {"version": "how_scorecard_v2", "human_sets": {"agentnet": "ubuntu 5k, first 1500 (MIT)",
           "videocua": "140 tasks, 8 smallest apps (MIT)", "opera": "527 real web shopper sessions (CC BY 4.0)"}, "sim": {}}
    for spec in sets:
        name, dirs = spec.split("=", 1)
        res["sim"][name] = score(sim_traces(dirs.split(",")), an, vc, op)
    json.dump(res, open(kv["--out"], "w"), indent=1)
    for name, r in res["sim"].items():
        print(name, json.dumps({"n": r["n"]["sim"], "js": [r["action_mix"]["js_vs_pooled"], r["action_mix"]["js_vs_pooled_ci95"]],
              "js_web": r["action_mix"]["js_vs_opera_web"], "ks": [r["step_timing"]["ks"], r["step_timing"]["ks_ci95"]],
              "giveup_gap": [r["giveup"]["gap_pts"], r["giveup"]["gap_ci95_pts"]], "auc": [r["classifier"]["auc"], r["classifier"]["auc_ci95"]],
              "timing_src": r["step_timing"]["sim_timing_source"]}))


if __name__ == "__main__":
    main()
