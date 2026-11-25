"""COMPLAINT-1: which real complaints the panels miss, and two arms meant to catch more of them.

  python -m simharness.complaint1 run   --work W --sim-dir SIM --bench BENCH --forward-root FWD [--budget 2.9]
  python -m simharness.complaint1 table --work W --out-dir simharness/bench_v0/ceiling1/complaint1 [--sync gs://...]

Same 22 launches, resamples and stored half-B themes / complaints as CEILING-2 (W/launch2_rows.jsonl), the same
scorer (E5's JUDGE and CJ, Gemini 2.5 Flash, temperature 0), every arm subsampled to half A's comment count with the
same seed rule. Half A is rebuilt from the same raw comment files and permutation as CEILING-2.

Diagnosis: CJ's per-complaint coverage for half A (the ceiling) and the deployed panel; each half-B complaint put in
one of six kinds by one Gemini call per batch: pricing, trust/privacy/security, already exists / differentiation,
setup friction / integration, bugs / reliability / performance, unclear value or use case (other).

Arms (all built only from the 00:05 line-up / launch page and held histories before the day; nothing from half B):
  deployed        the frozen persona panel + the frozen person-built comments (CEILING-2's "deployed")
  control         the persona panel regenerated now with E5's prompt unchanged + the frozen person-built comments
                  (so arm (a) differs from it by one line only)
  a_stop_line     the persona panel regenerated with one line added: what would stop a member of this group from using
                  this product, be specific + the frozen person-built comments
  b_critical      the frozen persona panel + 15 person-built comments from held people whose past comments are mostly
                  critical (>= 3 comments before D, >= 50% with a critique marker), chosen like the deployed panel
                  (topic share of their upvotes, ties by 30-day upvotes), same prompt, temperature 0.7, privacy guard
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd

from simharness import ceiling1 as C1

KINDS = ["pricing", "trust/privacy/security", "already exists/differentiation", "setup friction/integration",
         "bugs/reliability/performance", "unclear value/use case/other"]
CRIT = re.compile(r"\b(but|however|though|concern|concerned|worry|worried|expensive|pricing|price|privacy|secure|security|unclear|confus\w*|"
                  r"why would|different from|already|doesn'?t|don'?t|not sure|issue|problem|bug|missing|lack\w*|wish|struggle|hard to|"
                  r"limitation|downside|risk|trust)\b", re.I)
STOP_LINE = ('For each group\'s "concern", say what would stop a typical member of that group from using this product: '
             "be specific to this launch (a price, a missing integration, a trust or privacy worry, an existing tool they already use, "
             "setup effort, reliability), not a generic doubt.")


def gemini_t(prompt, max_tokens, temperature):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(6):
        try:
            req = urllib.request.Request(C1.URL, json.dumps(body).encode(), {"Authorization": "Bearer " + C1._token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r)
                u = j.get("usageMetadata", {})
                with C1._lk:
                    C1.USAGE["in"] += u.get("promptTokenCount", 0)
                    C1.USAGE["out"] += u.get("candidatesTokenCount", 0)
                    C1.USAGE["calls"] += 1
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            if "403" in str(e):
                raise
            time.sleep(4 * (i + 1))
    return ""


def persona_prompt(sim_dir):
    src = open(os.path.join(sim_dir, "persona_prompt.py")).read()
    G = {}
    exec(src, G)
    return G["PROMPT"], G["gtxt"]


def regen_persona(W, sim_dir, d, lid, stop):
    PROMPT, gtxt = persona_prompt(sim_dir)
    if stop:
        PROMPT = PROMPT.replace("\nFor EVERY group (same order), return JSON only:", "\n" + STOP_LINE + "\nFor EVERY group (same order), return JSON only:")
    cards = json.load(open(f"{W}/cards/{d}.json"))["launches"]
    line = {str(x["id"]): x for x in json.load(open(f"{W}/raw/{d}/today_0005.json"))}
    c, p = cards.get(lid) or {}, line.get(lid)
    P_ = c.get("personas") or []
    if not P_ or not p:
        return None
    topics = ", ".join(e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or []))
    txt = gemini_t(PROMPT.format(name=p.get("name"), tagline=p.get("tagline"), desc=(p.get("description") or "")[:1200], topics=topics,
                                 groups="\n".join(gtxt(i, g) for i, g in enumerate(P_))), max(3000, 300 * len(P_)), 0.0)
    try:
        R = json.loads(txt)["reactions"]
    except Exception:  # noqa: BLE001
        return None
    return [f"{r.get('reaction', '')} Concern: {r.get('concern', '')} Question: {r.get('question', '')}" for r in R]


def critical_panel(bench, W, d, lid, maker_comment=None, n=15):
    from simharness.run_what_panel import lineup_items
    from simharness.finetune.export import FT_PROMPT
    from simharness.task_c import _item_fields
    st = bench.state(d)
    o = (pd.Timestamp(d) - pd.Timestamp("1970-01-01")).days
    start = pd.Timestamp(d, tz="America/Los_Angeles").tz_convert("UTC")
    cm = bench.comments
    ts = pd.to_datetime(cm.ts, utc=True)
    prev = cm[(cm.day_ord < o) & (ts.isna() | (ts < start))]
    crit = prev.assign(c=prev.text.map(lambda t: bool(CRIT.search(str(t))))).groupby("person_idx").c.agg(["mean", "size"])
    critical = set(crit[(crit["size"] >= 3) & (crit["mean"] >= 0.5)].index)
    ok = np.array(sorted(p for p in np.flatnonzero((st["n60"] >= 1) & (st["n_comments"] >= 3)) if p in critical))
    items = {it.item_id: it for it in lineup_items(f"{W}/raw/{d}/today_0005.json")}
    slug = {str(x["id"]): str(x["slug"]) for x in json.load(open(f"{W}/raw/{d}/today_0005.json"))}
    item = items.get(slug.get(lid))
    if item is None or not len(ok):
        return [], len(ok)
    vec = np.zeros(len(bench.vocab), np.float32)
    for t in item.tags:
        if t in bench.vocab:
            vec[bench.vocab[t]] = 1.0
    share = np.asarray(st["topics"][ok] @ vec).ravel() / (np.maximum(st["n_all"][ok], 1.0) * max(vec.sum(), 1.0))
    panel = ok[np.lexsort((-st["n30"][ok], -share))[:30]]
    batch = bench.batch(d, panel)
    fields = _item_fields(item)
    rows = [FT_PROMPT.format(history=batch.render(j, 30, 10), **fields) for j in range(len(panel))]
    if maker_comment:
        rows = [r.replace("\nTopics:", f"\nMaker's launch comment: {maker_comment}\nTopics:", 1) for r in rows]
    order = list(np.random.default_rng(int(hashlib.md5((lid + d).encode()).hexdigest()[:8], 16)).permutation(len(rows)))
    OLD = "This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. Reply with the comment only."
    NEW = ("This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. "
           "Do not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}")
    MAKER = re.compile(r"\b(we built|we('| a)re (excited|thrilled|launching)|our (team|launch|product)|thanks for (the )?(support|hunting)|i built|we launched|hunting us|my (startup|company|product)|co-?founder|founder of|maker of)\b", re.I)

    def gen(p):
        raw = gemini_t(p.replace(OLD, NEW), 300, 0.7)
        try:
            c = " ".join(str(json.loads(raw).get("comment", "")).split())
        except Exception:  # noqa: BLE001
            c = ""
        c = re.sub(r"@[A-Za-z0-9_.-]+", "@someone", c)
        return c if c and not MAKER.search(c) else None
    kept, pos = [], 0
    while len(kept) < n and pos < len(order):
        need = min(n - len(kept), len(order) - pos)
        with cf.ThreadPoolExecutor(8) as ex:
            res = list(ex.map(gen, [rows[i] for i in order[pos:pos + need]]))
        pos += need
        kept += [r[:300] for r in res if r]
    return kept[:n], len(ok)


def cmd_run(a):
    P = C1.prompts(a.sim_dir)
    W = a.work
    from simharness.bench import Benchmark
    dirs = sorted(x for x in glob.glob(os.path.join(a.forward_root, "20*")) if os.path.exists(f"{x}/comments.parquet"))
    bench = Benchmark(a.bench, overlays=dirs)
    R = pd.DataFrame([json.loads(l) for l in open(f"{W}/launch2_rows.jsonl")])
    launches = R[["day", "id"]].drop_duplicates().values.tolist()
    # ---- arms per launch
    arms_path = f"{W}/complaint1_arms.json"
    ARMS = json.load(open(arms_path)) if os.path.exists(arms_path) else {}
    for d, lid in launches:
        key = f"{d}|{lid}"
        if key in ARMS:
            continue
        C, T0 = C1.real_comments(W, d)
        frozen = C1.arms_for(W, d, T0)[lid]
        persona_n = len(frozen["persona"])
        pb = frozen["deployed"][persona_n:]
        with cf.ThreadPoolExecutor(2) as ex:
            ctrl, stop = list(ex.map(lambda s: regen_persona(W, a.sim_dir, d, lid, s), (False, True)))
        crit, n_crit_pool = critical_panel(bench, W, d, lid)
        ARMS[key] = {"persona": frozen["persona"], "pb": pb, "control_persona": ctrl, "stop_persona": stop, "critical_pb": crit,
                     "n_critical_pool": int(n_crit_pool), "pb_source": frozen["pb_source"]}
        json.dump(ARMS, open(arms_path, "w"))
        print("arms", d, lid, "usd", round(C1.usd(), 3), "critical pool", n_crit_pool, "kept", len(crit), flush=True)
    # ---- judge every resample
    out_path = f"{W}/complaint1_rows.jsonl"
    done = {(json.loads(l)["id"], json.loads(l)["resample"]) for l in open(out_path)} if os.path.exists(out_path) else set()
    fo = open(out_path, "a")
    halves = {}
    for d, lid in launches:
        C, _ = C1.real_comments(W, d)
        g_ = C[C.post == lid]
        users = sorted(g_.uid.unique())
        for k in range(8):
            perm = np.random.default_rng(int(lid) * 100 + k).permutation(users)
            halves[(lid, k)] = g_[g_.uid.isin(set(perm[: len(users) // 2]))].sort_values("created").text.tolist()

    def one(r):
        A = ARMS[f"{r['day']}|{r['id']}"]
        ca = [x[:300] for x in halves[(r["id"], r["resample"])]]
        n = len(ca)
        th, ct = r["themes_b"], r["complaints_b"]
        lists = {"ceiling_half_a": ca, "deployed": A["persona"] + A["pb"]}
        if A["control_persona"]:
            lists["control"] = A["control_persona"] + A["pb"]
        if A["stop_persona"]:
            lists["a_stop_line"] = A["stop_persona"] + A["pb"]
        if A["critical_pb"]:
            lists["b_critical"] = A["persona"] + A["critical_pb"]
        o = {"day": r["day"], "id": r["id"], "resample": r["resample"], "n_a": n, "complaints_b": ct}
        for arm, L in lists.items():
            if arm != "ceiling_half_a":
                rs = np.random.default_rng(int(r["id"]) * 1000 + r["resample"])
                L = [L[i] for i in sorted(rs.choice(len(L), min(n, len(L)), replace=False))]
            Bt = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(L))
            if th:
                j = C1.g(P["JUDGE"].format(a="\n".join(f"{i + 1}. {t['theme']}" for i, t in enumerate(th)), b=Bt), 900)
                if j and len(j.get("a_covered", [])) == len(th):
                    o[f"{arm}:recall"] = float(np.mean([bool(v) for v in j["a_covered"]]))
                    o[f"{arm}:precision"] = float(np.mean([bool(v) for v in j.get("b_present", [])[:len(L)]]))
            if ct:
                j2 = C1.g(P["CJ"].format(a="\n".join(f"{i + 1}. {t}" for i, t in enumerate(ct)), b=Bt), 1200)
                if j2 and len(j2.get("a_covered", [])) == len(ct):
                    cov = [bool(v) for v in j2["a_covered"]]
                    o[f"{arm}:complaint_recall"] = float(np.mean(cov))
                    o[f"{arm}:complaint_covered"] = cov
        return o
    todo = [r for r in R.to_dict("records") if (r["id"], r["resample"]) not in done]
    with cf.ThreadPoolExecutor(10) as ex:
        for o in ex.map(one, todo):
            fo.write(json.dumps(o) + "\n")
            fo.flush()
            if C1.usd() > a.budget:
                print("budget reached", flush=True)
                break
    # ---- complaint kinds
    kind_path = f"{W}/complaint1_kinds.json"
    KIND = json.load(open(kind_path)) if os.path.exists(kind_path) else {}
    texts = sorted({c for r in R.complaints_b for c in r} - set(KIND))
    for i in range(0, len(texts), 40):
        chunk = texts[i:i + 40]
        j = C1.g("Classify each Product Hunt launch complaint into exactly one kind: " + "; ".join(f"{k + 1} = {x}" for k, x in enumerate(KINDS)) +
                 ".\nComplaints:\n" + "\n".join(f"{k + 1}. {t}" for k, t in enumerate(chunk)) +
                 '\nJSON only: {"kinds": [<kind number for complaint 1>, <for complaint 2>, ...]}', 800) or {}
        ks = j.get("kinds") or []
        for t, k in zip(chunk, ks):
            try:
                KIND[t] = KINDS[int(k) - 1]
            except (ValueError, IndexError):
                KIND[t] = KINDS[-1]
    json.dump(KIND, open(kind_path, "w"), indent=1)
    json.dump({"usd": round(C1.usd(), 4), "calls": C1.USAGE["calls"], "tokens_in": C1.USAGE["in"], "tokens_out": C1.USAGE["out"]}, open(f"{W}/complaint1_spend.json", "w"))
    print("usd", round(C1.usd(), 3))


def cmd_table(a):
    W = a.work
    R = pd.DataFrame([json.loads(l) for l in open(f"{W}/complaint1_rows.jsonl")])
    KIND = json.load(open(f"{W}/complaint1_kinds.json"))
    ARMS = json.load(open(f"{W}/complaint1_arms.json"))
    arms = ["deployed", "control", "a_stop_line", "b_critical"]
    out = {"launches": int(R.id.nunique()), "resamples": int(len(R)), "spend": json.load(open(f"{W}/complaint1_spend.json")),
           "critical_pool_per_launch_median": float(np.median([v["n_critical_pool"] for v in ARMS.values()])),
           "arms_missing": {arm: [k for k, v in ARMS.items() if not v.get({"control": "control_persona", "a_stop_line": "stop_persona", "b_critical": "critical_pb"}.get(arm, "persona"))] for arm in arms}}
    # diagnosis by kind
    rows = []
    for r in R.to_dict("records"):
        for i, c in enumerate(r["complaints_b"]):
            x = {"id": r["id"], "kind": KIND.get(c, KINDS[-1])}
            for arm in ["ceiling_half_a"] + arms:
                cov = r.get(f"{arm}:complaint_covered")
                x[arm] = float(cov[i]) if isinstance(cov, list) and i < len(cov) else np.nan
            rows.append(x)
    K = pd.DataFrame(rows)
    diag = {}
    for k, g in K.groupby("kind"):
        per = g.groupby("id")[["ceiling_half_a", "deployed"]].mean()
        diag[k] = {"complaints": int(len(g)), "launches": int(g.id.nunique()), "share_of_all": round(len(g) / len(K), 3),
                   "caught_by_half_a": round(float(g.ceiling_half_a.mean()), 3), "caught_by_deployed": round(float(g.deployed.mean()), 3),
                   "deployed_minus_half_a_points": C1.boot((per.deployed - per.ceiling_half_a) * 100)}
    out["diagnosis_by_kind"] = dict(sorted(diag.items(), key=lambda kv: -kv[1]["complaints"]))
    # arms vs ceiling and vs deployed, paired by launch
    res = {}
    for m in ("complaint_recall", "precision", "recall"):
        per = R.groupby("id").agg(**{arm: (f"{arm}:{m}", "mean") for arm in ["ceiling_half_a"] + arms if f"{arm}:{m}" in R})
        row = {"ceiling_half_a": C1.boot(per.ceiling_half_a * 100)}
        for arm in arms:
            if arm not in per:
                continue
            ok = per[arm].notna() & per.ceiling_half_a.notna()
            row[arm] = {"value": C1.boot(per[arm][ok] * 100),
                        "ratio_of_means_to_ceiling": round(float(per[arm][ok].mean() / per.ceiling_half_a[ok].mean()), 4),
                        "fraction_of_ceiling_by_launch": C1.boot((per[arm] / per.ceiling_half_a)[ok & (per.ceiling_half_a > 0)]),
                        "minus_deployed_points": C1.boot((per[arm] - per.deployed)[per[arm].notna()] * 100) if arm != "deployed" else None,
                        "minus_control_points": C1.boot((per[arm] - per.control)[per[arm].notna() & per.control.notna()] * 100) if arm == "a_stop_line" and "control" in per else None}
        res[m] = row
    out["arms"] = res
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(out, open(f"{a.out_dir}/complaint1.json", "w"), indent=1)
    if a.sync:
        subprocess.run(["gsutil", "-q", "cp", f"{a.out_dir}/complaint1.json", a.sync + "/complaint1.json"], check=False)
    print(json.dumps(out, indent=1)[:9000])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--sim-dir", required=True)
    r.add_argument("--bench", required=True)
    r.add_argument("--forward-root", required=True)
    r.add_argument("--budget", type=float, default=2.9)
    t = sub.add_parser("table")
    t.add_argument("--work", required=True)
    t.add_argument("--out-dir", required=True)
    t.add_argument("--sync")
    a = ap.parse_args(argv)
    cmd_run(a) if a.cmd == "run" else cmd_table(a)


if __name__ == "__main__":
    main()
