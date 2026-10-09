"""The response contract every data source is converted into."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ResponseTable:
    """units x items -> answer distribution.

    level      'person' (one answer per unit, stored one-hot) or 'group' (a share per option, n respondents)
    units      DataFrame indexed by unit_id; columns are unit attributes (strings), e.g. country, age_group, sex
    items      DataFrame indexed by item_id; columns: text, options (list of labels), block (topic / instrument)
    resp       DataFrame with columns unit, item, dist (np.ndarray over the item's options, sums to 1), n
    overlap    function (unit_a, unit_b) -> True if the two units may share respondents. A unit's own answer to an item,
               and answers of units that overlap it, are never used to predict that unit on that item.
    """
    name: str
    level: str
    units: pd.DataFrame
    items: pd.DataFrame
    resp: pd.DataFrame
    overlap: callable = field(default=lambda a, b: a == b)

    def n_options(self, item):
        return len(self.items.at[item, "options"])

    def coverage(self):
        U, I = len(self.units), len(self.items)
        per_item = self.resp.groupby("item").unit.nunique()
        per_unit = self.resp.groupby("unit").item.nunique()
        return {"units": U, "items": I, "observed_cells": len(self.resp), "density": round(len(self.resp) / max(U * I, 1), 4),
                "median_units_per_item": float(per_item.median()) if len(per_item) else 0.0,
                "median_items_per_unit": float(per_unit.median()) if len(per_unit) else 0.0}


def one_hot(k, j):
    v = np.zeros(k)
    v[j] = 1.0
    return v
