"""External public data for predicting HUMAINE (never HUMAINE rows).

Sources
  LMArena leaderboard (lmarena-ai/leaderboard-dataset, CC BY 4.0), 'text' latest snapshot (published 2026-10-08):
      Elo-style ratings per model and category (overall, multi_turn, creative_writing, coding, math, industry_* ...).
  LMArena votes (lmarena-ai/arena-human-preference-140k, CC BY 4.0): only the share of tie / both-bad votes is used
      (27.5% of 135,634 votes) as the external tie prior.
  OpenRouter model listing (public API /api/v1/models): description, listing date, price, context length. Exact ID
      matches only; the listing describes the CURRENT model behind an ID, which may differ from what was evaluated.

Product -> arena name mapping was made by hand from the candidate list (default / non-thinking variant where several
exist). Products with no arena entry: cohere/command-r7b-12-2024, mistralai/mistral-nemo."""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARENA_TIE_RATE = (21532 + 15754) / 135634  # external: LMArena 140k votes, tie + both_bad

ARENA_NAME = {
    "allenai/olmo-3.1-32b-instruct": "olmo-3.1-32b-instruct", "anthropic/claude-3.7-sonnet": "claude-3-7-sonnet-20250219",
    "anthropic/claude-opus-4": "claude-opus-4-20250514", "anthropic/claude-opus-4.5": "claude-opus-4-5-20251101",
    "anthropic/claude-opus-4.6": "claude-opus-4-6", "anthropic/claude-opus-4.7": "claude-opus-4-7",
    "anthropic/claude-sonnet-4": "claude-sonnet-4-20250514", "anthropic/claude-sonnet-4.5": "claude-sonnet-4-5-20250929",
    "cohere/command-a": "command-a-03-2025", "deepseek/deepseek-chat-v3-0324": "deepseek-v3-0324", "deepseek/deepseek-r1-0528": "deepseek-r1-0528",
    "deepseek/deepseek-v3.2": "deepseek-v3.2", "deepseek/deepseek-v4-flash": "deepseek-v4-flash", "google/gemini-2.0-flash-001": "gemini-2.0-flash-001",
    "google/gemini-2.5-flash": "gemini-2.5-flash", "google/gemini-2.5-pro": "gemini-2.5-pro", "google/gemini-3-pro": "gemini-3-pro",
    "google/gemini-3.1-pro-preview": "gemini-3.1-pro-preview", "google/gemma-3-27b-it": "gemma-3-27b-it",
    "meta-llama/llama-3.3-70b-instruct": "llama-3.3-70b-instruct", "meta-llama/llama-4-maverick": "llama-4-maverick-17b-128e-instruct",
    "minimax/minimax-m2.1": "minimax-m2.1-preview", "mistralai/magistral-medium-2506": "magistral-medium-2506", "mistralai/mistral-large-3": "mistral-large-3",
    "moonshotai/kimi-k2": "kimi-k2-0711-preview", "moonshotai/kimi-k2.5": "kimi-k2.5-instant", "openai/gpt-4.1": "gpt-4.1-2025-04-14",
    "openai/gpt-4o": "gpt-4o-2024-08-06", "openai/gpt-5": "gpt-5-high", "openai/gpt-5-mini": "gpt-5-mini-high",
    "openai/gpt-5.2-chat": "gpt-5.2-chat-latest-20260210", "openai/gpt-5.4": "gpt-5.4", "openai/gpt-5.5": "gpt-5.5", "openai/o1": "o1-2024-12-17",
    "openai/o1-mini": "o1-mini", "openai/o3": "o3-2025-04-16", "openai/o3-mini": "o3-mini", "openai/o4-mini": "o4-mini-2025-04-16",
    "qwen/qwen3-235b-a22b-2507": "qwen3-235b-a22b-instruct-2507", "x-ai/grok-3": "grok-3-preview-02-24", "x-ai/grok-4": "grok-4-0709",
    "x-ai/grok-4.20-beta": "grok-4.20-beta1", "z-ai/glm-4.7": "glm-4.7",
}

# HUMAINE task type -> the arena categories that best describe it (first is used for the direct predictor)
TASK_CATEGORIES = {
    "information_seeking": ["multi_turn", "english"], "personal_advice": ["multi_turn", "creative_writing"],
    "decision_support": ["hard_prompts", "industry_business_and_management_and_financial_operations"],
    "tutoring_explanation": ["industry_life_and_physical_and_social_science", "math"], "problem_solving": ["hard_prompts", "math"],
    "brainstorming": ["creative_writing", "multi_turn"], "project_planning": ["industry_business_and_management_and_financial_operations", "hard_prompts"],
    "technical_assistance": ["industry_software_and_it_services", "coding"], "learning_education": ["instruction_following", "industry_life_and_physical_and_social_science"],
    "comparison_analysis": ["hard_prompts", "longer_query"],
}


@lru_cache(maxsize=1)
def arena_table():
    d = pd.read_parquet(ROOT / "data" / "lmarena" / "text" / "latest.parquet")
    return d.pivot_table(index="model_name", columns="category", values="rating", aggfunc="first")


def arena_rating(product, category="overall"):
    name = ARENA_NAME.get(product)
    t = arena_table()
    if name is None or name not in t.index or category not in t.columns:
        return None
    v = t.at[name, category]
    return None if pd.isna(v) else float(v)


def arena_card(product, task=None):
    r = arena_rating(product)
    if r is None:
        return f"- {product}: not rated in the arena"
    t = arena_table()
    rank = int((t["overall"] > r).sum()) + 1
    parts = [f"overall {r:.0f} (rank {rank} of {t['overall'].notna().sum()})"]
    mt = arena_rating(product, "multi_turn")
    if mt is not None:
        parts.append(f"multi-turn conversations {mt:.0f}")
    for c in (TASK_CATEGORIES.get(task, [])[:2] if task else []):
        v = arena_rating(product, c)
        if v is not None and c != "multi_turn":
            parts.append(f"{c.replace('industry_', '').replace('_and_', ' & ').replace('_', ' ')} {v:.0f}")
    return f"- {product}: " + ", ".join(parts)


def arena_direct_p4(m1, m2, category="overall"):
    """No-LLM predictor: Elo win probability among decisive votes, tie share from external arena votes."""
    r1, r2 = arena_rating(m1, category), arena_rating(m2, category)
    if r1 is None or r2 is None:
        return None
    p = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
    t = ARENA_TIE_RATE
    return [(1 - t) * p, (1 - t) * (1 - p), t]


@lru_cache(maxsize=1)
def openrouter():
    d = json.load(open(ROOT / "data" / "openrouter" / "models.json"))["data"]
    return {x["id"]: x for x in d}


def openrouter_card(product):
    x = openrouter().get(product)
    if x is None:
        return f"- {product}: no marketplace listing found"
    created = dt.datetime.utcfromtimestamp(x.get("created", 0)).strftime("%Y-%m") if x.get("created") else "unknown"
    pr = x.get("pricing", {}) or {}
    try:
        price = f"${float(pr.get('prompt', 0)) * 1e6:.2f} input / ${float(pr.get('completion', 0)) * 1e6:.2f} output per million tokens"
    except (TypeError, ValueError):
        price = "price unknown"
    desc = " ".join((x.get("description") or "").split())[:260]
    return f"- {product}: listed {created}; {price}; context {x.get('context_length', '?')} tokens. {desc}"


def coverage(products):
    return {"arena": sum(arena_rating(p) is not None for p in products), "openrouter": sum(p in openrouter() for p in products), "total": len(products)}
