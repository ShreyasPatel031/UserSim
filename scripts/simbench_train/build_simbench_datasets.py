#!/usr/bin/env python3
"""Build SimBench-format training datasets from multiple survey distribution sources.

Sources:
  - SocSci210: Cell-level histograms from TESS studies (seen studies only)
  - WVS: World Values Survey aggregates from Cao et al. (SimLLMCultureDist)
  - SubPOP: Pew ATP distributions (requires gated HF access, skipped if unavailable)

Outputs (to GCS):
  - armA_humandist/train.jsonl: Human distribution data in SimBench format
  - armA_humandist/val.jsonl: Validation split (10%)
  - distill_pool.jsonl: Prompts for teacher distillation
  - dedup_report.json: Deduplication statistics

Hard rules:
  - Never train on SimBench items (pilot497 + heldout1426 + full13510)
  - Deduplicate via 6-gram overlap >= 0.5 OR embedding cosine >= 0.87
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

# Add eval kit to path for official prompt generation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "simbench_eval_kit"))

SIMBENCH_ITEMS_PATH = Path(__file__).parent.parent.parent / "simbench_eval_kit" / "items"


def load_simbench_items():
    """Load all SimBench items for deduplication."""
    from simbench_common import read_items
    
    items = []
    for name in ("pilot497", "heldout1426"):
        path = SIMBENCH_ITEMS_PATH / f"{name}.jsonl"
        if path.exists():
            items.extend(read_items(path))
    
    # Also load full13510 if available
    full_path = SIMBENCH_ITEMS_PATH / "full13510.jsonl.gz"
    if full_path.exists():
        items.extend(read_items(full_path))
    
    return items


def generate_prompt_grouped(question: str, options: list[tuple[str, str]], group_desc: str) -> dict:
    """Generate SimBench-style Grouped prompt (question names the demographic group).
    
    Returns dict with:
        system: Group description
        user_token_prob: Token probability format prompt
        user_verbalized: Verbalized distribution format prompt
    """
    system = f"You are a group of individuals with these shared characteristics:\n{group_desc}"
    
    options_text = "\n".join(f"({opt[0]}): {opt[1]}" for opt in options)
    keys = [opt[0] for opt in options]
    
    user_token_prob = (
        f"**Question**: {question}\n\n"
        f"Options:\n{options_text}\n"
        f"Do not provide any explanation, only answer with one of the following options: "
        f"{', '.join(keys)}.\n**Answer**: ("
    )
    
    json_format = "{" + ", ".join(f'"{k}": X' for k in keys) + "}"
    user_verbalized = (
        f"**Question**: {question}\n\n"
        f"Options:\n{options_text}\n"
        f"\nEstimate what percentage of your group would choose each option. "
        f"Follow these rules:\n"
        f"1. Use whole numbers from 0 to 100\n"
        f"2. Ensure the percentages sum to exactly 100\n"
        f"3. Only include the numbers (no % symbols)\n"
        f"4. Use this exact valid JSON format: {json_format} and do NOT include anything else.\n"
        f"5. Only output your final answer and nothing else. No explanations or intermediate steps are needed.\n"
        f"Replace X with your estimated percentages for each option.\n"
        f"**Answer**:"
    )
    
    return {
        "system": system,
        "user_token_prob": user_token_prob,
        "user_verbalized": user_verbalized,
        "keys": keys,
    }


def generate_prompt_pop(question: str, options: list[tuple[str, str]], pop_desc: str) -> dict:
    """Generate SimBench-style Pop prompt (general population of source survey)."""
    return generate_prompt_grouped(question, options, pop_desc)


def dist_to_soft_label(dist: dict[str, float], keys: list[str]) -> list[float]:
    """Convert distribution dict to normalized probability array over keys."""
    probs = [float(dist.get(k, 0.0)) for k in keys]
    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]
    else:
        probs = [1.0 / len(keys)] * len(keys)
    return probs


def build_simbench_item(
    question: str,
    options: list[tuple[str, str]],
    distribution: dict[str, float],
    group_desc: str,
    source: str,
    source_id: str,
    format_style: str = "grouped",
) -> dict:
    """Build a single SimBench-format training item."""
    if format_style == "grouped":
        prompts = generate_prompt_grouped(question, options, group_desc)
    else:
        prompts = generate_prompt_pop(question, options, group_desc)
    
    keys = prompts["keys"]
    human_probs = dist_to_soft_label(distribution, keys)
    
    # Build verbalized JSON target
    human_pct = [round(p * 100) for p in human_probs]
    # Adjust to sum to 100
    diff = 100 - sum(human_pct)
    if diff != 0:
        max_idx = human_pct.index(max(human_pct))
        human_pct[max_idx] += diff
    
    verbalized_target = json.dumps({k: v for k, v in zip(keys, human_pct)})
    
    return {
        "source": source,
        "source_id": source_id,
        "format": format_style,
        "system": prompts["system"],
        "user_token_prob": prompts["user_token_prob"],
        "user_verbalized": prompts["user_verbalized"],
        "keys": keys,
        "human": human_probs,
        "verbalized_target": verbalized_target,
        "soft_label": human_probs,  # First-token soft-label (same as human for now)
        "question_text": question,  # For dedup
    }


def load_socsci210_histograms(max_per_cell: int = 0, seen_only: bool = True) -> list[dict]:
    """Load SocSci210 and compute cell-level answer histograms.
    
    A cell is (study_id, condition_num, task_num).
    For each cell, we aggregate all participant responses into a distribution.
    """
    os.environ['HF_HOME'] = '/home/ubuntu/.cache/huggingface'
    os.environ['HF_DATASETS_CACHE'] = '/home/ubuntu/.cache/huggingface/datasets'
    
    from datasets import load_dataset
    
    # Load participant mapping to identify seen/unseen studies
    mapping_path = Path("/workspace/data/fm_baselines/SocSci210_meta/metadata/participant_mapping.json")
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text())
        seen_studies = set(mapping["seen"])
        unseen_studies = set(mapping["unseen"])
    else:
        print("Warning: participant_mapping.json not found, loading from HF")
        from huggingface_hub import hf_hub_download
        path = hf_hub_download("socratesft/SocSci210", "metadata/participant_mapping.json", repo_type="dataset")
        mapping = json.loads(Path(path).read_text())
        seen_studies = set(mapping["seen"])
        unseen_studies = set(mapping["unseen"])
    
    print(f"Loading SocSci210 (seen={len(seen_studies)}, unseen={len(unseen_studies)} studies)")
    
    # Load dataset
    ds = load_dataset("socratesft/SocSci210", split="train")
    
    # Group by cell
    cells = defaultdict(list)
    for row in ds:
        study_id = row["study_id"]
        if seen_only and study_id not in seen_studies:
            continue
        if study_id in unseen_studies:
            continue
        
        cell_key = (study_id, str(row["condition_num"]), str(row["task_num"]))
        cells[cell_key].append(row)
    
    print(f"Found {len(cells)} cells from SocSci210")
    
    # Build histograms
    items = []
    for cell_key, rows in cells.items():
        study_id, cond, task = cell_key
        
        # Aggregate responses
        responses = [str(r["response"]) for r in rows]
        response_counts = Counter(responses)
        total = sum(response_counts.values())
        
        if total < 5:  # Skip cells with too few responses
            continue
        
        # Get unique responses as options
        unique_responses = sorted(response_counts.keys())
        if len(unique_responses) < 2:  # Skip single-response cells
            continue
        
        # Use letter labels for options
        letters = "ABCDEFGHIJ"
        if len(unique_responses) > len(letters):
            continue
        
        options = [(letters[i], resp) for i, resp in enumerate(unique_responses)]
        distribution = {letters[i]: (response_counts[resp] / total) * 100 
                        for i, resp in enumerate(unique_responses)}
        
        # Extract question from stimuli
        sample_row = rows[0]
        question = sample_row["stimuli"]
        
        # Build group description from demographics (use population-level)
        group_desc = "You are a participant in a TESS (Time-sharing Experiments for the Social Sciences) survey."
        
        items.append({
            "question": question,
            "options": options,
            "distribution": distribution,
            "group_desc": group_desc,
            "source": "socsci210",
            "source_id": f"socsci210|{study_id}|{cond}|{task}",
        })
    
    print(f"Built {len(items)} SocSci210 cell histograms")
    return items


def load_wvs_data() -> list[dict]:
    """Load World Values Survey data from Cao et al."""
    wvs_path = Path("/tmp/SimLLMCultureDist/dataset/sft_wvs_train.json")
    if not wvs_path.exists():
        print("WVS data not found, skipping")
        return []
    
    with open(wvs_path) as f:
        data = json.load(f)
    
    print(f"Loaded {len(data)} WVS items")
    
    items = []
    for row in data:
        # Parse options
        options = []
        for opt_text in row["options"]:
            # Format: "(A)Very important"
            match = re.match(r"\(([A-Z])\)(.*)", opt_text)
            if match:
                options.append((match.group(1), match.group(2).strip()))
        
        if not options:
            continue
        
        # Extract country from instruction
        country_match = re.search(r"from (\w+(?:\s+\w+)*) answer", row["instruction"])
        country = country_match.group(1) if country_match else "Unknown"
        
        # Clean question
        question = row["input"]
        question = question.replace("\nHere are the options: \n", "").strip()
        
        # Build group description
        group_desc = f"You are from {country}."
        
        items.append({
            "question": question,
            "options": options,
            "distribution": row["options_dist"],
            "group_desc": group_desc,
            "source": "wvs",
            "source_id": f"wvs|{row['id']}|{country}",
        })
    
    return items


def tokenize_for_overlap(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric words."""
    return re.findall(r'[a-z0-9]+', text.lower())


def compute_ngram_overlap(text1: str, text2: str, n: int = 6) -> float:
    """Compute n-gram containment: fraction of text1's n-grams in text2."""
    toks1 = tokenize_for_overlap(text1)
    toks2 = tokenize_for_overlap(text2)
    
    if len(toks1) < n:
        return 0.0
    
    grams1 = {tuple(toks1[i:i+n]) for i in range(len(toks1) - n + 1)}
    grams2 = {tuple(toks2[i:i+n]) for i in range(len(toks2) - n + 1)}
    
    if not grams1:
        return 0.0
    
    return len(grams1 & grams2) / len(grams1)


def build_embedding_index(texts: list[str], model_name: str = "all-MiniLM-L6-v2"):
    """Build sentence embedding index for cosine similarity dedup."""
    try:
        import os
        os.environ['SENTENCE_TRANSFORMERS_HOME'] = '/home/ubuntu/.cache/sentence_transformers'
        os.makedirs('/home/ubuntu/.cache/sentence_transformers', exist_ok=True)
        
        from sentence_transformers import SentenceTransformer
        
        model = SentenceTransformer(model_name)
        embeddings = model.encode(texts, show_progress_bar=True)
        return embeddings
    except Exception as e:
        print(f"Warning: Could not build embedding index: {e}")
        return None


def deduplicate_against_simbench(
    items: list[dict],
    simbench_items: list[dict],
    ngram_threshold: float = 0.5,
    cosine_threshold: float = 0.87,
) -> tuple[list[dict], dict]:
    """Remove items that overlap with SimBench test set.
    
    Uses two methods:
    1. 6-gram containment >= ngram_threshold
    2. Embedding cosine similarity >= cosine_threshold
    
    Returns (clean_items, dedup_report)
    """
    report = {
        "total_input": len(items),
        "simbench_items": len(simbench_items),
        "removed_by_ngram": 0,
        "removed_by_embedding": 0,
        "removed_per_source": defaultdict(int),
        "retained": 0,
    }
    
    # Extract SimBench questions
    simbench_questions = []
    for it in simbench_items:
        # Extract question from user_verbalized (before "Estimate what percentage")
        q = it.get("user_verbalized", "")
        q = q.split("\nEstimate what percentage")[0]
        q = q.replace("**Question**: ", "")
        simbench_questions.append(q)
    
    # Build SimBench n-gram index
    print("Building SimBench n-gram index...")
    simbench_grams = []
    for q in simbench_questions:
        toks = tokenize_for_overlap(q)
        grams = {tuple(toks[i:i+6]) for i in range(len(toks) - 5)}
        simbench_grams.append(grams)
    
    all_simbench_grams = set()
    for g in simbench_grams:
        all_simbench_grams.update(g)
    
    # First pass: n-gram filtering
    ngram_clean = []
    for item in items:
        q = item.get("question_text", item.get("question", ""))
        toks = tokenize_for_overlap(q)
        if len(toks) < 6:
            ngram_clean.append(item)
            continue
        
        grams = {tuple(toks[i:i+6]) for i in range(len(toks) - 5)}
        overlap = len(grams & all_simbench_grams) / len(grams) if grams else 0
        
        if overlap >= ngram_threshold:
            report["removed_by_ngram"] += 1
            report["removed_per_source"][item["source"]] += 1
        else:
            ngram_clean.append(item)
    
    print(f"After n-gram dedup: {len(ngram_clean)} items (removed {report['removed_by_ngram']})")
    
    # Second pass: embedding similarity (if embeddings available)
    try:
        print("Building embedding index for remaining items...")
        item_texts = [it.get("question_text", it.get("question", "")) for it in ngram_clean]
        simbench_embeddings = build_embedding_index(simbench_questions)
        
        if simbench_embeddings is not None:
            item_embeddings = build_embedding_index(item_texts)
            
            if item_embeddings is not None:
                # Compute cosine similarities
                from sklearn.metrics.pairwise import cosine_similarity
                
                sims = cosine_similarity(item_embeddings, simbench_embeddings)
                max_sims = sims.max(axis=1)
                
                embedding_clean = []
                for i, item in enumerate(ngram_clean):
                    if max_sims[i] >= cosine_threshold:
                        report["removed_by_embedding"] += 1
                        report["removed_per_source"][item["source"]] += 1
                    else:
                        embedding_clean.append(item)
                
                ngram_clean = embedding_clean
                print(f"After embedding dedup: {len(ngram_clean)} items (removed {report['removed_by_embedding']})")
    except Exception as e:
        print(f"Warning: Embedding dedup failed: {e}")
    
    report["retained"] = len(ngram_clean)
    report["removed_per_source"] = dict(report["removed_per_source"])
    
    return ngram_clean, report


def build_distill_pool(items: list[dict], target_size: int = 15000) -> list[dict]:
    """Build distillation prompt pool from arm A questions plus diverse groups."""
    pool = []
    
    # Use existing items as base
    for item in items:
        pool.append({
            "source": item["source"],
            "source_id": item["source_id"],
            "system": item["system"],
            "user_verbalized": item["user_verbalized"],
            "keys": item["keys"],
        })
    
    # TODO: Add diverse group variations
    # For now, just return deduplicated items up to target size
    
    if len(pool) > target_size:
        # Sample uniformly
        indices = np.random.default_rng(42).choice(len(pool), target_size, replace=False)
        pool = [pool[i] for i in indices]
    
    return pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="/tmp/simbench_train_data")
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-socsci", action="store_true")
    parser.add_argument("--skip-wvs", action="store_true")
    args = parser.parse_args()
    
    np.random.seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load SimBench items for deduplication
    print("Loading SimBench items for deduplication...")
    simbench_items = load_simbench_items()
    print(f"Loaded {len(simbench_items)} SimBench items")
    
    # Collect all source items
    all_items = []
    
    # Load SocSci210
    if not args.skip_socsci:
        socsci_items = load_socsci210_histograms()
        all_items.extend(socsci_items)
    
    # Load WVS
    if not args.skip_wvs:
        wvs_items = load_wvs_data()
        all_items.extend(wvs_items)
    
    print(f"Total raw items: {len(all_items)}")
    
    # Convert to SimBench format
    print("Converting to SimBench format...")
    simbench_items_train = []
    for item in all_items:
        # Generate both Grouped and Pop style
        for style in ["grouped", "pop"]:
            simbench_item = build_simbench_item(
                question=item["question"],
                options=item["options"],
                distribution=item["distribution"],
                group_desc=item["group_desc"],
                source=item["source"],
                source_id=item["source_id"],
                format_style=style,
            )
            simbench_items_train.append(simbench_item)
    
    print(f"Generated {len(simbench_items_train)} SimBench-format items")
    
    # Deduplicate
    print("Deduplicating against SimBench test set...")
    clean_items, dedup_report = deduplicate_against_simbench(
        simbench_items_train, simbench_items
    )
    
    # Split train/val
    n_val = int(len(clean_items) * args.val_ratio)
    indices = np.random.permutation(len(clean_items))
    val_items = [clean_items[i] for i in indices[:n_val]]
    train_items = [clean_items[i] for i in indices[n_val:]]
    
    # Build distill pool
    distill_pool = build_distill_pool(clean_items, target_size=15000)
    
    # Save outputs
    arm_a_dir = output_dir / "armA_humandist"
    arm_a_dir.mkdir(parents=True, exist_ok=True)
    
    with open(arm_a_dir / "train.jsonl", "w") as f:
        for item in train_items:
            del item["question_text"]  # Remove dedup field
            f.write(json.dumps(item) + "\n")
    
    with open(arm_a_dir / "val.jsonl", "w") as f:
        for item in val_items:
            del item["question_text"]
            f.write(json.dumps(item) + "\n")
    
    with open(output_dir / "distill_pool.jsonl", "w") as f:
        for item in distill_pool:
            f.write(json.dumps(item) + "\n")
    
    with open(output_dir / "dedup_report.json", "w") as f:
        json.dump(dedup_report, f, indent=2)
    
    # Summary
    summary = {
        "train_items": len(train_items),
        "val_items": len(val_items),
        "distill_pool_items": len(distill_pool),
        "dedup": dedup_report,
        "sources": dict(Counter(it["source"] for it in train_items)),
    }
    
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    
    print("\n" + "="*60)
    print("Dataset build complete!")
    print(f"  Train: {len(train_items)}")
    print(f"  Val: {len(val_items)}")
    print(f"  Distill pool: {len(distill_pool)}")
    print(f"  Dedup removed: {dedup_report['removed_by_ngram'] + dedup_report['removed_by_embedding']}")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
