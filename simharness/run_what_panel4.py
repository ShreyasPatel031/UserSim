"""WHAT-PANEL-4: does the deployed "persona panel + 15 person-built comments" keep its WHAT gain over the persona panel
alone on more days?

The person-built comments are made exactly as the deployed nightly job makes them (E5's person_panel.py):
  * the reference selection: run_what_panel build (30 held people per launch);
  * a draw of 15, in the order of a permutation seeded by md5(launch id + day);
  * one gemini-2.5-flash call each at temperature 0.7, with FT_PROMPT's last sentence replaced by the privacy line
    and the JSON instruction;
  * the privacy guard: drop maker-like, self-named or own-history-product comments and take the next person.
Scoring uses E5's frozen consensus truth (truth_<D>.v1.json) and the JUDGE / CJ prompts (reactions_eval.py,
complaints_eval.py). Each arm gets 3 judge runs per launch, and their mean is the launch value. Arms:
  * panel       : the persona panel items from results/web/explain/<D>.json;
  * panel + 15  : those items followed by the 15 person-built comments (merged as the deployed forward_says.py merges).

  python -m simharness.run_what_panel4 gen   --day D --prompts DIR --explain EX.json --lineup L.json --fs FS.json --truth T.json --out OUT
  python -m simharness.run_what_panel4 score --days D1 D2 ... --work OUT --judge-src SIMLAB_DIR --out RES.json

OUT holds simulated text built on private histories: private.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request

import numpy as np

URL = ("https://aiplatform.googleapis.com/v1/projects/{p}/locations/global/publishers/google/models/gemini-2.5-flash:"
       "generateContent")
USAGE = {"in": 0, "out": 0}
_lk = threading.Lock()
_tok = {"t": "", "at": 0.0}

OLD = ("This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\n"
       "kind of question or praise, as their past comments show. Reply with the comment only.")
NEW = ("This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\n"
       "kind of question or praise, as their past comments show. Do not mention your own name, employer or products. "
       "Answer in JSON only: {\"comment\": \"...\"}")
MAKER = re.compile(r"\b(we built|we('| a)re (excited|thrilled|launching)|our (team|launch|product)|thanks for (the )?(support|hunting)|"
                   r"i built|we launched|hunting us|my (startup|company|product)|co-?founder|founder of|maker of|(hey|hi|hello) product hunt|"
                   r"i'?m \w+,? (the )?(co-?founder|founder|maker|ceo|cto)|we('ve| have) (built|been building)|our (users|customers|app|tool|platform))\b", re.I)
SELFNAME = re.compile(r"\b[A-Z][a-z]{2,} here\b|\b(I'?m|I am|my name is) [A-Z][a-z]{2,}\b(?! (excited|glad|happy|curious|interested|impressed))")


def _token() -> str:
    with _lk:
        if time.time() - _tok["at"] > 1800:
            _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            _tok["at"] = time.time()
        return _tok["t"]


def gemini(prompt: str, max_tokens: int, temperature: float) -> str:
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens,
                                 "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    url = URL.format(p=os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"))
    for i in range(6):
        try:
            req = urllib.request.Request(url, json.dumps(body).encode(),
                                         {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r)
                u = j.get("usageMetadata", {})
                with _lk:
                    USAGE["in"] += u.get("promptTokenCount", 0)
                    USAGE["out"] += u.get("candidatesTokenCount", 0)
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception:  # noqa: BLE001
            time.sleep(5 * (i + 1))
    return ""


def usd() -> float:
    return round(USAGE["in"] / 1e6 * 0.30 + USAGE["out"] / 1e6 * 2.50, 4)


def own_names(prompt: str) -> set:
    h = prompt.split("TODAY'S LAUNCH:")[0]
    names = set()
    for m in re.finditer(r"^- \d{4}-\d{2}-\d{2}: (.+?) \|", h, re.M):
        names.add(m.group(1).strip())
    for m in re.finditer(r'^- on (.+?): "', h, re.M):
        names.add(m.group(1).strip())
    out = set()
    for n in names:
        out.add(n)
        w = re.split(r"[\s:+|-]", n)[0]
        if len(w) >= 5 and w.lower() not in {"smart", "super", "simple", "better", "first", "agent", "open", "cloud", "build", "magic"}:
            out.add(w)
    return {n for n in out if len(n) >= 4}


def scored_launches(fs_path, truth_path, explain_path, lineup_path) -> dict:
    """launch id -> slug for launches E5's forward_says scored that have frozen truth and a persona panel."""
    fs = json.load(open(fs_path))
    tr = json.load(open(truth_path))["launches"]
    ex = json.load(open(explain_path))["launches"]
    slugs = {str(x["id"]): str(x.get("slug")) for x in json.load(open(lineup_path))}
    out = {}
    for r in fs["per_launch"]:
        lid = r["id"]
        if r.get("scored") and lid in tr and ((ex.get(lid) or {}).get("say") or {}).get("persona_panel") and lid in slugs:
            out[lid] = slugs[lid]
    return out


# ------------------------------------------------------------------------------------------------ gen
def stage_gen(a):
    os.makedirs(a.out, exist_ok=True)
    keep = scored_launches(a.fs, a.truth, a.explain, a.lineup)
    rows = [json.loads(l) for l in open(os.path.join(a.prompts, "eval.jsonl"))]
    by = {}
    for r in rows:
        by.setdefault(r["meta"]["slug"], []).append(r)
    cache_p = os.path.join(a.out, f"gen_{a.day}.jsonl")
    done = {}
    if os.path.exists(cache_p):
        for l in open(cache_p):
            x = json.loads(l)
            done[(x["meta"]["slug"], x["meta"]["person_idx"])] = x
    fh = open(cache_p, "a")
    leak = {"prompts": 0, "history_lines_on_or_after_day": 0, "comment_lines_on_a_launch_of_the_day": 0}
    names_today = {r["messages"][0]["content"].split("TODAY'S LAUNCH:\nName: ")[1].split("\n")[0] for r in rows}

    def gen(row):
        k = (row["meta"]["slug"], row["meta"]["person_idx"])
        if k in done:
            return done[k]
        prompt = row["messages"][0]["content"]
        p2 = prompt.replace(OLD, NEW) if OLD in prompt else prompt + "\n\nDo not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}"
        try:
            c = str(json.loads(gemini(p2, 300, 0.7)).get("comment", "")).strip()
        except Exception:  # noqa: BLE001
            c = ""
        c = re.sub(r"@[A-Za-z0-9_.-]+", "@someone", " ".join(c.split()))
        why = ("empty" if not c else "maker_like" if MAKER.search(c) else "self_named" if SELFNAME.search(c)
               else "names_own_history_product" if any(n.lower() in c.lower() for n in own_names(prompt)) else None)
        x = {"meta": row["meta"], "text": c, "drop": why}
        with _lk:
            fh.write(json.dumps(x) + "\n")
            fh.flush()
            done[k] = x
        return x

    stats = {"launches": 0, "calls_total": 0, "dropped": {}}
    for lid, slug in keep.items():
        rs = by.get(slug) or []
        if not rs:
            continue
        for r in rs:   # leak checks on every prompt of the launch
            h = r["messages"][0]["content"].split("TODAY'S LAUNCH:")[0]
            leak["prompts"] += 1
            leak["history_lines_on_or_after_day"] += sum(1 for m in re.finditer(r"^- (\d{4}-\d{2}-\d{2}): ", h, re.M) if m.group(1) >= a.day)
            leak["comment_lines_on_a_launch_of_the_day"] += sum(1 for m in re.finditer(r'^- on (.+?): "', h, re.M) if m.group(1).strip() in names_today)
        order = list(np.random.default_rng(int(hashlib.md5((lid + a.day).encode()).hexdigest()[:8], 16)).permutation(len(rs)))
        kept, pos = [], 0
        while len(kept) < 15 and pos < len(order):
            need = min(15 - len(kept), len(order) - pos)
            batch = [rs[i] for i in order[pos:pos + need]]
            pos += need
            with cf.ThreadPoolExecutor(8) as ex:
                res = list(ex.map(gen, batch))
            stats["calls_total"] += len(batch)
            for g in res:
                if g["drop"]:
                    stats["dropped"][g["drop"]] = stats["dropped"].get(g["drop"], 0) + 1
                else:
                    kept.append(g)
        stats["launches"] += 1
        with open(os.path.join(a.out, f"kept_{a.day}.jsonl"), "a") as f:
            for g in kept[:15]:
                f.write(json.dumps({"meta": {**g["meta"], "launch_id": lid}, "text": g["text"]}) + "\n")
    fh.close()
    stats.update(day=a.day, usd_this_run=usd(), leak=leak)
    json.dump(stats, open(os.path.join(a.out, f"gen_stats_{a.day}.json"), "w"), indent=1)
    print(json.dumps(stats))


# ------------------------------------------------------------------------------------------------ score
def stage_score(a):
    RE = open(os.path.join(a.judge_src, "reactions_eval.py")).read()
    CE = open(os.path.join(a.judge_src, "complaints_eval.py")).read()
    JUDGE = re.search(r'JUDGE = """(.*?)"""', RE, re.S).group(1)
    CJ = re.search(r'CJ = """(.*?)"""', CE, re.S).group(1)

    def g(p, mt):
        try:
            return json.loads(gemini(p, mt, 0.0))
        except Exception:  # noqa: BLE001
            return None

    def judge(th, ct, cand):
        Bt = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(cand))
        r = {}
        j = g(JUDGE.format(a="\n".join(f"{i + 1}. {t['theme']}" for i, t in enumerate(th)), b=Bt), 900) if th else None
        if j and len(j.get("a_covered", [])) == len(th):
            ac = np.array([bool(v) for v in j["a_covered"]])
            w = np.array([t["n"] for t in th], float)
            r.update({"recall": float(ac.mean()), "recall_w": float((ac * w).sum() / w.sum()),
                      "precision": float(np.mean([bool(v) for v in j.get("b_present", [])[:len(cand)]]))})
        if ct:
            j2 = g(CJ.format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(ct)), b=Bt), 1200)
            if j2 and len(j2.get("a_covered", [])) == len(ct):
                r["complaint_recall"] = float(np.mean([bool(v) for v in j2["a_covered"]]))
        return r

    jobs, meta = [], {}
    for D in a.days:
        TR = json.load(open(os.path.join(a.work, f"truth_{D}.v1.json")))["launches"]
        EX = json.load(open(os.path.join(a.work, f"explain_{D}.json")))["launches"]
        FS = {r["id"]: r for r in json.load(open(os.path.join(a.work, f"fs_{D}.v1.json")))["per_launch"]}
        kept = {}
        for l in open(os.path.join(a.work, f"kept_{D}.jsonl")):
            x = json.loads(l)
            kept.setdefault(x["meta"]["launch_id"], []).append(str(x["text"])[:300])
        for lid, pb in kept.items():
            pan = ((EX.get(lid) or {}).get("say") or {}).get("persona_panel") or {}
            pp = [f"{x.get('reaction', '')} Concern: {x.get('concern', '')} Question: {x.get('question', '')}" for x in pan.get("items", [])]
            if not pp or lid not in TR:
                continue
            meta[(D, lid)] = {"n_panel": len(pp), "n_person": len(pb),
                              "fs_v1_panel": {m: FS.get(lid, {}).get(m) for m in ("recall", "precision", "complaint_recall")}}
            for arm, cand in (("panel", pp), ("panel + 15", pp + pb)):
                for run in range(3):
                    jobs.append(((D, lid, arm, run), TR[lid]["themes"], TR[lid]["complaints"], cand))
    print("launches", len(meta), "judge jobs", len(jobs), flush=True)
    with cf.ThreadPoolExecutor(12) as ex:
        RES = list(ex.map(lambda j: (j[0], judge(j[1], j[2], j[3])), jobs))
    M = ("recall", "recall_w", "precision", "complaint_recall")
    V = {}
    for (D, lid, arm, run), r in RES:
        for m in M:
            if m in r:
                V.setdefault((D, lid, arm, m), []).append(r[m])
    lv = lambda D, l, arm, m: float(np.mean(V[(D, l, arm, m)])) if V.get((D, l, arm, m)) else np.nan  # noqa: E731
    rng = np.random.default_rng(0)

    def boot(keys, f):
        """[mean %, day-bootstrap 2.5, 97.5, launch-bootstrap 2.5, 97.5, launches, days]"""
        v = np.array([f(k) for k in keys], float)
        d = np.array([k[0] for k in keys])
        ok = ~np.isnan(v)
        v, d = v[ok], d[ok]
        if len(v) < 2:
            return None
        days = np.unique(d)
        idx = {x: np.flatnonzero(d == x) for x in days}
        bd = [v[np.concatenate([idx[x] for x in rng.choice(days, len(days))])].mean() for _ in range(4000)]
        bl = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
        p = lambda q, b: round(100 * float(np.percentile(b, q)), 1)  # noqa: E731
        return [round(100 * float(v.mean()), 1), p(2.5, bd), p(97.5, bd), p(2.5, bl), p(97.5, bl), int(len(v)), int(len(days))]

    def block(keys):
        out = {}
        for arm in ("panel", "panel + 15"):
            out[arm] = {m: boot(keys, lambda k, arm=arm, m=m: lv(k[0], k[1], arm, m)) for m in M}
        out["panel + 15 minus panel (paired)"] = {m: boot(keys, lambda k, m=m: lv(k[0], k[1], "panel + 15", m) - lv(k[0], k[1], "panel", m)) for m in M}
        out["panel (this run) minus panel (E5 forward_says v1)"] = {
            m: boot(keys, lambda k, m=m: lv(k[0], k[1], "panel", m) - (meta[k]["fs_v1_panel"][m] if meta[k]["fs_v1_panel"][m] is not None else np.nan))
            for m in ("recall", "precision", "complaint_recall")}
        return out

    keys = sorted(meta)
    groups = {"all days": keys}
    if a.groups:
        for gdef in a.groups:
            name, ds = gdef.split("=", 1)
            groups[name] = [k for k in keys if k[0] in ds.split(",")]
    res = {"note": "[mean %, day-bootstrap 2.5%, 97.5%, launch-bootstrap 2.5%, 97.5%, launches, days]; launch value = mean of 3 judge runs; "
                   "frozen consensus truth v1; persona panel items + person-built comments appended (deployed merge)",
           "launches_per_day": {D: sum(1 for k in keys if k[0] == D) for D in a.days},
           "person_built_per_launch_mean": round(float(np.mean([v["n_person"] for v in meta.values()])), 2),
           "panel_items_per_launch_mean": round(float(np.mean([v["n_panel"] for v in meta.values()])), 2),
           "groups": {n: block(k) for n, k in groups.items()}, "per day": {D: block([k for k in keys if k[0] == D]) for D in a.days},
           "usd_judging": usd()}
    json.dump(res, open(a.out, "w"), indent=1)
    for n, b in res["groups"].items():
        print(n, {m: b["panel + 15 minus panel (paired)"][m] for m in ("recall", "precision", "complaint_recall")}, flush=True)
        print("   panel", {m: b["panel"][m][:3] if b["panel"][m] else None for m in ("recall", "precision", "complaint_recall")},
              "panel+15", {m: b["panel + 15"][m][:3] if b["panel + 15"][m] else None for m in ("recall", "precision", "complaint_recall")})
    print("usd", res["usd_judging"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["gen", "score"])
    ap.add_argument("--day"); ap.add_argument("--prompts"); ap.add_argument("--explain"); ap.add_argument("--lineup")
    ap.add_argument("--fs"); ap.add_argument("--truth"); ap.add_argument("--out", required=True)
    ap.add_argument("--days", nargs="*", default=[]); ap.add_argument("--work"); ap.add_argument("--judge-src")
    ap.add_argument("--groups", nargs="*", default=[])
    a = ap.parse_args(argv)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
