#!/usr/bin/env python3
"""Build SimBench-format training datasets from survey distribution sources.

V2 - Fixed version with proper Pop vs Grouped format handling:
  - Pop: Distribution over ALL respondents for question+condition
  - Grouped: Demographic subgroup cells with n≥30 respondents
  - All options included (even zero-count), with text labels
  - Train/val split by QUESTION (study for SocSci210, question_id for WVS)
  - No duplicate prompts across or within splits

Sources:
  - SocSci210: Cell-level histograms from TESS studies (seen studies only)
  - WVS: World Values Survey country-level aggregates from Cao et al.

Hard rules:
  - Never train on SimBench items (dedup via 6-gram + embedding)
  - Never commit SimBench data to git
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

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "simbench_eval_kit"))

SIMBENCH_ITEMS_PATH = Path(__file__).parent.parent.parent / "simbench_eval_kit" / "items"
MIN_RESPONDENTS = 30  # Minimum n per cell


# ============================================================================
# SimBench prompt generation (official format)
# ============================================================================

def generate_simbench_prompt(
    question: str,
    options: list[tuple[str, str]],  # [(letter, label), ...]
    group_desc: str,
) -> dict:
    """Generate SimBench-style prompts (token_prob and verbalized)."""
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


def build_verbalized_target(distribution: list[float], keys: list[str]) -> str:
    """Build the JSON target string from distribution."""
    # Convert to percentages that sum to 100
    total = sum(distribution)
    if total <= 0:
        pcts = [100 // len(keys)] * len(keys)
    else:
        pcts = [round(p / total * 100) for p in distribution]
    
    # Adjust to sum exactly to 100
    diff = 100 - sum(pcts)
    if diff != 0 and pcts:
        max_idx = pcts.index(max(pcts))
        pcts[max_idx] += diff
    
    return json.dumps({k: v for k, v in zip(keys, pcts)})


# ============================================================================
# SocSci210 Processing
# ============================================================================

def parse_scale_from_stimuli(stimuli: str) -> list[tuple[str, str]]:
    """Parse response scale options from stimuli text.
    
    Many TESS questions include scale definitions like:
        "Only return 1 for Strongly approve; 2 for Somewhat approve; ..."
        "1 for 'For' or 2 for 'Against'"
    """
    options = []
    letters = "ABCDEFGHIJ"
    
    # Pattern 1: quoted labels "N for 'Label'" or "N for \"Label\""
    pattern_quoted = r"(\d+)\s+for\s+['\"]([^'\"]+)['\"]"
    matches_quoted = re.findall(pattern_quoted, stimuli, re.IGNORECASE)
    
    # Pattern 2: semicolon-separated "N for Label; N for Label"
    pattern_semi = r'(\d+)\s+for\s+([^;,\d]+?)(?:;|,|$|\.|nothing else)'
    matches_semi = re.findall(pattern_semi, stimuli, re.IGNORECASE)
    
    # Pattern 3: unquoted labels with lookahead "N for Label or N for Label"
    pattern_or = r"(\d+)\s+for\s+(\w+(?:\s+\w+)*)(?:\s+or\s+\d+|,|$|\.)"
    matches_or = re.findall(pattern_or, stimuli, re.IGNORECASE)
    
    # Use pattern that found the most matches
    all_matches = [matches_quoted, matches_semi, matches_or]
    matches = max(all_matches, key=len)
    
    # Clean up matches - dedupe by number and clean labels
    seen_nums = set()
    for num, label in matches:
        if num in seen_nums:
            continue
        seen_nums.add(num)
        label = label.strip().strip("'\"").strip()
        # Skip overly long labels or empty ones
        if not label or len(label) > 100:
            continue
        if len(options) < len(letters):
            options.append((letters[len(options)], f"{num} - {label}"))
    
    # Sort by number to maintain scale order
    try:
        options.sort(key=lambda x: int(x[1].split(' - ')[0]))
        # Re-assign letters after sorting
        options = [(letters[i], opt[1]) for i, opt in enumerate(options)]
    except ValueError:
        pass
    
    return options


def get_age_band(age: int) -> str:
    """Convert age to band."""
    if age < 25:
        return "18-24"
    elif age < 35:
        return "25-34"
    elif age < 45:
        return "35-44"
    elif age < 55:
        return "45-54"
    elif age < 65:
        return "55-64"
    else:
        return "65+"


def get_income_band(income: str) -> str:
    """Simplify income to broader bands."""
    if not income:
        return None
    income = income.lower()
    if any(x in income for x in ['under', '<10', '10-14', '15-19', '20-24', '25-29']):
        return "Under $30K"
    elif any(x in income for x in ['30-', '35-', '40-', '45-']):
        return "$30K-$50K"
    elif any(x in income for x in ['50-', '55-', '60-', '65-', '70-']):
        return "$50K-$75K"
    elif any(x in income for x in ['75-', '80-', '85-', '90-', '95-', '100-']):
        return "$75K-$150K"
    elif any(x in income for x in ['150', '175', '200', '+', 'over']):
        return "$150K+"
    return None


def simplify_education(edu: str) -> str:
    """Simplify education levels."""
    if not edu:
        return None
    edu = edu.lower()
    if 'high school' in edu or 'ged' in edu or 'less than' in edu:
        return "High school or less"
    elif 'some college' in edu or 'associate' in edu:
        return "Some college"
    elif "bachelor" in edu:
        return "Bachelor's degree"
    elif 'post grad' in edu or 'professional' in edu or 'master' in edu or 'doctor' in edu:
        return "Graduate degree"
    return None


def simplify_party(party: str) -> str:
    """Simplify party ID."""
    if not party:
        return None
    party = party.lower()
    if 'strong democrat' in party:
        return "Strong Democrat"
    elif 'democrat' in party:
        return "Democrat"
    elif 'strong republican' in party:
        return "Strong Republican"
    elif 'republican' in party:
        return "Republican"
    elif 'independent' in party or 'lean' in party or 'none' in party:
        return "Independent"
    return None


def format_socsci210_pop_desc() -> str:
    """Pop-style group description for SocSci210/TESS."""
    return "You are a participant in a Time-sharing Experiments for the Social Sciences (TESS) survey in the United States."


def format_socsci210_grouped_desc(demo_attr: str, demo_value: str) -> str:
    """Grouped-style group description for a demographic cell."""
    attr_phrases = {
        "gender": f"Your gender is {demo_value}.",
        "party_id": f"Your political affiliation is {demo_value}.",
        "age_band": f"Your age is {demo_value}.",
        "education": f"Your education level is {demo_value}.",
        "income_band": f"Your household income is {demo_value}.",
        "ideology": f"Your political ideology is {demo_value}.",
    }
    phrase = attr_phrases.get(demo_attr, f"Your {demo_attr} is {demo_value}.")
    return f"You are from the United States. {phrase}"


def load_socsci210_data(seen_only: bool = True) -> dict:
    """Load SocSci210 and build cell distributions.
    
    Returns:
        {
            (study_id, condition_num, task_num): {
                'stimuli': str,
                'responses': [resp1, resp2, ...],
                'demographics': [{...}, {...}, ...],  # per-response
            }
        }
    """
    os.environ['HF_HOME'] = '/home/ubuntu/.cache/huggingface'
    os.environ['HF_DATASETS_CACHE'] = '/home/ubuntu/.cache/huggingface/datasets'
    
    from datasets import load_dataset
    
    # Load participant mapping
    mapping_path = Path("/workspace/data/fm_baselines/SocSci210_meta/metadata/participant_mapping.json")
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text())
    else:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download("socratesft/SocSci210", "metadata/participant_mapping.json", repo_type="dataset")
        mapping = json.loads(Path(path).read_text())
    
    seen_studies = set(mapping["seen"])
    unseen_studies = set(mapping["unseen"])
    
    print(f"Loading SocSci210 (seen={len(seen_studies)}, unseen={len(unseen_studies)} studies)")
    
    ds = load_dataset("socratesft/SocSci210", split="train")
    
    # Group by cell
    cells = defaultdict(lambda: {'stimuli': None, 'responses': [], 'demographics': []})
    
    for row in ds:
        study_id = row["study_id"]
        if seen_only and study_id not in seen_studies:
            continue
        if study_id in unseen_studies:
            continue
        
        cell_key = (study_id, str(row["condition_num"]), str(row["task_num"]))
        cells[cell_key]['stimuli'] = row["stimuli"]
        cells[cell_key]['responses'].append(str(row["response"]))
        cells[cell_key]['demographics'].append(row.get("demographic", {}))
    
    print(f"Found {len(cells)} cells from SocSci210")
    return dict(cells)


def build_socsci210_items(cells: dict, min_n: int = MIN_RESPONDENTS) -> tuple[list[dict], list[dict]]:
    """Build Pop and Grouped items from SocSci210 cells.
    
    Returns (pop_items, grouped_items)
    """
    pop_items = []
    grouped_items = []
    
    # Demographics to use for grouping
    demo_extractors = {
        'gender': lambda d: d.get('gender'),
        'party_id': lambda d: simplify_party(d.get('party_id')),
        'age_band': lambda d: get_age_band(d.get('age', 0)) if d.get('age') else None,
        'education': lambda d: simplify_education(d.get('education')),
        'income_band': lambda d: get_income_band(d.get('income')),
        'ideology': lambda d: d.get('ideology'),
    }
    
    for cell_key, cell_data in cells.items():
        study_id, cond, task = cell_key
        stimuli = cell_data['stimuli']
        responses = cell_data['responses']
        demographics = cell_data['demographics']
        
        if len(responses) < min_n:
            continue
        
        # Parse options from stimuli
        scale_options = parse_scale_from_stimuli(stimuli)
        
        # Get all unique responses
        unique_responses = sorted(set(responses), key=lambda x: (len(x), x))
        
        # Build option list and response mapping
        letters = "ABCDEFGHIJ"
        resp_to_letter = {}
        
        if scale_options:
            # Check if scale_options covers all unique responses
            scale_nums = set()
            for letter, label in scale_options:
                num_match = re.match(r'(\d+)', label)
                if num_match:
                    scale_nums.add(num_match.group(1))
            
            # If scale_options covers all unique responses, use it
            if scale_nums >= set(unique_responses):
                options = scale_options
                for letter, label in scale_options:
                    num_match = re.match(r'(\d+)', label)
                    if num_match:
                        resp_to_letter[num_match.group(1)] = letter
            else:
                # Fall back to using unique_responses with scale labels if available
                scale_num_to_label = {}
                for letter, label in scale_options:
                    num_match = re.match(r'(\d+)\s*-\s*(.*)', label)
                    if num_match:
                        scale_num_to_label[num_match.group(1)] = num_match.group(2).strip()
                
                if len(unique_responses) > len(letters):
                    continue
                options = []
                for i, resp in enumerate(unique_responses):
                    if resp in scale_num_to_label:
                        options.append((letters[i], f"{resp} - {scale_num_to_label[resp]}"))
                    else:
                        options.append((letters[i], resp))
                    resp_to_letter[resp] = letters[i]
        else:
            # Use responses as options directly
            if len(unique_responses) > len(letters):
                continue
            options = [(letters[i], resp) for i, resp in enumerate(unique_responses)]
            resp_to_letter = {resp: letters[i] for i, resp in enumerate(unique_responses)}
        
        # Build distribution for POP (all respondents)
        response_counts = Counter(responses)
        total_n = len(responses)
        
        distribution = []
        for letter, label in options:
            # Find responses that map to this letter
            count = 0
            for resp, letter_mapped in resp_to_letter.items():
                if letter_mapped == letter:
                    count += response_counts.get(resp, 0)
            distribution.append(count)
        
        # Create Pop item
        prompts = generate_simbench_prompt(
            question=stimuli,
            options=options,
            group_desc=format_socsci210_pop_desc(),
        )
        
        soft_label = [d / total_n if total_n > 0 else 1/len(options) for d in distribution]
        
        pop_items.append({
            "source": "socsci210",
            "source_id": f"socsci210|{study_id}|{cond}|{task}|pop",
            "study_id": study_id,
            "format": "pop",
            "n": total_n,
            **prompts,
            "human": soft_label,
            "verbalized_target": build_verbalized_target(distribution, prompts["keys"]),
            "soft_label": soft_label,
        })
        
        # Build Grouped items (by demographic)
        for demo_attr, extractor in demo_extractors.items():
            # Group by this demographic
            demo_cells = defaultdict(lambda: {'responses': [], 'count': 0})
            
            for resp, demo in zip(responses, demographics):
                demo_value = extractor(demo or {})
                if demo_value:
                    demo_cells[demo_value]['responses'].append(resp)
                    demo_cells[demo_value]['count'] += 1
            
            # Build items for cells with enough respondents
            for demo_value, demo_data in demo_cells.items():
                if demo_data['count'] < min_n:
                    continue
                
                demo_responses = demo_data['responses']
                demo_response_counts = Counter(demo_responses)
                demo_n = len(demo_responses)
                
                demo_distribution = []
                for letter, label in options:
                    count = 0
                    for resp, letter_mapped in resp_to_letter.items():
                        if letter_mapped == letter:
                            count += demo_response_counts.get(resp, 0)
                    demo_distribution.append(count)
                
                demo_prompts = generate_simbench_prompt(
                    question=stimuli,
                    options=options,
                    group_desc=format_socsci210_grouped_desc(demo_attr, demo_value),
                )
                
                demo_soft_label = [d / demo_n if demo_n > 0 else 1/len(options) for d in demo_distribution]
                
                grouped_items.append({
                    "source": "socsci210",
                    "source_id": f"socsci210|{study_id}|{cond}|{task}|{demo_attr}|{demo_value}",
                    "study_id": study_id,
                    "format": "grouped",
                    "demographic_attr": demo_attr,
                    "demographic_value": demo_value,
                    "n": demo_n,
                    **demo_prompts,
                    "human": demo_soft_label,
                    "verbalized_target": build_verbalized_target(demo_distribution, demo_prompts["keys"]),
                    "soft_label": demo_soft_label,
                })
    
    print(f"Built {len(pop_items)} SocSci210 pop items, {len(grouped_items)} grouped items")
    return pop_items, grouped_items


# ============================================================================
# WVS Processing
# ============================================================================

def load_wvs_data() -> list[dict]:
    """Load World Values Survey data from Cao et al.
    
    WVS items are country-level aggregates. Each item is emitted ONCE
    as a Grouped item (country is the group).
    """
    wvs_path = Path("/tmp/SimLLMCultureDist/dataset/sft_wvs_train.json")
    if not wvs_path.exists():
        print("WVS data not found, skipping")
        return []
    
    with open(wvs_path) as f:
        data = json.load(f)
    
    print(f"Loaded {len(data)} WVS items")
    
    items = []
    for row in data:
        # Parse options - format: "(A)Very important"
        options = []
        for opt_text in row["options"]:
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
        
        # Group description (country is the group)
        group_desc = f"You are from {country}."
        
        prompts = generate_simbench_prompt(
            question=question,
            options=options,
            group_desc=group_desc,
        )
        
        # Build distribution (ensure all options present)
        distribution = []
        for letter, _ in options:
            dist_val = row["options_dist"].get(letter, 0.0)
            distribution.append(dist_val)
        
        total = sum(distribution)
        soft_label = [d / total if total > 0 else 1/len(options) for d in distribution]
        
        items.append({
            "source": "wvs",
            "source_id": f"wvs|{row['id']}|{country}",
            "question_id": row['id'],
            "country": country,
            "format": "grouped",  # Country is the demographic group
            "n": None,  # WVS doesn't provide per-item n in this format
            **prompts,
            "human": soft_label,
            "verbalized_target": build_verbalized_target(distribution, prompts["keys"]),
            "soft_label": soft_label,
        })
    
    return items


# ============================================================================
# Deduplication
# ============================================================================

def load_simbench_items():
    """Load all SimBench items for deduplication."""
    from simbench_common import read_items
    
    items = []
    for name in ("pilot497", "heldout1426"):
        path = SIMBENCH_ITEMS_PATH / f"{name}.jsonl"
        if path.exists():
            items.extend(read_items(path))
    
    full_path = SIMBENCH_ITEMS_PATH / "full13510.jsonl.gz"
    if full_path.exists():
        items.extend(read_items(full_path))
    
    return items


def tokenize_for_overlap(text: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', text.lower())


def get_ngrams(tokens: list[str], n: int = 6) -> set:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}


def extract_question_text(user_verbalized: str) -> str:
    """Extract question text from user_verbalized prompt."""
    text = user_verbalized.split("\nEstimate what percentage")[0]
    text = text.replace("**Question**: ", "")
    text = re.split(r'\n\s*Options:\s*\n', text, maxsplit=1)[0]
    return text.strip()


def deduplicate_against_simbench(
    items: list[dict],
    simbench_items: list[dict],
    ngram_threshold: float = 0.5,
    cosine_threshold: float = 0.87,
) -> tuple[list[dict], dict]:
    """Remove items overlapping with SimBench test set."""
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
        q = extract_question_text(it.get("user_verbalized", ""))
        simbench_questions.append(q)
    
    # Build SimBench n-gram index
    print("Building SimBench n-gram index...")
    all_simbench_grams = set()
    for q in simbench_questions:
        grams = get_ngrams(tokenize_for_overlap(q))
        all_simbench_grams.update(grams)
    
    # N-gram filtering
    ngram_clean = []
    for item in items:
        q = extract_question_text(item.get("user_verbalized", ""))
        tokens = tokenize_for_overlap(q)
        if len(tokens) < 6:
            ngram_clean.append(item)
            continue
        
        grams = get_ngrams(tokens)
        overlap = len(grams & all_simbench_grams) / len(grams) if grams else 0
        
        if overlap >= ngram_threshold:
            report["removed_by_ngram"] += 1
            report["removed_per_source"][item["source"]] += 1
        else:
            ngram_clean.append(item)
    
    print(f"After n-gram dedup: {len(ngram_clean)} items (removed {report['removed_by_ngram']})")
    
    # Embedding filtering
    try:
        print("Building embedding index...")
        os.environ['SENTENCE_TRANSFORMERS_HOME'] = '/home/ubuntu/.cache/sentence_transformers'
        os.makedirs('/home/ubuntu/.cache/sentence_transformers', exist_ok=True)
        
        from sentence_transformers import SentenceTransformer
        from sklearn.metrics.pairwise import cosine_similarity
        
        model = SentenceTransformer("all-MiniLM-L6-v2")
        
        item_texts = [extract_question_text(it["user_verbalized"]) for it in ngram_clean]
        simbench_embeddings = model.encode(simbench_questions, show_progress_bar=True)
        item_embeddings = model.encode(item_texts, show_progress_bar=True)
        
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


# ============================================================================
# Train/Val Split and Deduplication
# ============================================================================

def split_by_question(
    items: list[dict],
    val_ratio: float = 0.1,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split by question (study for SocSci210, question_id for WVS).
    
    Ensures no prompt appears in both splits.
    """
    rng = np.random.default_rng(seed)
    
    # Group items by question identifier
    socsci_by_study = defaultdict(list)
    wvs_by_qid = defaultdict(list)
    
    for item in items:
        if item["source"] == "socsci210":
            socsci_by_study[item["study_id"]].append(item)
        elif item["source"] == "wvs":
            wvs_by_qid[item["question_id"]].append(item)
    
    # Split studies/questions
    socsci_studies = list(socsci_by_study.keys())
    wvs_qids = list(wvs_by_qid.keys())
    
    rng.shuffle(socsci_studies)
    rng.shuffle(wvs_qids)
    
    n_val_studies = max(1, int(len(socsci_studies) * val_ratio))
    n_val_qids = max(1, int(len(wvs_qids) * val_ratio))
    
    val_studies = set(socsci_studies[:n_val_studies])
    val_qids = set(wvs_qids[:n_val_qids])
    
    train_items = []
    val_items = []
    
    for study, study_items in socsci_by_study.items():
        if study in val_studies:
            val_items.extend(study_items)
        else:
            train_items.extend(study_items)
    
    for qid, qid_items in wvs_by_qid.items():
        if qid in val_qids:
            val_items.extend(qid_items)
        else:
            train_items.extend(qid_items)
    
    return train_items, val_items


def remove_duplicate_prompts(items: list[dict]) -> list[dict]:
    """Remove items with duplicate (system, user_verbalized) prompts."""
    seen = set()
    unique = []
    
    for item in items:
        key = (item["system"], item["user_verbalized"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    
    return unique


# ============================================================================
# Validation
# ============================================================================

def validate_dataset(train: list[dict], val: list[dict]) -> dict:
    """Run validation checks on the dataset."""
    errors = []
    
    # Check for prompt overlap
    train_prompts = {(it["system"], it["user_verbalized"]) for it in train}
    val_prompts = {(it["system"], it["user_verbalized"]) for it in val}
    overlap = train_prompts & val_prompts
    if overlap:
        errors.append(f"Train/val prompt overlap: {len(overlap)} prompts")
    
    # Check for duplicates within splits
    train_dup = len(train) - len(train_prompts)
    val_dup = len(val) - len(val_prompts)
    if train_dup > 0:
        errors.append(f"Train has {train_dup} duplicate prompts")
    if val_dup > 0:
        errors.append(f"Val has {val_dup} duplicate prompts")
    
    # Check option consistency (all options should be in keys)
    option_issues = 0
    for item in train + val:
        # Check if soft_label sums to ~1
        label_sum = sum(item["soft_label"])
        if abs(label_sum - 1.0) > 0.01:
            option_issues += 1
    
    if option_issues > 0:
        errors.append(f"{option_issues} items have soft_label not summing to 1")
    
    return {
        "train_val_overlap": len(overlap),
        "train_duplicates": train_dup,
        "val_duplicates": val_dup,
        "option_issues": option_issues,
        "errors": errors,
        "passed": len(errors) == 0,
    }


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="/tmp/simbench_train_data_v2")
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-n", type=int, default=MIN_RESPONDENTS)
    args = parser.parse_args()
    
    np.random.seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load SimBench items for deduplication
    print("Loading SimBench items for deduplication...")
    simbench_items = load_simbench_items()
    print(f"Loaded {len(simbench_items)} SimBench items")
    
    # Process SocSci210
    print("\n" + "="*60)
    print("Processing SocSci210...")
    print("="*60)
    socsci_cells = load_socsci210_data()
    socsci_pop, socsci_grouped = build_socsci210_items(socsci_cells, min_n=args.min_n)
    
    # Process WVS
    print("\n" + "="*60)
    print("Processing WVS...")
    print("="*60)
    wvs_items = load_wvs_data()
    
    # Combine all items
    all_items = socsci_pop + socsci_grouped + wvs_items
    print(f"\nTotal items before dedup: {len(all_items)}")
    
    # Deduplicate against SimBench
    print("\n" + "="*60)
    print("Deduplicating against SimBench...")
    print("="*60)
    clean_items, dedup_report = deduplicate_against_simbench(all_items, simbench_items)
    
    # Remove duplicate prompts within dataset
    print("\nRemoving duplicate prompts...")
    before_dedup = len(clean_items)
    clean_items = remove_duplicate_prompts(clean_items)
    print(f"Removed {before_dedup - len(clean_items)} internal duplicates")
    
    # Split train/val by question
    print("\nSplitting train/val by question...")
    train_items, val_items = split_by_question(clean_items, val_ratio=args.val_ratio, seed=args.seed)
    
    # Validate
    print("\nValidating dataset...")
    validation = validate_dataset(train_items, val_items)
    
    if not validation["passed"]:
        print("VALIDATION FAILED:")
        for err in validation["errors"]:
            print(f"  - {err}")
    else:
        print("VALIDATION PASSED")
    
    # Build distill pool
    distill_pool = []
    for item in clean_items:
        distill_pool.append({
            "source": item["source"],
            "source_id": item["source_id"],
            "system": item["system"],
            "user_verbalized": item["user_verbalized"],
            "keys": item["keys"],
        })
    
    # Save outputs
    arm_a_dir = output_dir / "armA_humandist"
    arm_a_dir.mkdir(parents=True, exist_ok=True)
    
    with open(arm_a_dir / "train.jsonl", "w") as f:
        for item in train_items:
            f.write(json.dumps(item) + "\n")
    
    with open(arm_a_dir / "val.jsonl", "w") as f:
        for item in val_items:
            f.write(json.dumps(item) + "\n")
    
    with open(output_dir / "distill_pool.jsonl", "w") as f:
        for item in distill_pool:
            f.write(json.dumps(item) + "\n")
    
    with open(output_dir / "dedup_report.json", "w") as f:
        json.dump(dedup_report, f, indent=2)
    
    with open(output_dir / "validation.json", "w") as f:
        json.dump(validation, f, indent=2)
    
    # Statistics
    stats = {
        "train": len(train_items),
        "val": len(val_items),
        "distill_pool": len(distill_pool),
        "unique_prompts_train": len({(it["system"], it["user_verbalized"]) for it in train_items}),
        "unique_prompts_val": len({(it["system"], it["user_verbalized"]) for it in val_items}),
        "by_source": {
            source: {
                "train": sum(1 for it in train_items if it["source"] == source),
                "val": sum(1 for it in val_items if it["source"] == source),
            }
            for source in ["socsci210", "wvs"]
        },
        "by_format": {
            fmt: {
                "train": sum(1 for it in train_items if it["format"] == fmt),
                "val": sum(1 for it in val_items if it["format"] == fmt),
            }
            for fmt in ["pop", "grouped"]
        },
        "n_distribution": {
            "min": min((it["n"] for it in train_items + val_items if it.get("n")), default=0),
            "max": max((it["n"] for it in train_items + val_items if it.get("n")), default=0),
            "median": int(np.median([it["n"] for it in train_items + val_items if it.get("n")])) if any(it.get("n") for it in train_items + val_items) else 0,
        },
        "validation": validation,
        "dedup": dedup_report,
    }
    
    with open(output_dir / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    
    print("\n" + "="*60)
    print("Dataset build complete!")
    print("="*60)
    print(f"  Train: {len(train_items)} ({stats['unique_prompts_train']} unique prompts)")
    print(f"  Val: {len(val_items)} ({stats['unique_prompts_val']} unique prompts)")
    print(f"  Distill pool: {len(distill_pool)}")
    print(f"\nBy source x format:")
    for source in ["socsci210", "wvs"]:
        for fmt in ["pop", "grouped"]:
            train_cnt = sum(1 for it in train_items if it["source"] == source and it["format"] == fmt)
            val_cnt = sum(1 for it in val_items if it["source"] == source and it["format"] == fmt)
            print(f"  {source} x {fmt}: train={train_cnt}, val={val_cnt}")
    print(f"\nTrain/val overlap: {validation['train_val_overlap']} (must be 0)")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()
