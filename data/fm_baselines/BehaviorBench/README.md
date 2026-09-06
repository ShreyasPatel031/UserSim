---
license: cc-by-nc-nd-4.0
language:
  - en
pretty_name: BehaviorBench
size_categories:
  - 10K<n<100K
task_categories:
  - text-generation
  - question-answering
  - multiple-choice
tags:
  - behavioral-science
  - benchmark
  - foundation-models
  - personality
  - economic-games
  - scientific-workflows
---

# BehaviorBench

BehaviorBench is a benchmark for evaluating large language models on behavioral
science tasks. It bundles four data sources covering personality and survey
response prediction (Big Five), economic-game decision making (MobLab),
scientific-workflow prediction (Workflows), and economics-contest problem
solving (IEO). All examples are released as chat-formatted
`{system, user, assistant}` JSONL records using a fixed evaluation split.

This repository hosts the **evaluation data only**. The benchmark code (loaders,
prompts, metrics) is released separately from this dataset.

## Subsets

| Subset | Task name | Files | Rows |
| --- | --- | --- | --- |
| `big_five/pers_score_pred/` | Personality score prediction given demographics (Demo. To Pers.) | 1 | 1,000 |
| `big_five/surv_resp_pred/` | Survey response prediction given demographics (Demo. To Resp.) | 1 | 1,000 |
| `big_five/missing_surv_resp/` | Masked survey response prediction (Masked Resp. Pred.) | 1 | 1,000 |
| `big_five/seq_surv_resp/` | Sequential survey response prediction (Seq. Resp. Pred.) | 1 | 1,000 |
| `big_five/acrossdim_pers_score/` | Personality score prediction given scores from other dimensions (Across-Dim Pers. Pred.) | 1 | 1,000 |
| `big_five/demo_pred_age/` | Age prediction given personality scores (Pers. To Demo.) | 1 | 1,000 |
| `moblab/game_behavior/` | First-round game behavior simulation (Game Behav. Sim.) | 9 | 1,800 |
| `moblab/multiround_behavior/` | Multi-round game behavior prediction (Multi-Round Pred.) | 7 | 3,498 |
| `moblab/acrossgame_behavior/` | First-round game behavior prediction given observations from other games (Across-Ctx Pred.) | 9 | 6,262 |
| `moblab/strategic_gameplay/` | Strategic game play | 1 | 1,000 |
| `workflows/` | Scientific workflow prediction (5 subtasks × `aer`/`nhb`/combined splits) | 15 | ~2,200 |
| `economics_contests/` | Economics contest problem solving | 1 | 124 |

`behaviorbench_indices.json` records the fixed evaluation indices used to
construct each subset from its upstream source, enabling exact reproducibility
across evaluation runs.

## Schema

Every released file uses a unified chat schema:

```json
{"system": "<task framing>", "user": "<input/question>", "assistant": "<reference target>"}
```

- `system` — task-level instructions establishing the framing.
- `user` — the per-example input (question, demographic profile, prior round
  history, paper context, etc.).
- `assistant` — the reference target (empirical participant response, gold
  answer, or author-written ground truth, depending on subset).

## Loading

This repository ships the data as raw JSONL files. Direct usage:

```python
import json
from pathlib import Path

records = [json.loads(line) for line in Path("big_five/pers_score_pred/test.jsonl").open()]
print(len(records), records[0].keys())
```

Alternatively, the Croissant 1.0 metadata file (`croissant.json`) can be used
with `mlcroissant` for typed record iteration.

## Source data and curation

| Subset | Upstream source | Selection |
| --- | --- | --- |
| Big Five | Open-Source Psychometrics Project's Big Five Personality Test dataset (Kaggle: `lucasgreenwell/ocean-five-factor-personality-test-responses`), pairing 50-item OCEAN responses with self-reported demographics (age, gender, race, country/region, native language, handedness). | Fixed-index sample of 1,000 participants per subtask (no overlap across the six subtasks). |
| MobLab | Anonymized gameplay logs from MobLab (`https://www.moblab.com/`), 2015–2023, released with Mei et al., "A Turing test of whether AI chatbots are behaviorally similar to humans," *PNAS* 121(9):e2313925121, 2024 ([doi:10.1073/pnas.2313925121](https://doi.org/10.1073/pnas.2313925121)). Covers seven classic economic games across nine scenarios: Dictator, Ultimatum (Proposer/Responder), Trust (Investor/Banker), Public Goods, Bomb Risk, Beauty Contest, and Push/Pull (Prisoner's Dilemma). | Fixed-index sample of recent gameplay rounds. |
| Workflows | Open-access article metadata (title and abstract) from the *American Economic Review* and *Nature Human Behaviour*, restricted to articles **published in 2025**. | Each title–abstract pair decomposed into a five-field structured workflow (context, key idea, method, outcome, projected impact) following the MASSW protocol; combined and per-journal splits provided. |
| IEO | Publicly available multiple-choice problems and answer keys from recent International Economics Olympiad rounds. | All problems available at curation time. |

No new human annotations were collected for this release. Reference answers
are taken directly from the upstream sources. All upstream records were
converted to a unified chat schema; no model-generated labels are included.

## Personal and sensitive information

The Big Five subset includes self-reported demographic attributes that are
present in the upstream public dataset: age, gender, race/ethnicity, native
language, and country/region. **No direct identifiers** (names, emails, IP
addresses, geocoordinates, account IDs) and **no free-text fields** that could
re-identify participants are released. The MobLab, Workflows, and IEO subsets
do not contain personal information.

## Biases and limitations

Big Five participants may skew Western, English-speaking, and self-selected
respondents of online personality surveys.

English-only.

## Intended use

- Academic benchmarking of foundation models on behavioral-science tasks.
- Studying generalization of large language models to human behavior prediction.
- Comparing distributional alignment between model and human responses.

## Out-of-scope use

Clinical psychology diagnosis; employment, credit, or insurance scoring; legal
proceedings; surveillance; and any individual-level prediction or scoring of
real persons.

## License

This compilation is released under
**[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)**.
Users may share the compilation with attribution for non-commercial purposes
without modification. Upstream source corpora retain their own licenses and
terms; users are responsible for complying with both this license and the
upstream licenses when redistributing or building on this data.

## Maintenance

Versioned releases on this hosting platform. Bug fixes that change evaluation
behavior trigger a new minor version (current: `1.0.0`).

## Citation

```bibtex
@misc{behaviorbench2026,
  title  = {BehaviorBench: Benchmarking Foundation Models for Behavioral Science Tasks},
  author = {BeFM Authors},
  year   = {2026}
}
```
