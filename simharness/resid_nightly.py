"""Nightly layer-1 residual read: does a frozen simulation line carry the structural model's miss?

  python -m simharness.resid_nightly --day 2026-11-26            # one PT day, once its final board exists
  python -m simharness.resid_nightly --backfill 2026-11-15:2026-11-24
  python -m simharness.resid_nightly --leaderboard-only

  --root   where results live (default gs://usersim-bakeoff-347838016394/usersim_sim; a local folder with the same
           layout also works, for tests)
  --dry-run  compute and print, write nothing

What it reads for day D (all paths under --root):
  results/web/truth_daily.json                 the final board; D is skipped until days[D].status == "counts"
  results/structural/D/shortlist.json          structural ranks (else results/structural/backtest/D.json)
  results/web/explain/D.json                   the explain `say` blocks:
      say:panel_interest        persona panel, people-weighted interest (high 1, medium 0.5, low 0)
      say:panel_reaction_sent   persona panel reactions, mean VADER compound
      say:panel_concern_sent    persona panel concerns, mean VADER compound
      say:reactions_sent        /try simulator reactions, mean VADER compound
      person_panel:sent         say.person_built_panel comments, mean VADER compound
      person_panel_noblock:sent say.person_built_panel_noblock (shadow), mean VADER compound
      ref:expected_held_votes   who.expected_held_votes (backer model; a reference line, not a simulation)
  results/calibration/D/**.json                any other frozen file with a per-launch `launches` list or dict (Stage B
                                               v1/v2 rerank_frozen*, PU-1 from Nov 26, ...): every numeric per-launch
                                               field becomes a line "<file stem>:<field>"

Freeze rule: a line is scored only when it was written before 03:30 PT on D. Proof, in order: the block's or file's own
predicted_at / frozen_at / written_at stamp; else the object's write time in the store. A block flagged
rehearsal_late_unscored, a stamp after 03:30 PT, or no proof at all (no stamp and the file was rewritten after 03:30 PT)
makes the line "late": it is listed with its reason and never scored. Late launches inside an on-time line are dropped.

Scores for each on-time line (structural top 20, launches with a real rank and a score):
  * within-day Spearman of the score with the structural miss (real rank minus structural rank, both re-ranked inside
    the scored set; negative = high score does better than the structural rank says);
  * real top-3 / top-5 captured when the shortlist is re-ordered by structural rank - k * z(score) (z inside the
    shortlist, missing scores z = 0), minus the structural order; k from a signed grid, fitted leave-one-day-out over
    every day with that line on time so far.

Writes results/calibration/D/residual.json (per line: status, freeze time, rows, Spearman, capture change) and the
cumulative results/calibration/residual_leaderboard.json (per line: n days, n launches, mean Spearman and capture change
with day-bootstrap 95% intervals, on-time freeze rate). No model calls; no person ids are read or written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import spearmanr

PT = ZoneInfo("America/Los_Angeles")
DEFAULT_ROOT = "gs://usersim-bakeoff-347838016394/usersim_sim"
TOPN = 20
KS = [0, 0.5, 1, 2, 3, 5, 8, -0.5, -1, -2, -3, -5, -8]
IV = {"high": 1.0, "medium": 0.5, "low": 0.0}
STAMP_KEYS = ("predicted_at", "frozen_at", "written_at")
SKIP_CAL = re.compile(r"(^|/)(truth|lineup_frozen|residual|cohort_scorecard[^/]*|rerank_a[^/]*)\.json$|(^|/)what_panel/")
SKIP_FIELD = re.compile(r"rank|structural|^agents$|^n_|_n$|usd|seed|^k$|^id$|^day$|count|calls")
VERSION = "resid_nightly_v1"


# ---------------------------------------------------------------- storage (gs:// prefix or local folder)
class Store:
    def __init__(self, root: str):
        self.root = root.rstrip("/")
        self.gcs = self.root.startswith("gs://")

    def _p(self, rel):
        return f"{self.root}/{rel}"

    def read_json(self, rel):
        if not self.gcs:
            p = self._p(rel)
            return json.load(open(p)) if os.path.exists(p) else None
        r = subprocess.run(["gsutil", "-q", "cat", self._p(rel)], capture_output=True)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)

    def mtime(self, rel):
        if not self.gcs:
            p = self._p(rel)
            return dt.datetime.fromtimestamp(os.path.getmtime(p), dt.timezone.utc) if os.path.exists(p) else None
        r = subprocess.run(["gsutil", "ls", "-l", self._p(rel)], capture_output=True, text=True)
        m = re.search(r"\s(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s", r.stdout or "")
        return _ts(m.group(1)) if m else None

    def list(self, rel_prefix):
        """Relative paths of every .json file under rel_prefix (recursive)."""
        if not self.gcs:
            base = self._p(rel_prefix)
            return sorted(os.path.relpath(p, self.root) for p in glob.glob(f"{base}/**/*.json", recursive=True))
        r = subprocess.run(["gsutil", "ls", "-r", f"{self._p(rel_prefix)}/**"], capture_output=True, text=True)
        out = [ln.strip()[len(self.root) + 1:] for ln in (r.stdout or "").splitlines() if ln.strip().endswith(".json")]
        return sorted(out)

    def write_json(self, rel, obj):
        data = json.dumps(obj, indent=1, ensure_ascii=False)
        if not self.gcs:
            p = self._p(rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write(data)
            return
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(data)
        subprocess.run(["gsutil", "-q", "-h", "Content-Type:application/json", "cp", f.name, self._p(rel)], check=True)
        os.unlink(f.name)


# ---------------------------------------------------------------- helpers
def _ts(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def cutoff(day: str) -> dt.datetime:
    d = dt.date.fromisoformat(day)
    return dt.datetime(d.year, d.month, d.day, 3, 30, tzinfo=PT).astimezone(dt.timezone.utc)


def _stamp(obj):
    if isinstance(obj, dict):
        for k in STAMP_KEYS:
            t = _ts(obj.get(k))
            if t:
                return t, k
    return None, None


_VADER = None


def vader(text):
    global _VADER
    if _VADER is None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _VADER = SentimentIntensityAnalyzer()
        except ImportError:
            _VADER = False
    if _VADER is False:
        return None
    return _VADER.polarity_scores(text if isinstance(text, str) else json.dumps(text))["compound"]


def _mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return float(np.mean(xs)) if xs else None


def boot(x, B=4000, seed=0):
    x = np.array([v for v in x if v is not None and not np.isnan(v)], float)
    if len(x) == 0:
        return {"mean": None, "lo": None, "hi": None}
    if len(x) < 2:
        return {"mean": float(x[0]), "lo": None, "hi": None}
    rng = np.random.default_rng(seed)
    m = rng.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 4), "lo": round(float(np.percentile(m, 2.5)), 4),
            "hi": round(float(np.percentile(m, 97.5)), 4)}


# ---------------------------------------------------------------- line extraction
class Line:
    def __init__(self, name, source, kind="simulation"):
        self.name, self.source, self.kind = name, source, kind
        self.scores, self.late_launches = {}, 0
        self.freeze_time, self.proof, self.late_reason = None, None, None

    def status(self):
        if self.late_reason:
            return "late"
        return "on_time" if self.scores else "empty"

    def head(self):
        return {"source": self.source, "kind": self.kind, "status": self.status(),
                "freeze_time": self.freeze_time.isoformat() if self.freeze_time else None, "proof": self.proof,
                "late_reason": self.late_reason, "late_launches_dropped": self.late_launches}


def _gate(line, stamp, key, file_time, cut, flag_late=False):
    """Decide the line's freeze proof; returns True if on time."""
    if flag_late:
        line.late_reason = "flagged rehearsal_late_unscored"
        return False
    if stamp is not None:
        line.freeze_time, line.proof = stamp, key
    elif file_time is not None and file_time <= cut:
        line.freeze_time, line.proof = file_time, "object write time"
    else:
        line.late_reason = ("no stamp, and the file was last written " + file_time.isoformat() + ", after 03:30 PT"
                            if file_time else "no stamp and no write time")
        return False
    if line.freeze_time > cut:
        line.late_reason = f"{line.proof} {line.freeze_time.isoformat()} is after 03:30 PT"
        return False
    return True


def explain_lines(store, day, cut):
    rel = f"results/web/explain/{day}.json"
    E = store.read_json(rel)
    if not E:
        return []
    ftime = store.mtime(rel)
    launches = E.get("launches") or {}
    say_lines = {n: Line(n, rel) for n in ("say:panel_interest", "say:panel_reaction_sent", "say:panel_concern_sent",
                                           "say:reactions_sent")}
    pp = {"person_panel:sent": ("person_built_panel", Line("person_panel:sent", rel)),
          "person_panel_noblock:sent": ("person_built_panel_noblock", Line("person_panel_noblock:sent", rel))}
    ref = Line("ref:expected_held_votes", rel, kind="reference (backer model, not a simulation)")
    say_times, pp_seen = [], {k: [] for k in pp}
    for lid, L in launches.items():
        say = L.get("say") or {}
        pa = _ts(say.get("predicted_at"))
        if say:
            if pa is None or pa > cut:
                for ln in say_lines.values():
                    ln.late_launches += 1
            else:
                say_times.append(pa)
                items = (say.get("persona_panel") or {}).get("items") or []
                w = [(it.get("n_people") or 0, it) for it in items if it.get("interest") in IV]
                if w and sum(a for a, _ in w) > 0:
                    say_lines["say:panel_interest"].scores[lid] = sum(a * IV[it["interest"]] for a, it in w) / sum(a for a, _ in w)
                if items:
                    s = _mean([vader(it.get("reaction") or "") for it in items])
                    if s is not None:
                        say_lines["say:panel_reaction_sent"].scores[lid] = s
                    s = _mean([vader(it.get("concern") or "") for it in items])
                    if s is not None:
                        say_lines["say:panel_concern_sent"].scores[lid] = s
                re_ = say.get("reactions")
                if isinstance(re_, list) and re_:
                    s = _mean([vader(x) for x in re_])
                    if s is not None:
                        say_lines["say:reactions_sent"].scores[lid] = s
        for name, (key, ln) in pp.items():
            blk = say.get(key)
            if isinstance(blk, dict) and blk.get("comments"):
                pp_seen[name].append((lid, blk))
        ehv = (L.get("who") or {}).get("expected_held_votes")
        if isinstance(ehv, (int, float)):
            ref.scores[lid] = float(ehv)
    out = []
    for ln in say_lines.values():
        if say_times:
            ln.freeze_time, ln.proof = max(say_times), "say.predicted_at (latest launch)"
        elif ln.late_launches:
            ln.late_reason = "every launch's say.predicted_at is missing or after 03:30 PT"
        if ln.scores or ln.late_reason:
            out.append(ln)
    for name, (key, ln) in pp.items():
        rows = pp_seen[name]
        if not rows:
            continue
        flag = any(b.get("rehearsal_late_unscored") for _, b in rows)
        stamps = [_stamp(b) for _, b in rows]
        st = max((s for s, _ in stamps if s), default=None)
        k = next((k for s, k in stamps if s), None)
        if _gate(ln, st, f"{key}.{k}" if k else None, ftime, cut, flag):
            for lid, b in rows:
                s = _mean([vader(c if isinstance(c, str) else (c.get("text") or c.get("comment") or ""))
                           for c in b["comments"]])
                if s is not None:
                    ln.scores[lid] = s
        out.append(ln)
    # the who block carries no stamp of its own: on time only if the whole file was last written before 03:30 PT
    if ref.scores:
        sc = ref.scores
        ref.scores = {}
        if _gate(ref, None, None, ftime, cut):
            ref.scores = sc
        out.append(ref)
    return out


def _numeric_fields(rec, prefix=""):
    out = {}
    for k, v in rec.items():
        if SKIP_FIELD.search(k):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
            out[prefix + k] = float(v)
        elif isinstance(v, dict) and not prefix:
            out.update(_numeric_fields(v, prefix=k + "."))
    return out


def calibration_lines(store, day, cut):
    out = []
    for rel in store.list(f"results/calibration/{day}"):
        if SKIP_CAL.search(rel):
            continue
        J = store.read_json(rel)
        if not isinstance(J, dict):
            continue
        L = J.get("launches")
        if isinstance(L, dict):
            items = [(str(k), v) for k, v in L.items() if isinstance(v, dict)]
        elif isinstance(L, list):
            items = [(str(v.get("id") or v.get("launch_id") or v.get("post_id")), v) for v in L if isinstance(v, dict)]
        else:
            continue
        items = [(k, v) for k, v in items if k and k != "None"]
        if not items:
            continue
        stem = os.path.splitext(os.path.relpath(rel, f"results/calibration/{day}"))[0].replace("/", ".")
        if J.get("version") or J.get("arm"):
            stem += "@" + str(J.get("version") or J.get("arm"))
        st, key = _stamp(J)
        flag = bool(J.get("rehearsal_late_unscored")) or J.get("before_0345_pt") is False and st is None
        fields = {}
        for lid, rec in items:
            for f, v in _numeric_fields(rec).items():
                fields.setdefault(f, {})[lid] = v
        ftime = store.mtime(rel)
        for f, sc in sorted(fields.items()):
            ln = Line(f"{stem}:{f}", rel)
            if _gate(ln, st, key, ftime, cut, flag):
                ln.scores = sc
            out.append(ln)
    return out


# ---------------------------------------------------------------- structural shortlist and truth
def structural(store, day):
    S = store.read_json(f"results/structural/{day}/shortlist.json") or store.read_json(f"results/structural/backtest/{day}.json")
    if not S:
        return None, None
    rows = sorted(S["launches"], key=lambda r: r["structural_rank"])[:TOPN]
    return [{"id": str(r["id"]), "srank": int(r["structural_rank"])} for r in rows], S.get("structural_model")


def spearman_day(rows):
    R = [r for r in rows if r.get("score") is not None and r.get("real") is not None]
    if len(R) < 5 or np.std([r["score"] for r in R]) == 0:
        return None, len(R)
    rr = {r["id"]: i + 1 for i, r in enumerate(sorted(R, key=lambda r: r["real"]))}
    sr = {r["id"]: i + 1 for i, r in enumerate(sorted(R, key=lambda r: r["srank"]))}
    rho = spearmanr([r["score"] for r in R], [rr[r["id"]] - sr[r["id"]] for r in R]).correlation
    return (None if np.isnan(rho) else float(rho)), len(R)


def order_with(rows, k):
    s = np.array([np.nan if r.get("score") is None else r["score"] for r in rows], float)
    ok = ~np.isnan(s)
    z = np.zeros(len(rows))
    if ok.sum() >= 2 and s[ok].std() > 0:
        z[ok] = (s[ok] - s[ok].mean()) / s[ok].std()
    sr = np.array([r["srank"] for r in rows], float)
    return [rows[i]["id"] for i in np.lexsort((sr, sr - k * z))]


def capture(order, top_ids, N):
    return len(set(order[:N]) & set(top_ids[N])) / N * 100


def fit_k(day_rows, N):
    """day_rows: list of (rows, top_ids). k maximising mean capture, ties to the smallest |k|."""
    if not day_rows:
        return 0
    return max(KS, key=lambda k: (np.mean([capture(order_with(r, k), t, N) for r, t in day_rows]), -abs(k)))


# ---------------------------------------------------------------- per day
def read_day(store, day):
    truth = (store.read_json("results/web/truth_daily.json") or {}).get("days", {}).get(day)
    if not truth or truth.get("status") != "counts":
        return None, "final board not in results/web/truth_daily.json yet"
    real = {str(k): int(v) for k, v in truth["ranks"].items()}
    sl, smodel = structural(store, day)
    if not sl:
        return None, "no structural shortlist for the day"
    cut = cutoff(day)
    lines = explain_lines(store, day, cut) + calibration_lines(store, day, cut)
    top_ids = {N: [k for k, v in real.items() if v <= N] for N in (3, 5)}
    res = {"version": VERSION, "day": day, "cutoff_utc": cut.isoformat(), "structural_model": smodel, "top_n": TOPN,
           "n_ranked": len(real), "real_top": top_ids, "lines": {}}
    for ln in lines:
        rec = ln.head()
        if rec["status"] == "on_time":
            rows = [{"id": r["id"], "srank": r["srank"], "real": real.get(r["id"]),
                     "score": ln.scores.get(r["id"])} for r in sl]
            rho, n = spearman_day(rows)
            rec.update({"rows": rows, "n_scored": n, "spearman_with_miss": rho})
        res["lines"][ln.name] = rec
    return res, None


def add_capture(res, history):
    """Capture change for this day per line, k fitted on every other day so far with the line on time."""
    for name, rec in res["lines"].items():
        if rec["status"] != "on_time":
            continue
        others = [(h["lines"][name]["rows"], h["real_top"]) for h in history
                  if h["day"] != res["day"] and h["lines"].get(name, {}).get("status") == "on_time"]
        top = {int(k): v for k, v in res["real_top"].items()}
        for N in (3, 5):
            k = fit_k([(r, {int(a): b for a, b in t.items()}) for r, t in others], N)
            rec[f"top{N}_k"] = k
            rec[f"top{N}_structural"] = capture(order_with(rec["rows"], 0), top, N)
            rec[f"top{N}_capture_change"] = capture(order_with(rec["rows"], k), top, N) - rec[f"top{N}_structural"]
        rec["k_fitted_on_days"] = len(others)


# ---------------------------------------------------------------- leaderboard
def leaderboard(history):
    names = sorted({n for h in history for n in h["lines"]})
    out = {"version": VERSION, "written_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "days": [h["day"] for h in history], "top_n": TOPN,
           "rule": "structural top 20; miss = real rank - structural rank; capture change = re-order by structural rank "
                   "- k*z(score), k fitted leave-one-day-out, minus structural order; day-bootstrap 95% intervals; "
                   "late lines are never scored",
           "lines": {}}
    for name in names:
        recs = [(h, h["lines"][name]) for h in history if name in h["lines"]]
        on = [(h, r) for h, r in recs if r["status"] == "on_time"]
        late = [h["day"] for h, r in recs if r["status"] == "late"]
        row = {"kind": recs[0][1].get("kind"), "n_days_present": len(recs), "n_days_on_time": len(on),
               "on_time_freeze_rate": round(len(on) / len(recs), 3) if recs else None, "late_days": late,
               "n_days_scored": sum(1 for _, r in on if r.get("spearman_with_miss") is not None),
               "n_launches": sum(r.get("n_scored", 0) for _, r in on if r.get("spearman_with_miss") is not None),
               "spearman_with_miss": boot([r.get("spearman_with_miss") for _, r in on
                                           if r.get("spearman_with_miss") is not None])}
        for N in (3, 5):
            diffs, ks, base = [], [], []
            for h, r in on:
                tr = [(r2["rows"], {int(a): b for a, b in h2["real_top"].items()}) for h2, r2 in on if h2["day"] != h["day"]]
                k = fit_k(tr, N)
                top = {int(a): b for a, b in h["real_top"].items()}
                b0 = capture(order_with(r["rows"], 0), top, N)
                diffs.append(capture(order_with(r["rows"], k), top, N) - b0)
                ks.append(k)
                base.append(b0)
            row[f"top{N}_capture_change"] = boot(diffs)
            row[f"top{N}_k_by_day"] = ks
            row[f"top{N}_structural_capture"] = boot(base)
        n = row["n_days_scored"]
        row["note"] = ("no on-time day" if not on else
                       f"{n} day(s): too few to read" if n < 7 else
                       f"{n} days: top-3 capture can only see effects of about {round(100 / n * 1.0, 1)} points or more"
                       if n < 20 else "")
        out["lines"][name] = row
    return out


# ---------------------------------------------------------------- main
def days_between(a, b):
    d, e = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= e:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def load_history(store):
    hist = []
    for rel in store.list("results/calibration"):
        if rel.endswith("/residual.json"):
            h = store.read_json(rel)
            if h and h.get("version") == VERSION:
                hist.append(h)
    return sorted(hist, key=lambda h: h["day"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--day")
    g.add_argument("--backfill", help="FIRST:LAST (PT days)")
    g.add_argument("--leaderboard-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    store = Store(a.root)
    if vader("ok") is None:
        print("warning: vaderSentiment is not installed; the sentiment lines are skipped "
              "(pip install vaderSentiment)", file=sys.stderr)

    history = load_history(store)
    todo = [] if a.leaderboard_only else ([a.day] if a.day else list(days_between(*a.backfill.split(":"))))
    status = {}
    for day in todo:
        res, why = read_day(store, day)
        if res is None:
            status[day] = why
            print(f"{day}: skipped ({why})")
            continue
        history = [h for h in history if h["day"] != day] + [res]
        history.sort(key=lambda h: h["day"])
        status[day] = "ok"
    # capture per day with k fitted on every other day so far
    for h in history:
        if h["day"] in todo:
            add_capture(h, history)
            if not a.dry_run:
                store.write_json(f"results/calibration/{h['day']}/residual.json", h)
            n_on = sum(1 for r in h["lines"].values() if r["status"] == "on_time")
            n_late = sum(1 for r in h["lines"].values() if r["status"] == "late")
            print(f"{h['day']}: {n_on} line(s) on time, {n_late} late")
    lb = leaderboard(history)
    if not a.dry_run:
        store.write_json("results/calibration/residual_leaderboard.json", lb)
    for name, r in lb["lines"].items():
        s, c3 = r["spearman_with_miss"], r["top3_capture_change"]
        fmt = lambda b: "n/a" if b["mean"] is None else (f"{b['mean']:+.3f}" + (f" [{b['lo']:+.3f}, {b['hi']:+.3f}]" if b["lo"] is not None else ""))
        print(f"{name:40s} days {r['n_days_scored']:>2} launches {r['n_launches']:>4} on-time {r['on_time_freeze_rate']} "
              f"rho {fmt(s)} top3 {fmt(c3)} top5 {fmt(r['top5_capture_change'])}")
    if a.day and status.get(a.day) != "ok":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
