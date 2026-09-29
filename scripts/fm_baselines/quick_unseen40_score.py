#!/usr/bin/env python3
"""Quick unseen40 scoring without expensive bootstrap CIs."""
import json
from pathlib import Path
import numpy as np
from collections import defaultdict

def load_distributions(dist_file):
    cells = []
    with open(dist_file) as f:
        for line in f:
            if line.strip():
                cells.append(json.loads(line))
    return cells

def logprobs_to_probs(logprobs, temperature=1.0):
    answers = sorted(int(a) for a in logprobs.keys())
    log_vals = np.array([logprobs[str(a)] for a in answers])
    if temperature != 1.0:
        log_vals = log_vals / temperature
    probs = np.exp(log_vals - np.max(log_vals))
    probs = probs / probs.sum()
    return {a: p for a, p in zip(answers, probs)}

def apply_top_p(probs, top_p):
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

def sample_from_probs(probs, n, seed):
    answers = sorted(probs.keys())
    p_vals = np.array([probs[a] for a in answers])
    p_vals = p_vals / p_vals.sum()
    rng = np.random.default_rng(seed)
    return rng.choice(answers, size=n, p=p_vals).tolist()

def wasserstein_1d(a, b):
    a = np.sort(np.array(a, dtype=float))
    b = np.sort(np.array(b, dtype=float))
    n = 256
    qa = np.quantile(a, np.linspace(0, 1, n))
    qb = np.quantile(b, np.linspace(0, 1, n))
    return float(np.mean(np.abs(qa - qb)))

def score_model(cells, temperature=1.0, top_p=1.0, seed=42):
    study_scores = defaultdict(list)
    raw_errors = []
    clipped_errors = []
    
    for cell in cells:
        logprobs = cell["logprobs"]
        human_responses = np.array(cell["human_responses"], dtype=float)
        n = len(human_responses)
        
        probs = logprobs_to_probs(logprobs, temperature)
        if top_p < 1.0:
            probs = apply_top_p(probs, top_p)
        
        cell_seed = hash((cell["study_id"], cell["condition_num"], cell["task_num"], seed)) % (2**31)
        preds = np.array(sample_from_probs(probs, n, cell_seed), dtype=float)
        
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
    
    return {"wasserstein": w_mean, "accuracy_raw": acc_raw, "accuracy_clipped": acc_clip, "n_studies": len(per_study), "per_study": per_study}

def fit_temperature(cells, t_range=(0.1, 10.0), n_points=30, seed=42):
    temps = np.logspace(np.log10(t_range[0]), np.log10(t_range[1]), n_points)
    best_t, best_w = 1.0, float("inf")
    
    for t in temps:
        result = score_model(cells, temperature=t, seed=seed)
        if result["wasserstein"] is not None and result["wasserstein"] < best_w:
            best_w = result["wasserstein"]
            best_t = t
    
    return best_t, best_w

def main():
    import sys
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "unseen40_results"
    
    print("Loading distributions...")
    models = {}
    for name in ["zero-shot", "checkpoint-600", "dpo-240"]:
        path = f"{results_dir}/{name}/cell_distributions.jsonl"
        models[name] = load_distributions(path)
        print(f"  {name}: {len(models[name])} cells")

    results = {}

    for name, cells in models.items():
        print(f"\n{'='*60}")
        print(f"Model: {name}")
        print(f"{'='*60}")
        
        t1 = score_model(cells, temperature=1.0)
        print(f"T=1.0: W={t1['wasserstein']:.4f}, raw={100*t1['accuracy_raw']:.2f}%, clipped={100*t1['accuracy_clipped']:.2f}%")
        
        t06 = score_model(cells, temperature=0.6, top_p=0.9)
        print(f"T=0.6, top_p=0.9: W={t06['wasserstein']:.4f}, raw={100*t06['accuracy_raw']:.2f}%, clipped={100*t06['accuracy_clipped']:.2f}%")
        
        if name == "zero-shot":
            print(f"  Reference (gen-based): W=0.215, raw=67.0%, clipped=73.2%")
            w_diff = abs(t06["wasserstein"] - 0.215)
            acc_diff = abs(100*t06["accuracy_clipped"] - 73.2)
            print(f"  Difference: W={w_diff:.4f}, clipped acc={acc_diff:.1f}pp")
        
        best_t, best_w = fit_temperature(cells)
        fitted = score_model(cells, temperature=best_t)
        print(f"Fitted T={best_t:.3f}: W={fitted['wasserstein']:.4f}, raw={100*fitted['accuracy_raw']:.2f}%, clipped={100*fitted['accuracy_clipped']:.2f}%")
        
        results[name] = {
            "t1": t1,
            "calibration": t06,
            "fitted_t": best_t,
            "fitted": fitted
        }

    print(f"\n{'='*60}")
    print("SUMMARY TABLE")
    print(f"{'='*60}")
    print(f"{'Model':<15} {'T=1 W':>10} {'T=0.6 W':>10} {'Fit T':>8} {'Fit W':>10} {'Clip Acc':>10}")
    print("-" * 70)
    for name in ["zero-shot", "checkpoint-600", "dpo-240"]:
        r = results[name]
        print(f"{name:<15} {r['t1']['wasserstein']:>10.4f} {r['calibration']['wasserstein']:>10.4f} {r['fitted_t']:>8.3f} {r['fitted']['wasserstein']:>10.4f} {100*r['fitted']['accuracy_clipped']:>9.2f}%")

    with open(f"{results_dir}/quick_comparison.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {results_dir}/quick_comparison.json")

if __name__ == "__main__":
    main()
