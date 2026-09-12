#!/usr/bin/env python3
"""Single source of truth for the Socrates/SocSci210 prompt format.

Both the SFT corpus builder and the Wasserstein eval runner must render the
identical prompt, otherwise train/test formats diverge and the eval number is
meaningless. The strings here are copied from
`scripts/fm_baselines/colab_qwen3_8b_floor_socrates_vllm.py` and asserted equal
by `scripts/fm_train/smoke_socrates_sft.py`.
"""
from __future__ import annotations

SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)


def build_messages(row: dict) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": row["prompt"]},
    ]


def render_prompt(tok, row: dict) -> str:
    """Prompt exactly as the eval runner feeds it to vLLM."""
    return tok.apply_chat_template(
        build_messages(row), tokenize=False, add_generation_prompt=True
    )


def render_target(row: dict) -> str:
    """Assistant continuation the model is trained to produce."""
    return str(row["response"])


def sample_id(row: dict) -> str:
    return (
        f"{row['study_id']}|{row['sample_id']}|{row['condition_num']}|"
        f"{row['task_num']}|{row['participant']}"
    )
