# SimBench Training Data Card

**Version:** 1.0.0  
**Created:** 2026-09-29  
**GCS Location:** `gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train/`

## Overview

Training datasets for fine-tuning Qwen3-14B to predict survey response distributions, targeting SimBench benchmark performance (arXiv 2510.17516).

## Data Locations (GCS)

```
gs://ai-studio-bucket-347838016394-us-east1/usersim-models/simbench_train/
├── armA_humandist/
│   ├── train.jsonl          # Human distribution training data
│   └── val.jsonl             # Validation split (10%)
├── distill_pool.jsonl        # Prompts for teacher distillation
├── dedup_report.json         # Deduplication statistics
└── DATA_CARD.md              # This file
```

## Data Sources

### 1. SocSci210 (TESS Studies)

- **Source:** [socratesft/SocSci210](https://huggingface.co/datasets/socratesft/SocSci210) on HuggingFace
- **Description:** Cell-level answer histograms aggregated from TESS (Time-sharing Experiments for the Social Sciences) survey responses
- **Studies Used:** 170 "seen" studies only (40 "unseen" studies held out for Socrates eval)
- **License:** [TESS Open Access](https://www.tessexperiments.org/data.html) - academic use permitted
- **Processing:** Individual responses aggregated into (study, condition, task) cell distributions
- **Rows (after dedup):** ~8,253 items

### 2. World Values Survey (WVS)

- **Source:** [Cao et al. SimLLMCultureDist](https://github.com/yongcaoplus/SimLLMCultureDist) (NAACL 2025)
- **Original Data:** WVS Wave 7 (2017-2022), 65 countries, 80k+ respondents
- **Description:** Country-level response distributions on cultural/values questions
- **License:** CC BY (academic use, must cite WVS and Cao et al.)
- **Processing:** Pre-aggregated distributions from Cao et al. GitHub repo
- **Rows (after dedup):** ~4,113 items

### 3. SubPOP (NOT INCLUDED)

- **Status:** SKIPPED - requires gated HuggingFace access
- **Source:** [jjssuh/subpop](https://huggingface.co/datasets/jjssuh/subpop) (Suh et al., ACL 2025)
- **Reason:** Dataset is gated and requires HuggingFace authentication agreement
- **Note:** If access is obtained later, can be added with the same pipeline

## Data Format

Each JSONL row contains:

```json
{
  "source": "socsci210|wvs",
  "source_id": "unique_identifier",
  "format": "grouped|pop",
  "system": "You are a group of individuals with these shared characteristics:\n...",
  "user_token_prob": "**Question**: ... Do not provide any explanation...\n**Answer**: (",
  "user_verbalized": "**Question**: ... Estimate what percentage...\n**Answer**:",
  "keys": ["A", "B", "C", ...],
  "human": [0.25, 0.45, 0.30, ...],
  "verbalized_target": "{\"A\": 25, \"B\": 45, \"C\": 30}",
  "soft_label": [0.25, 0.45, 0.30, ...]
}
```

### Fields

| Field | Description |
|-------|-------------|
| `source` | Data source identifier |
| `source_id` | Unique item identifier |
| `format` | SimBench format style: "grouped" (demographic group) or "pop" (general population) |
| `system` | System prompt with group description |
| `user_token_prob` | Token probability format prompt (for logprob evaluation) |
| `user_verbalized` | Verbalized distribution format prompt (for JSON generation) |
| `keys` | Answer option letters |
| `human` | Normalized human response distribution (sums to 1) |
| `verbalized_target` | Target JSON output (percentages summing to 100) |
| `soft_label` | First-token soft labels for KL loss |

## Row Counts

| Split | Total | SocSci210 | WVS |
|-------|-------|-----------|-----|
| Train | 12,366 | 8,253 | 4,113 |
| Val | 1,374 | ~900 | ~474 |
| Distill Pool | 13,740 | - | - |

## Deduplication

All items deduplicated against SimBench test set (13,510 items) using:

1. **6-gram overlap ≥ 0.5:** Removed items with significant textual overlap
2. **Embedding cosine ≥ 0.87:** Removed semantically similar items (all-MiniLM-L6-v2)

### Deduplication Report

```json
{
  "total_input": 22850,
  "simbench_items": 15433,
  "removed_by_ngram": 9018,
  "removed_by_embedding": 92,
  "retained": 13740
}
```

**Key Finding:** WVS data had high overlap with GlobalOpinionQA (part of SimBench), resulting in 9,110 WVS items being removed. SocSci210 (TESS-based) had no overlap since SimBench explicitly excluded TESS.

## Licensing Summary

| Source | License | Commercial Use | Notes |
|--------|---------|----------------|-------|
| SocSci210/TESS | TESS Open Access | Academic only | Cite TESS and SocSci210 paper |
| WVS (via Cao et al.) | CC BY + WVS Terms | Restricted | Cite WVS and Cao et al. |
| SimBench | CC BY-NC-SA 4.0 | No | NEVER train on SimBench items |

## Citation

If using this data, please cite:

```bibtex
@inproceedings{kolluri2025socsci210,
  title={Finetuning LLMs for Human Behavior Prediction in Social Science Experiments},
  author={Kolluri, Aashish and others},
  booktitle={arXiv preprint arXiv:2509.05830},
  year={2025}
}

@inproceedings{cao2025simllm,
  title={Specializing Large Language Models to Simulate Survey Response Distributions for Global Populations},
  author={Cao, Yong and others},
  booktitle={NAACL},
  year={2025}
}

@misc{wvs2022,
  title={World Values Survey Wave 7 (2017-2022)},
  author={{World Values Survey Association}},
  year={2022},
  url={https://www.worldvaluessurvey.org/}
}
```

## Hard Rules

1. **NEVER train on SimBench items** (pilot497, heldout1426, or any of the 13,510 test items)
2. **NEVER commit SimBench data or predictions to git** (keep gitignored, store in GCS)
3. **Store all datasets in GCS**, not in the repository

## Contact

Training Lead, AI Studio Research
