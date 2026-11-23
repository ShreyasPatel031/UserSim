"""The four-table plug-in interface of the social simulation harness.

A domain (Product Hunt, an app store, a crowdfunding site, a forum ...) plugs into the harness by producing four
tables. Names are domain-neutral: an *item* is whatever people act on (a launch, an app, a post), an *endorse* is the
domain's lightweight positive action (an upvote, a like, a star), a *comment* is free text attached to an item.

All tables are pandas DataFrames with the columns below. Person ids are opaque strings; the domain adapter must salt
or hash them before they reach the harness. The harness never needs a real name or username.

1. ITEMS            one row per item
2. EVENTS           people histories: one row per (person, dated action)
3. OUTCOMES         per item: the final result (and, implicitly, who acted on it, from EVENTS)
4. STRUCTURAL       the domain model's score per item, frozen before the item's day

plus a PEOPLE table (one row per person) that says which people are held whole and until when their actions were
observed. Observation time matters: a person read before day D cannot show an action on day D, so a missing action
is only a real negative when the person was observed after D.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str
    doc: str
    required: bool = True


@dataclass(frozen=True)
class TableSpec:
    name: str
    doc: str
    columns: tuple[Column, ...] = field(default_factory=tuple)

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        missing = [c.name for c in self.columns if c.required and c.name not in df.columns]
        if missing:
            raise ValueError(f"table {self.name}: missing required columns {missing}")
        return df

    def empty(self) -> pd.DataFrame:
        return pd.DataFrame({c.name: pd.Series(dtype=c.dtype) for c in self.columns})


# Action kinds the harness understands. Domains map their own actions onto these.
ENDORSE = "endorse"      # upvote / like / star: the Task V label
COMMENT = "comment"      # free text on an item: the Task C target
REVIEW = "review"        # longer free text with a verdict
MAKE = "make"            # the person made / launched / hunted the item
FOLLOW = "follow"        # person -> person or person -> item edge (often undated: see leak rules)
KINDS = (ENDORSE, COMMENT, REVIEW, MAKE, FOLLOW)

ITEMS = TableSpec(
    "items",
    "What people act on. One row per item.",
    (
        Column("item_id", "string", "domain id of the item, unique"),
        Column("day", "string", "ISO date the item went live (the competition day)"),
        Column("title", "string", "short name"),
        Column("summary", "string", "one-line pitch (tagline)"),
        Column("description", "string", "longer text; may be empty", required=False),
        Column("tags", "object", "list[str] of topics / categories"),
    ),
)

EVENTS = TableSpec(
    "events",
    "People histories. One row per dated action of a person. Only actions that can be dated go in: the harness "
    "uses `day` to enforce the leak rule (history for day D uses only events with day < D).",
    (
        Column("person_id", "string", "salted person id"),
        Column("kind", "string", f"one of {KINDS}"),
        Column("item_id", "string", "target item (null for person -> person follows)"),
        Column("day", "string", "ISO date the action is attributed to. For undated endorsements this is the "
                                  "item's day (most endorsements happen on it); the adapter documents the choice"),
        Column("ts", "datetime64[ns, UTC]", "exact time when known", required=False),
        Column("ts_quality", "string", "exact / day / item_day / snapshot (snapshot = undated)", required=False),
        Column("text", "string", "comment or review text, when the kind carries text", required=False),
    ),
)

PEOPLE = TableSpec(
    "people",
    "One row per person the domain holds.",
    (
        Column("person_id", "string", "salted person id"),
        Column("complete", "bool", "the person's history is held whole (domain's own completeness rule)"),
        Column("observed_until", "datetime64[ns, UTC]", "time the person's endorsements were last read; actions "
                                                         "after this time are unknown, not absent"),
    ),
)

OUTCOMES = TableSpec(
    "outcomes",
    "Final result per item, known only after the item's day. Never an input to a model.",
    (
        Column("item_id", "string", "item"),
        Column("final_score", "float64", "votes / likes / installs at close"),
        Column("final_rank", "float64", "rank within its day (1 = best), null if unranked", required=False),
    ),
)

STRUCTURAL = TableSpec(
    "structural",
    "The domain model's score per item, frozen before the item's day. Used as the shortlist and the baseline for "
    "Task R; never trained on by the social simulation.",
    (
        Column("item_id", "string", "item"),
        Column("day", "string", "ISO date"),
        Column("score", "float64", "higher = predicted to do better"),
        Column("model_version", "string", "which structural model"),
        Column("frozen_at", "datetime64[ns, UTC]", "when the score was written (must be before the day starts)",
               required=False),
    ),
)

ALL_TABLES = {t.name: t for t in (ITEMS, EVENTS, PEOPLE, OUTCOMES, STRUCTURAL)}


@dataclass
class DomainTables:
    """What a domain adapter returns."""
    items: pd.DataFrame
    events: pd.DataFrame
    people: pd.DataFrame
    outcomes: pd.DataFrame
    structural: pd.DataFrame
    notes: dict = field(default_factory=dict)  # adapter's documented choices (dating, leak risks, exclusions)

    def validate(self) -> "DomainTables":
        for name in ("items", "events", "people", "outcomes", "structural"):
            ALL_TABLES[name].validate(getattr(self, name))
        bad = set(self.events["kind"].unique()) - set(KINDS)
        if bad:
            raise ValueError(f"unknown event kinds {bad}")
        return self
