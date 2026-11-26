"""CHOICE-FT-1 (docs/ledger/experiments.jsonl): a tuned open model as a yes/no backing scorer vs most-active and
BACKER-v2 on Benchmark v0.

  python -m simharness.finetune.choice_ft1 export    --bench B --lineup choice_lineup.parquet --out O
  python -m simharness.finetune.choice_ft1 baselines --bench B --out O
  python -m simharness.finetune.choice_ft1 agg       --bench B --out O --scores DIR --results-dir R

export     O/train.jsonl (person-days of days <= the benchmark's train_end; all positives + 10 sampled negatives
           each, half of the person-days with an upvote, half without), O/eval.jsonl (test days: a fixed 15% of each
           day's pool x the day's 00:05 line-up), O/eval_pairs.parquet (day, item_idx, person_idx, y), leak checks.
baselines  most-active and the BACKER-v2-style logistic (walk-forward, 1-day gap; and frozen on days <= train_end) on
           the eval pairs and on the full pool x line-up.
agg        per-launch recall@N and AUC with launch-bootstrap intervals, paired differences vs BACKER-v2, the
           learning curve; aggregates only into --results-dir (no rows, no ids).

Everything under O and DIR is private (salted person keys, real comment text). Leak rules: a prompt for day D holds
endorsements of launches with day < D and comments written before D starts; launch fields are name, tagline and
topics (listing fields); the day's own upvotes are labels only.
"""
from __future__ import annotations

import argparse
import json
import os
import re

import numpy as np
import pandas as pd

from simharness.bench import KIND_CODE, Benchmark, _day_bounds_utc, day_ord, scrub
from simharness.schema import COMMENT, ENDORSE

NB = 2000
K_NEG = 10
EVAL_FRAC = 0.15
N_LATEST = 12

INSTR = ("You predict which Product Hunt launches one real member upvotes on the day the launches go live.\n\n"
         "MEMBER (everything known before today):\n{history}\n\n"
         "Question: did this member upvote the launch below today? Answer Yes or No.\n\nLAUNCH: ")


class Histories:
    """Per-person sorted endorsement and comment arrays for fast as-of-day rendering."""

    def __init__(self, b: Benchmark):
        self.b = b
        h = b.hist[b.hist["kind"] == KIND_CODE[ENDORSE]].sort_values(["person_idx", "day_ord", "item_idx"])
        self.e_p = h["person_idx"].to_numpy(); self.e_d = h["day_ord"].to_numpy(); self.e_i = h["item_idx"].to_numpy()
        self.e_ts = h["ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        self.e_lo = np.searchsorted(self.e_p, np.arange(b.n_people)); self.e_hi = np.searchsorted(self.e_p, np.arange(b.n_people), "right")
        c = b.comments.sort_values(["person_idx", "day_ord", "ts"])
        self.c_p = c["person_idx"].to_numpy(); self.c_d = c["day_ord"].to_numpy(); self.c_i = c["item_idx"].to_numpy()
        self.c_ts = c["ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        self.c_txt = c["text"].astype(str).to_numpy()
        self.c_lo = np.searchsorted(self.c_p, np.arange(b.n_people)); self.c_hi = np.searchsorted(self.c_p, np.arange(b.n_people), "right")
        it = b.items
        self.title = [scrub(str(x)) for x in it["title"]]
        self.summary = [scrub(str(x)) for x in it["summary"]]
        self.tags = [list(x) for x in it["tags"]]
        self.item_day = it["day_ord"].to_numpy()

    def events(self, p: int, day: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Endorsements (day_ord, item_idx) and comment rows (indices) known before `day` for person p."""
        o = day_ord(day)
        start = np.datetime64(_day_bounds_utc(day, self.b.cfg.day_tz)[0].tz_localize(None))
        lo, hi = self.e_lo[p], self.e_hi[p]
        k = lo + np.searchsorted(self.e_d[lo:hi], o)
        ed, ei, ets = self.e_d[lo:k], self.e_i[lo:k], self.e_ts[lo:k]
        ok = np.isnat(ets) | (ets < start)
        ed, ei = ed[ok], ei[ok]
        lo, hi = self.c_lo[p], self.c_hi[p]
        ci = np.arange(lo, hi)
        ci = ci[(self.c_d[ci] < o) & (np.isnat(self.c_ts[ci]) | (self.c_ts[ci] < start))]
        return ed, ei, ci

    def launch(self, i: int) -> str:
        s = self.summary[i]
        s = s if len(s) <= 120 else s[:117] + "..."
        return f"{self.title[i]} — {s} | topics: {', '.join(self.tags[i][:4]) or '(none)'}"

    def prefix(self, p: int, day: str) -> str:
        o = day_ord(day)
        ed, ei, ci = self.events(p, day)
        age = o - ed
        n = lambda k: int((age <= k).sum())  # noqa: E731
        act = lambda k: int(len(np.unique(ed[age <= k])))  # noqa: E731
        dsl = int(age.min()) if len(age) else None
        lines = [f"Upvotes: {int((age == 1).sum())} yesterday, {n(7)} in the last 7 days, {n(30)} in the last 30 days, "
                 f"{n(60)} in the last 60 days, {len(ed)} in all. Active on {act(7)} of the last 7 days and {act(30)} "
                 f"of the last 30. " + (f"Last upvote {dsl} days before today." if dsl else "No upvote known before today."),
                 f"Comments written: {len(ci)}."]
        if len(ei):
            cnt: dict[str, int] = {}
            for i in ei:
                for t in self.tags[i]:
                    cnt[t] = cnt.get(t, 0) + 1
            top = sorted(cnt, key=lambda t: (-cnt[t], t))[:5]
            lines.append(f"Most-upvoted topics: {', '.join(top)}.")
            lines.append(f"Latest upvoted launches (newest first, up to {N_LATEST}):")
            order = np.lexsort((-ei, -ed))[:N_LATEST]
            for j in order:
                s = self.summary[ei[j]]
                lines.append(f"- {self.title[ei[j]]} — {s if len(s) <= 70 else s[:67] + '...'}")
        if len(ci):
            lines.append("Latest comments:")
            for j in ci[::-1][:2]:
                t = scrub(" ".join(self.c_txt[j].split()))
                lines.append(f'- on {self.title[self.c_i[j]]}: "{t if len(t) <= 140 else t[:137] + "..."}"')
        return INSTR.format(history="\n".join(lines))


def _handles(text: str) -> int:
    """@handles left after scrub() (the scrubbed form "@someone", also when cut short, is not a handle)."""
    return sum(1 for m in re.findall(r"@[A-Za-z0-9_.-]+", text) if not "someone".startswith(m[1:].rstrip(".-")))


def day_matrix(b: Benchmark, day: str, items: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pool = b.pool(day)
    loc = {int(p): k for k, p in enumerate(pool)}
    Y = np.zeros((len(pool), len(items)), bool)
    for j, it in enumerate(items):
        pos = b.positives(day, it)
        Y[[loc[int(p)] for p in pos], j] = True
    return pool, Y


# ------------------------------------------------------------------------------------------------ export
def stage_export(a):
    b = Benchmark(a.bench)
    H = Histories(b)
    rng = np.random.default_rng(a.seed)
    os.makedirs(a.out, exist_ok=True)
    # training person-days, stratified: present (>= 1 upvote on the day's launches) / absent
    tr_days = b.days("train")
    pres, absn = [], []
    for d in tr_days:
        items = b.items_on(d)
        pool, Y = day_matrix(b, d, items)
        has = Y.any(1)
        pres += [(d, int(p)) for p in pool[has]]; absn += [(d, int(p)) for p in pool[~has]]
    pick = [pres[i] for i in rng.choice(len(pres), a.person_days // 2, replace=False)] + \
           [absn[i] for i in rng.choice(len(absn), a.person_days // 2, replace=False)]
    order = rng.permutation(len(pick))
    by_day: dict[str, list[int]] = {}
    for k in order:
        by_day.setdefault(pick[k][0], []).append(int(k))
    recs: list[dict | None] = [None] * len(pick)
    for d, ks in by_day.items():
        items = b.items_on(d)
        pool, Y = day_matrix(b, d, items)
        loc = {int(p): k for k, p in enumerate(pool)}
        for k in ks:
            p = pick[k][1]
            y = Y[loc[p]]
            pos = np.flatnonzero(y); neg = np.flatnonzero(~y)
            neg = rng.choice(neg, min(K_NEG, len(neg)), replace=False) if len(neg) else neg
            js = rng.permutation(np.r_[pos, neg])
            recs[k] = {"prefix": H.prefix(p, d), "suffixes": [H.launch(int(items[j])) for j in js],
                       "labels": [int(y[j]) for j in js],
                       "meta": {"day": d, "person_idx": p, "items": [int(items[j]) for j in js]}}
    with open(f"{a.out}/train.jsonl", "w") as f:
        for k in order:
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")
    n_rows = sum(len(recs[k]["labels"]) for k in order)
    n_pos = sum(sum(recs[k]["labels"]) for k in order)

    # eval: fixed 15% of each test day's pool x the day's 00:05 line-up
    lu = pd.read_parquet(a.lineup)
    ev, pairs = [], []
    for d in b.days("test"):
        items = lu.loc[lu["day"] == d, "item_idx"].to_numpy().astype(np.int64)
        if not len(items):
            continue
        pool, Y = day_matrix(b, d, items)
        r = np.random.default_rng(day_ord(d))
        sel = np.sort(r.choice(len(pool), int(round(EVAL_FRAC * len(pool))), replace=False))
        for k in sel:
            p = int(pool[k])
            ev.append({"prefix": H.prefix(p, d), "suffixes": [H.launch(int(i)) for i in items],
                       "meta": {"day": d, "person_idx": p, "items": [int(i) for i in items]}})
            pairs.append(pd.DataFrame({"day": d, "item_idx": items, "person_idx": p, "y": Y[k].astype(np.int8)}))
    with open(f"{a.out}/eval.jsonl", "w") as f:
        for r in ev:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ep = pd.concat(pairs, ignore_index=True)
    ep.to_parquet(f"{a.out}/eval_pairs.parquet")

    # leak checks and overlap
    late = later_c = tgt_in_hist = 0
    chk = [recs[k] for k in order[:3000]] + ev[:3000]
    for r in chk:
        d, p = r["meta"]["day"], r["meta"]["person_idx"]
        ed, ei, ci = H.events(p, d)
        late += int((ed >= day_ord(d)).sum())
        start = np.datetime64(_day_bounds_utc(d, b.cfg.day_tz)[0].tz_localize(None))
        later_c += int(((H.c_d[ci] >= day_ord(d)) & np.isnat(H.c_ts[ci])).sum() + (H.c_ts[ci] >= start).sum())
        tgt_in_hist += int(np.isin(r["meta"]["items"], ei).sum())
    item_days_ok = all(H.item_day[i] == day_ord(r["meta"]["day"]) for r in chk for i in r["meta"]["items"])
    tr_people = {pick[k][1] for k in order}
    ev_people = set(ep["person_idx"].unique().tolist())
    info = {"train_person_days": len(pick), "train_rows": n_rows, "train_positives": n_pos,
            "train_pos_neg_ratio": f"1:{(n_rows - n_pos) / max(n_pos, 1):.2f}",
            "train_first_day": min(x[0] for x in pick), "train_last_day": max(x[0] for x in pick),
            "train_people": len(tr_people), "train_launches": len({i for k in order for i in recs[k]["meta"]["items"]}),
            "present_person_days_available": len(pres), "absent_person_days_available": len(absn),
            "eval_person_days": len(ev), "eval_pairs": int(len(ep)), "eval_positives": int(ep["y"].sum()),
            "eval_launches": int(ep[["day", "item_idx"]].drop_duplicates().shape[0]),
            "eval_launches_with_a_backer": int(ep.groupby(["day", "item_idx"])["y"].sum().gt(0).sum()),
            "eval_people": len(ev_people), "eval_people_also_in_train": len(ev_people & tr_people),
            "eval_launches_in_train": 0 if not set(ep["item_idx"]) & {i for k in order for i in recs[k]["meta"]["items"]} else -1,
            "leak_checks_on_rows": len(chk), "history_endorsements_on_or_after_day": late,
            "comments_written_on_or_after_day_start": later_c, "target_launch_in_history": tgt_in_hist,
            "launches_all_dated_on_the_row_day": bool(item_days_ok),
            "handles_in_prompts": sum(_handles(t) for r in recs + ev for t in [r["prefix"]] + r["suffixes"]),
            "k_neg": K_NEG, "eval_frac": EVAL_FRAC, "seed": a.seed}
    json.dump(info, open(f"{a.out}/export_info.json", "w"), indent=1)
    print(json.dumps(info, indent=1))


# ------------------------------------------------------------------------------------------------ baselines
def stage_baselines(a):
    from simharness.models.baselines import backer_logistic, most_active
    b = Benchmark(a.bench)
    ep = pd.read_parquet(f"{a.out}/eval_pairs.parquet")
    lu = ep[["day", "item_idx"]].drop_duplicates()
    out = {}
    models = {"most_active": most_active(), "backer_v2_wf": backer_logistic(),
              "backer_v2_frozen": backer_logistic(refit_every=10 ** 6), "most_active_frozen": most_active(refit_every=10 ** 6)}
    full_rows = []
    for d, g in lu.groupby("day"):
        pool = b.pool(d)
        for it in g["item_idx"]:
            full_rows.append(pd.DataFrame({"day": d, "item_idx": int(it), "person_idx": pool,
                                           "y": np.isin(pool, b.positives(d, it)).astype(np.int8)}))
    full = pd.concat(full_rows, ignore_index=True)
    for name, m in models.items():
        if name.endswith("frozen"):
            m.prepare(b, ord_next(b.cfg.train_end))  # fit on days <= train_end once
            print(name, m.fit_info, flush=True)
        for which, rows in (("eval", ep), ("full", full)):
            p = np.full(len(rows), np.nan)
            for (d, it), g in rows.groupby(["day", "item_idx"], sort=True):
                m.prepare(b, d)
                p[g.index.to_numpy()] = m.score(b.batch(d, g["person_idx"].to_numpy()), b.item(it))
            out[f"{name}__{which}"] = p
            print(name, which, "done", flush=True)
    np.savez(f"{a.out}/baseline_scores.npz", **out)
    full[["day", "item_idx", "person_idx", "y"]].to_parquet(f"{a.out}/full_pairs.parquet")


def ord_next(day: str) -> str:
    from simharness.bench import ord_day
    return ord_day(day_ord(day) + 1)


# ------------------------------------------------------------------------------------------------ agg
def load_scores(path: str, ep: pd.DataFrame) -> np.ndarray:
    key = {(d, int(i), int(p)): k for k, (d, i, p) in enumerate(zip(ep["day"], ep["item_idx"], ep["person_idx"]))}
    out = np.full(len(ep), np.nan)
    for line in open(path):
        r = json.loads(line)
        m = r["meta"]
        for i, s in zip(m["items"], r["p"]):
            out[key[(m["day"], int(i), int(m["person_idx"]))]] = s
    return out


def stage_agg(a):
    from simharness.score import paired_diff, score_rows, summarize
    ep = pd.read_parquet(f"{a.out}/eval_pairs.parquet")
    full = pd.read_parquet(f"{a.out}/full_pairs.parquet")
    bs = np.load(f"{a.out}/baseline_scores.npz")
    info = json.load(open(f"{a.out}/export_info.json"))
    per = {}
    names = {"most_active": "most-active (walk-forward)", "backer_v2_wf": "BACKER-v2 logistic (walk-forward, primary)",
             "backer_v2_frozen": "BACKER-v2 logistic (frozen, days <= Oct 31)",
             "most_active_frozen": "most-active (frozen)"}
    for k in names:
        per[k] = score_rows(ep, bs[f"{k}__eval"])
    tuned = {}
    for f in sorted(os.listdir(a.scores)):
        if f.startswith("scores_") and f.endswith(".jsonl"):
            tag = f[len("scores_"):-len(".jsonl")]
            p = load_scores(f"{a.scores}/{f}", ep)
            assert not np.isnan(p).any(), f"{f}: {np.isnan(p).sum()} pairs unscored"
            per[f"qwen_{tag}"] = score_rows(ep, p)
            tuned[f"qwen_{tag}"] = tag
    ok = lambda df: df[(df.N > 0) & (df.n > df.N)]  # noqa: E731
    res = {"experiment": "CHOICE-FT-1", "intervals": "launch-clustered bootstrap, 95%, 2,000 draws",
           "eval": {k: info[k] for k in ("eval_person_days", "eval_pairs", "eval_positives", "eval_launches",
                                         "eval_launches_with_a_backer", "eval_frac")},
           "train": {k: info[k] for k in ("train_person_days", "train_rows", "train_positives", "train_pos_neg_ratio",
                                          "train_first_day", "train_last_day", "train_people")},
           "overlap": {"eval_people": info["eval_people"], "eval_people_also_in_train": info["eval_people_also_in_train"],
                       "eval_launches_in_train": info["eval_launches_in_train"]},
           "leak_checks": {k: info[k] for k in ("leak_checks_on_rows", "history_endorsements_on_or_after_day",
                                                "comments_written_on_or_after_day_start", "target_launch_in_history",
                                                "launches_all_dated_on_the_row_day", "handles_in_prompts")},
           "models": {}, "vs_backer_v2_wf": {}, "vs_most_active": {}, "full_pool_baselines": {}}
    keys = ("recall_at_N_pooled", "recall_at_N_mean", "auc_mean")
    for k, df in per.items():
        s = summarize(ok(df), n_boot=NB, cluster="item")
        res["models"][k] = {m: s[m] for m in keys} | {"launches": s["items"], "positives": s["positives"],
                                                      "pairs": s["pairs"]}
        for ref, slot in (("backer_v2_wf", "vs_backer_v2_wf"), ("most_active", "vs_most_active")):
            if k != ref:
                res[slot][k] = {m: paired_diff(ok(df), ok(per[ref]), m, NB, cluster="item")
                                for m in ("recall_at_N_pooled", "recall_at_N_mean", "auc_mean")}
    for k in names:
        s = summarize(ok(score_rows(full, bs[f"{k}__full"])), n_boot=NB, cluster="item")
        res["full_pool_baselines"][k] = {m: s[m] for m in ("recall_at_N_pooled", "recall_at_N_mean", "auc_mean")} | {
            "launches": s["items"], "positives": s["positives"]}
    curve = sorted(((int(t.split("_")[-1]) if t.split("_")[-1].isdigit() else 0), k) for k, t in tuned.items()
                   if t != "base")
    res["learning_curve"] = [{"train_rows": n, "model": k, **{m: res["models"][k][m] for m in keys}} for n, k in curve]
    if len(curve) >= 2:
        hi, lo = curve[-1][1], curve[0][1]
        res["learning_curve_last_minus_first"] = {m: paired_diff(ok(per[hi]), ok(per[lo]), m, NB, cluster="item")
                                                  for m in ("recall_at_N_pooled", "auc_mean")}
    if os.path.exists(f"{a.scores}/train_info.json"):
        res["train_info"] = json.load(open(f"{a.scores}/train_info.json"))
    if os.path.exists(f"{a.scores}/cost.json"):
        res["cost"] = json.load(open(f"{a.scores}/cost.json"))
    os.makedirs(a.results_dir, exist_ok=True)
    json.dump(res, open(f"{a.results_dir}/results.json", "w"), indent=1, default=float)
    f = lambda d: f"{d['value'] * 100:.1f} [{d['ci95'][0] * 100:.1f}, {d['ci95'][1] * 100:.1f}]"  # noqa: E731
    g = lambda d: f"{d['value']:.3f} [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]"  # noqa: E731
    fd = lambda d: f"{d['diff'] * 100:+.1f} [{d['ci95'][0] * 100:+.1f}, {d['ci95'][1] * 100:+.1f}]"  # noqa: E731
    gd = lambda d: f"{d['diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"  # noqa: E731
    L = ["| Model | recall@N pooled | recall@N mean per launch | AUC mean per launch | recall@N vs BACKER-v2 | AUC vs BACKER-v2 |",
         "|---|---|---|---|---|---|"]
    for k, e in res["models"].items():
        dv = res["vs_backer_v2_wf"].get(k)
        L.append(f"| {names.get(k, k)} | {f(e['recall_at_N_pooled'])} | {f(e['recall_at_N_mean'])} | {g(e['auc_mean'])} "
                 f"| {fd(dv['recall_at_N_pooled']) if dv else ''} | {gd(dv['auc_mean']) if dv else ''} |")
    L += ["", "Full pool x line-up (baselines only):", "", "| Model | recall@N pooled | AUC mean |", "|---|---|---|"]
    for k, e in res["full_pool_baselines"].items():
        L.append(f"| {names[k]} | {f(e['recall_at_N_pooled'])} | {g(e['auc_mean'])} |")
    open(f"{a.results_dir}/table.md", "w").write("\n".join(L) + "\n")
    print("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["export", "baselines", "agg"])
    ap.add_argument("--bench", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--lineup", default=""); ap.add_argument("--person-days", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0); ap.add_argument("--scores", default="")
    ap.add_argument("--results-dir", default="")
    a = ap.parse_args(argv)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
