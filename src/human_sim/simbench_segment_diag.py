"""Why segment mixtures do not help: weights vs segment content.

For every dev case with logged segments, rescore the same segment distributions under
  model  : the shares the model gave (what the arm actually used)
  equal  : equal weights
  oracle : the convex weights that minimise TVD to the human answer (an upper bound
           for any weighting scheme over these segments; linear program)
  best1  : the single best segment
  major  : the segment with the largest share, alone
and describe the segments themselves (diversity, peakedness, coverage of the human
modal option). Bins use the same entropy cut points as the reports (0.65 / 0.84).

Usage:
  PYTHONPATH=src python -m human_sim.simbench_segment_diag
"""

from __future__ import annotations

import json
import math
from collections import defaultdict

import numpy as np
from scipy.optimize import linprog

from human_sim.simbench_ablate import OUT_DIR

TAG = "claude-haiku-4-5_p25g100s7dev10x40"
ARMS = ["Bdiag_n3_soft", "Bdiag_hybrid3", "Bdiag_agents_w"]
CUTS = (0.65, 0.84)


def _h(p: np.ndarray) -> float:
    q = p[p > 0]
    return float(-(q * np.log(q)).sum() / math.log(len(p))) if len(p) > 1 else 0.0


def _tvd(p: np.ndarray, q: np.ndarray) -> float:
    return 0.5 * float(np.abs(p - q).sum())


def oracle_weights(segs: np.ndarray, human: np.ndarray) -> np.ndarray:
    """min_w sum_j |sum_k w_k segs[k, j] - human_j|  s.t.  w >= 0, sum w = 1."""
    k, m = segs.shape
    c = np.concatenate([np.zeros(k), np.ones(m)])
    a_ub = np.block([[segs.T, -np.eye(m)], [-segs.T, -np.eye(m)]])
    b_ub = np.concatenate([human, -human])
    a_eq = np.concatenate([np.ones(k), np.zeros(m)])[None, :]
    res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=[1.0], bounds=[(0, None)] * (k + m))
    return res.x[:k] if res.success else np.full(k, 1.0 / k)


def dataset_norms(rows: list[dict]) -> dict[str, float]:
    acc = defaultdict(list)
    for r in rows:
        h = np.array(list(r["human_answer"].values()), dtype=float)
        h /= h.sum()
        acc[r["dataset_name"]].append(_tvd(h, np.full(len(h), 1.0 / len(h))))
    return {k: float(np.mean(v)) for k, v in acc.items()}


def analyse(arm: str, norms: dict | None = None) -> tuple[dict, list[dict]]:
    rows = [r for r in json.loads((OUT_DIR / f"{arm}_{TAG}.json").read_text())["rows"] if r.get("ok")]
    norms = norms or dataset_norms(rows)
    cases = []
    for r in rows:
        segs_raw = r.get("segments") or []
        keys = list(r["human_answer"].keys())
        if len(segs_raw) < 2:
            continue
        human = np.array([r["human_answer"][k] for k in keys], dtype=float)
        human /= human.sum()
        segs = np.array([[s["dist"][k] for k in keys] for s in segs_raw])
        shares = np.array([max(float(s["share"]), 0.0) for s in segs_raw])
        shares = shares / shares.sum() if shares.sum() > 0 else np.full(len(segs), 1 / len(segs))
        norm = norms[r["dataset_name"]]
        score = lambda p: 100 * (1 - _tvd(p, human) / norm)  # noqa: E731
        w_or = oracle_weights(segs, human)
        modal = int(np.argmax(human))
        pair = [_tvd(segs[a], segs[b]) for a in range(len(segs)) for b in range(a + 1, len(segs))]
        cases.append(
            {
                "i": r["i"],
                "ds": r["dataset_name"],
                "hH": _h(human),
                "S_model": score(shares @ segs),
                "S_equal": score(segs.mean(axis=0)),
                "S_oracle": score(w_or @ segs),
                "S_best1": max(score(s) for s in segs),
                "S_major": score(segs[int(np.argmax(shares))]),
                "seg_pair_tvd": float(np.mean(pair)),
                "seg_H": float(np.mean([_h(s) for s in segs])),
                "seg_top1": float(np.mean(segs.max(axis=1))),
                "mix_H": _h(shares @ segs),
                "max_share": float(shares.max()),
                "share_vs_oracle": _tvd(shares, w_or),
                "equal_vs_oracle": _tvd(np.full(len(segs), 1 / len(segs)), w_or),
                "modal_in_some_seg": bool(any(int(np.argmax(s)) == modal for s in segs)),
                "mix_modal_ok": int(np.argmax(shares @ segs)) == modal,
                "mass_on_modal_mix": float((shares @ segs)[modal]),
                "mass_on_modal_human": float(human[modal]),
                "segments": segs_raw,
                "human": dict(zip(keys, human.round(3).tolist())),
            }
        )
    return summarise(cases), cases


def summarise(cases: list[dict]) -> dict:
    def block(cs):
        m = lambda k: round(float(np.mean([c[k] for c in cs])), 3)  # noqa: E731
        return {
            "n": len(cs),
            **{k: round(float(np.mean([c[k] for c in cs])), 2) for k in ("S_model", "S_equal", "S_oracle", "S_best1", "S_major")},
            "human_H": m("hH"),
            "mix_H": m("mix_H"),
            "seg_H": m("seg_H"),
            "seg_top1": m("seg_top1"),
            "seg_pair_tvd": m("seg_pair_tvd"),
            "max_share": m("max_share"),
            "share_vs_oracle_tvd": m("share_vs_oracle"),
            "equal_vs_oracle_tvd": m("equal_vs_oracle"),
            "modal_in_some_seg": m("modal_in_some_seg"),
            "mix_modal_ok": m("mix_modal_ok"),
            "mass_on_modal_mix": m("mass_on_modal_mix"),
            "mass_on_modal_human": m("mass_on_modal_human"),
        }

    lo, hi = CUTS
    return {
        "all": block(cases),
        "low": block([c for c in cases if c["hH"] < lo]),
        "mid": block([c for c in cases if lo <= c["hH"] < hi]),
        "high": block([c for c in cases if c["hH"] >= hi]),
    }


def main() -> None:
    out = {}
    for arm in ARMS:
        summary, cases = analyse(arm)
        out[arm] = summary
        print(f"\n=== {arm} ===")
        for b, v in summary.items():
            print(b, json.dumps(v))
    (OUT_DIR / "segment_diagnosis.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
