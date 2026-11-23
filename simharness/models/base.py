"""The one model interface of the harness.

Every model (a baseline, a logistic model, a prompted LLM, a fine-tuned open model) implements:

    score(histories: HistoryBatch, item: Item) -> np.ndarray   # p_vote in [0, 1], one per person, batched
    comment(histories: HistoryBatch, j: int, item: Item) -> str  # what person j would say (Task C)

and optionally
    prepare(bench, day)   # called before a day is scored; walk-forward models (re)fit here on days < day only

A HistoryBatch only exposes history from before the day (bench.py enforces the leak rule), so a model cannot see
the outcome it is asked to predict through the batch. Models must not read outcome tables directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class VoteModel(ABC):
    name: str = "model"
    cost_usd: float = 0.0  # running spend for paid models

    def prepare(self, bench, day: str) -> None:  # noqa: B027  (optional hook)
        pass

    @abstractmethod
    def score(self, histories, item) -> np.ndarray:
        ...

    def comment(self, histories, j: int, item) -> str:
        return ""
