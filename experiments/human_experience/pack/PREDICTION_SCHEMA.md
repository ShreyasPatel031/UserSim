# Prediction contract

Write one JSONL record per case, condition and repetition. The same final prediction model must be used in every cell. Do not submit example/dummy forecasts as results.

```json
{
  "case_id": "copy from inputs/cases.jsonl",
  "condition": "A0",
  "replicate": 1,
  "ratings": {
    "ease_of_use_rating": {"probabilities": [0.1, 0.1, 0.2, 0.3, 0.3]},
    "functionality_rating": {"probabilities": [0.1, 0.1, 0.2, 0.3, 0.3]},
    "overall_rating": {"probabilities": [0.1, 0.1, 0.2, 0.3, 0.3]},
    "value_for_money_rating": null
  },
  "benefits": [{"aspect": "example only", "claim": "one specific predicted benefit", "basis_ids": []}],
  "frictions": [{"aspect": "example only", "claim": "one specific predicted difficulty", "basis_ids": []}],
  "task_hypotheses": [],
  "unknowns": [],
  "execution": null,
  "usage": {"input_tokens": null, "output_tokens": null, "cost_usd": null, "latency_seconds": null},
  "model": "record exact model/version",
  "packet_sha256": "record actual packet hash"
}
```

Vectors are ordered rating 1 through 5. Numbers above illustrate structure only. Null means abstention, not neutral score. Max three benefit and three friction claims, max five task hypotheses in phase A. In phase B the goal is supplied, so task discovery is not scored.

Execution records: `run_id`, `engine`, `status`, `success_criteria_results`, `observations`, `errors`, `actions`, `elapsed_seconds`, `plan`, `product_version_or_capture_date`, `environment_mismatches`, `trace_path`. Separate environmental failure, inaccessible paid capability, runner failure and observed product friction. Observations must be trace-supported. Do not manufacture persona frustration or delays to make a score fit.

Prohibit outcome files, source test-review prose, reviewer IDs, review date, stratum, sampling weight, hidden scores and outcome-oriented task annotations from model input. The opaque case ID can remain orchestration-only.
