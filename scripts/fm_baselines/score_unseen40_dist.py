#!/usr/bin/env python3
"""Re-score unseen-40 stored distributions with temperature/top_p settings.

This script does NOT need a GPU - it works on stored distributions from eval_unseen40_dist.py.

Features:
1. Calibration check: Reproduce reference zero-shot numbers (W=0.215, 67.0% raw, 73.2% clipped)
   using T=0.6, top_p=0.9 sampling
2. Cross-fitted temperature: Fit T on half A, apply to half B, swap and report
3. Report multiple temperature settings for comparison

Usage:
  python score_unseen40_dist.py --results-dir ./results --models zero-shot checkpoint-600 dpo-240
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats


def load_distributions(dist_file: Path) -> list[dict]:
    """Load cell distributions from a JSONL file."""
    cells = []
    with dist_file.open() as f:
        for line in f:
            if line.strip():
                cells.append(json.loads(line))
    return cells


def logprobs_to_probs(logprobs: dict[str, float], temperature: float = 1.0) -> dict[int, float]:
    """Convert logprobs to probabilities with optional temperature scaling."""
    answers = sorted(int(a) for a in logprobs.keys())
    log_vals = np.array([logprobs[str(a)] for a in answers])
    
    if temperature != 1.0:
        log_vals = log_vals / temperature
    
    probs = np.exp(log_vals - np.max(log_vals))
    probs = probs / probs.sum()
    
    return {a: p for a, p in zip(answers, probs)}


def apply_top_p(probs: dict[int, float], top_p: float) -> dict[int, float]:
    """Apply nucleus (top-p) sampling by zeroing out low-probability options."""
    if top_p >= 1.0:
        return probs
    
    answers = sorted(probs.keys())
    p_vals = np.array([probs[a] for a in answers])
    sorted_idx = np.argsort(p_vals)[::-1]
    cumsum = np.cumsum(p_vals[sorted_idx])
    cutoff_idx = np.searchsorted(cumsum, top_p) + 1
    
    mask = np.zeros_like(p_vals)
    mask[sorted_idx[:cutoff_idx]] = 1.0
    p_vals = p_vals * mask
    p_vals = p_vals / p_vals.sum()
    
    return {a: p for a, p in zip(answers, p_vals)}


def sample_from_probs(probs: dict[int, float], n: int, seed: int) -> list[int]:
    """Sample n values from the probability distribution."""
    answers = sorted(probs.keys())
    p_vals = np.array([probs[a] for a in answers])
    p_vals = p_vals / p_vals.sum()
    
    rng = np.random.default_rng(seed)
    samples = rng.choice(answers, size=n, p=p_vals)
    return samples.tolist()


def wasserstein_1d(a: np.ndarray, b: np.ndarray) -> float:
    """Wasserstein-1 distance using quantile matching."""
    a = np.sort(a.astype(float))
    b = np.sort(b.astype(float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))


def score_model(
    cells: list[dict],
    temperature: float = 1.0,
    top_p: float = 1.0,
    method: str = "sample",
    seed: int = 42
) -> dict:
    """Score a model's distributions with given temperature and top_p."""
    study_scores: dict[str, list[float]] = defaultdict(list)
    raw_errors = []
    clipped_errors = []
    
    for cell in cells:
        logprobs = cell["logprobs"]
        human_responses = np.array(cell["human_responses"], dtype=float)
        n = len(human_responses)
        
        probs = logprobs_to_probs(logprobs, temperature)
        if top_p < 1.0:
            probs = apply_top_p(probs, top_p)
        
        if method == "sample":
            cell_seed = hash((cell["study_id"], cell["condition_num"], cell["task_num"], seed)) % (2**31)
            preds = np.array(sample_from_probs(probs, n, cell_seed), dtype=float)
        else:
            answers = sorted(probs.keys())
            p_vals = np.array([probs[a] for a in answers])
            ev = float(np.sum(np.array(answers) * p_vals))
            preds = np.full(n, ev)
        
        rmin, rmax = float(human_responses.min()), float(human_responses.max())
        if rmax <= rmin:
            continue
        
        h_s = (human_responses - rmin) / (rmax - rmin)
        m_s = (preds - rmin) / (rmax - rmin)
        m_s_clip = np.clip(m_s, 0.0, 1.0)
        
        w = wasserstein_1d(h_s, m_s_clip)
        study_scores[cell["study_id"]].append(w)
        
        raw_errors.extend(np.abs(h_s - m_s).tolist())
        clipped_errors.extend(np.abs(h_s - m_s_clip).tolist())
    
    per_study = {s: float(np.mean(v)) for s, v in study_scores.items() if v}
    w_mean = float(np.mean(list(per_study.values()))) if per_study else None
    acc_raw = 1 - float(np.mean(raw_errors)) if raw_errors else None
    acc_clip = 1 - float(np.mean(clipped_errors)) if clipped_errors else None
    
    return {
        "wasserstein": w_mean,
        "accuracy_raw": acc_raw,
        "accuracy_clipped": acc_clip,
        "per_study": per_study,
        "n_studies": len(per_study),
    }


def fit_temperature(
    cells: list[dict],
    study_ids: set[str],
    t_range: tuple[float, float] = (0.1, 10.0),
    n_points: int = 50,
    seed: int = 42
) -> tuple[float, float]:
    """Fit temperature on a subset of studies to minimize W."""
    subset = [c for c in cells if c["study_id"] in study_ids]
    
    temps = np.logspace(np.log10(t_range[0]), np.log10(t_range[1]), n_points)
    best_t, best_w = 1.0, float("inf")
    
    for t in temps:
        result = score_model(subset, temperature=t, seed=seed)
        if result["wasserstein"] is not None and result["wasserstein"] < best_w:
            best_w = result["wasserstein"]
            best_t = t
    
    return best_t, best_w


def bootstrap_ci(
    cells: list[dict],
    temperature: float,
    n_boot: int = 1000,
    seed: int = 42
) -> dict:
    """Compute bootstrap 95% CI for W by resampling studies."""
    studies = list(set(c["study_id"] for c in cells))
    study_to_cells = defaultdict(list)
    for c in cells:
        study_to_cells[c["study_id"]].append(c)
    
    rng = np.random.default_rng(seed)
    w_samples = []
    
    for i in range(n_boot):
        boot_studies = rng.choice(studies, size=len(studies), replace=True)
        boot_cells = []
        for s in boot_studies:
            boot_cells.extend(study_to_cells[s])
        result = score_model(boot_cells, temperature=temperature, seed=seed + i)
        if result["wasserstein"] is not None:
            w_samples.append(result["wasserstein"])
    
    w_samples = np.array(w_samples)
    return {
        "mean": float(np.mean(w_samples)),
        "ci_low": float(np.percentile(w_samples, 2.5)),
        "ci_high": float(np.percentile(w_samples, 97.5)),
    }


def paired_bootstrap_delta(
    cells_ref: list[dict],
    cells_test: list[dict],
    t_ref: float,
    t_test: float,
    n_boot: int = 1000,
    seed: int = 42
) -> dict:
    """Compute paired per-study delta with bootstrap CI."""
    studies_ref = set(c["study_id"] for c in cells_ref)
    studies_test = set(c["study_id"] for c in cells_test)
    studies = list(studies_ref & studies_test)
    
    ref_by_study = defaultdict(list)
    test_by_study = defaultdict(list)
    for c in cells_ref:
        ref_by_study[c["study_id"]].append(c)
    for c in cells_test:
        test_by_study[c["study_id"]].append(c)
    
    def compute_delta():
        deltas = []
        for s in studies:
            ref_result = score_model(ref_by_study[s], temperature=t_ref, seed=seed)
            test_result = score_model(test_by_study[s], temperature=t_test, seed=seed)
            if ref_result["wasserstein"] is not None and test_result["wasserstein"] is not None:
                deltas.append(test_result["wasserstein"] - ref_result["wasserstein"])
        return np.mean(deltas) if deltas else None
    
    point_delta = compute_delta()
    
    rng = np.random.default_rng(seed)
    delta_samples = []
    for i in range(n_boot):
        boot_studies = rng.choice(studies, size=len(studies), replace=True)
        deltas = []
        for s in boot_studies:
            ref_result = score_model(ref_by_study[s], temperature=t_ref, seed=seed + i)
            test_result = score_model(test_by_study[s], temperature=t_test, seed=seed + i)
            if ref_result["wasserstein"] is not None and test_result["wasserstein"] is not None:
                deltas.append(test_result["wasserstein"] - ref_result["wasserstein"])
        if deltas:
            delta_samples.append(np.mean(deltas))
    
    delta_samples = np.array(delta_samples)
    return {
        "delta": point_delta,
        "ci_low": float(np.percentile(delta_samples, 2.5)) if len(delta_samples) > 0 else None,
        "ci_high": float(np.percentile(delta_samples, 97.5)) if len(delta_samples) > 0 else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True, help="Directory containing model results")
    ap.add_argument("--models", nargs="+", required=True, help="Model names to compare")
    ap.add_argument("--out", default="./comparison_results.json", help="Output file")
    ap.add_argument("--n-boot", type=int, default=1000, help="Number of bootstrap samples")
    ap.add_argument("--seed", type=int, default=0, help="Random seed for study split")
    args = ap.parse_args()
    
    results_dir = Path(args.results_dir)
    
    model_cells = {}
    for name in args.models:
        dist_file = results_dir / name / "cell_distributions.jsonl"
        if not dist_file.exists():
            print(f"Warning: {dist_file} not found, skipping {name}")
            continue
        model_cells[name] = load_distributions(dist_file)
        print(f"Loaded {name}: {len(model_cells[name])} cells")
    
    if not model_cells:
        raise SystemExit("No valid model results found")
    
    all_studies = set()
    for cells in model_cells.values():
        all_studies.update(c["study_id"] for c in cells)
    all_studies = sorted(all_studies)
    print(f"\nTotal studies: {len(all_studies)}")
    
    rng = np.random.default_rng(args.seed)
    shuffled = rng.permutation(all_studies).tolist()
    half_a = set(shuffled[:len(shuffled)//2])
    half_b = set(shuffled[len(shuffled)//2:])
    print(f"Split: A={len(half_a)} studies, B={len(half_b)} studies")
    print(f"Half A: {sorted(half_a)[:5]}...")
    print(f"Half B: {sorted(half_b)[:5]}...")
    
    results = {
        "study_split": {"half_a": sorted(half_a), "half_b": sorted(half_b), "seed": args.seed},
        "models": {},
    }
    
    ref_model = args.models[0]
    print(f"\nReference model: {ref_model}")
    
    for name, cells in model_cells.items():
        print(f"\n{'='*60}")
        print(f"Model: {name}")
        print(f"{'='*60}")
        
        model_result = {"name": name}
        
        t1_result = score_model(cells, temperature=1.0)
        print(f"T=1.0: W={t1_result['wasserstein']:.4f}, "
              f"raw={100*t1_result['accuracy_raw']:.2f}%, clipped={100*t1_result['accuracy_clipped']:.2f}%")
        model_result["t1"] = t1_result
        
        t06_result = score_model(cells, temperature=0.6, top_p=0.9)
        print(f"T=0.6, top_p=0.9: W={t06_result['wasserstein']:.4f}, "
              f"raw={100*t06_result['accuracy_raw']:.2f}%, clipped={100*t06_result['accuracy_clipped']:.2f}%")
        model_result["calibration_check"] = {
            "temperature": 0.6,
            "top_p": 0.9,
            **t06_result
        }
        
        if name == ref_model:
            print(f"\n  Reference zero-shot (generation-based): W=0.215, raw=67.0%, clipped=73.2%")
            w_diff = abs(t06_result['wasserstein'] - 0.215)
            acc_diff = abs(100*t06_result['accuracy_clipped'] - 73.2)
            print(f"  Difference: W={w_diff:.4f}, clipped acc={acc_diff:.1f}pp")
            model_result["calibration_check"]["reference"] = {
                "wasserstein": 0.215,
                "accuracy_raw": 0.67,
                "accuracy_clipped": 0.732,
            }
            model_result["calibration_check"]["within_tolerance"] = (w_diff < 0.02 and acc_diff < 2.0)
        
        cells_a = [c for c in cells if c["study_id"] in half_a]
        cells_b = [c for c in cells if c["study_id"] in half_b]
        
        t_fit_a, w_fit_a = fit_temperature(cells, half_a)
        t_fit_b, w_fit_b = fit_temperature(cells, half_b)
        print(f"\n  Fit T on A: T={t_fit_a:.3f}, in-sample W={w_fit_a:.4f}")
        print(f"  Fit T on B: T={t_fit_b:.3f}, in-sample W={w_fit_b:.4f}")
        
        cross_a_to_b = score_model(cells_b, temperature=t_fit_a)
        cross_b_to_a = score_model(cells_a, temperature=t_fit_b)
        print(f"  Apply T_A to B: W={cross_a_to_b['wasserstein']:.4f}")
        print(f"  Apply T_B to A: W={cross_b_to_a['wasserstein']:.4f}")
        
        cross_w = (cross_a_to_b["wasserstein"] + cross_b_to_a["wasserstein"]) / 2
        print(f"  Cross-fitted W (mean): {cross_w:.4f}")
        
        t_mean = (t_fit_a + t_fit_b) / 2
        full_at_mean_t = score_model(cells, temperature=t_mean)
        print(f"  Full data at mean T={t_mean:.3f}: W={full_at_mean_t['wasserstein']:.4f}")
        
        model_result["cross_fitted"] = {
            "t_fit_a": t_fit_a,
            "t_fit_b": t_fit_b,
            "w_cross_a_to_b": cross_a_to_b["wasserstein"],
            "w_cross_b_to_a": cross_b_to_a["wasserstein"],
            "w_cross_mean": cross_w,
            "t_mean": t_mean,
            "w_at_mean_t": full_at_mean_t["wasserstein"],
            "accuracy_raw_at_mean_t": full_at_mean_t["accuracy_raw"],
            "accuracy_clipped_at_mean_t": full_at_mean_t["accuracy_clipped"],
        }
        
        results["models"][name] = model_result
    
    print(f"\n{'='*60}")
    print("PAIRED DELTAS vs ZERO-SHOT")
    print(f"{'='*60}")
    
    if ref_model in model_cells:
        ref_cells = model_cells[ref_model]
        ref_t = results["models"][ref_model]["cross_fitted"]["t_mean"]
        
        for name, cells in model_cells.items():
            if name == ref_model:
                continue
            
            test_t = results["models"][name]["cross_fitted"]["t_mean"]
            delta = paired_bootstrap_delta(
                ref_cells, cells, ref_t, test_t, n_boot=args.n_boot, seed=args.seed
            )
            
            print(f"\n{name} vs {ref_model}:")
            print(f"  Delta W: {delta['delta']:.4f} [{delta['ci_low']:.4f}, {delta['ci_high']:.4f}] (95% CI)")
            
            results["models"][name]["paired_delta_vs_ref"] = delta
    
    print(f"\n{'='*60}")
    print("SUMMARY TABLE")
    print(f"{'='*60}")
    
    print(f"\n{'Model':<20} {'T=1 W':>10} {'T=0.6 W':>10} {'Cross W':>10} {'Raw Acc':>10} {'Clip Acc':>10}")
    print("-" * 80)
    for name in args.models:
        if name not in results["models"]:
            continue
        m = results["models"][name]
        t1_w = m["t1"]["wasserstein"]
        t06_w = m["calibration_check"]["wasserstein"]
        cross_w = m["cross_fitted"]["w_cross_mean"]
        raw_acc = 100 * m["cross_fitted"]["accuracy_raw_at_mean_t"]
        clip_acc = 100 * m["cross_fitted"]["accuracy_clipped_at_mean_t"]
        print(f"{name:<20} {t1_w:>10.4f} {t06_w:>10.4f} {cross_w:>10.4f} {raw_acc:>9.2f}% {clip_acc:>9.2f}%")
    
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to: {args.out}")


if __name__ == "__main__":
    main()
