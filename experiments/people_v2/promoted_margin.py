"""List the people whose X handle was promoted by the dead-link fallback, with PH name, X name and name similarity, lowest first, for hand review.
    python promoted_margin.py BUILD_DIR [x_lookup.json] > promoted_name_margin.csv      (read-only)
The X name comes from the build's X profile row when there is one, else from x_lookup.json."""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import pandas as pd

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("b", os.path.join(here, "build_v3.py"))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def main(d: str, lookup: str | None) -> pd.DataFrame:
    H, P, Pr = (pd.read_parquet(os.path.join(d, f"{t}.parquet")) for t in ("handles", "persons", "profiles"))
    f = H[H.source == "ph_twitter_field_live_fallback"][["person_id", "handle"]].merge(P[["person_id", "display_name"]], on="person_id", how="left")
    x = Pr[Pr.platform == "x"][["person_id", "handle", "name"]].rename(columns={"name": "x_name"})
    f = f.merge(x, on=["person_id", "handle"], how="left")
    if lookup and os.path.exists(lookup):
        xl = json.load(open(lookup))
        f["x_name"] = [n if isinstance(n, str) and n else (xl.get(h, {}) or {}).get("name") for n, h in zip(f.x_name, f.handle)]
    f["sim"] = [round(b.namesim(a, c), 2) for a, c in zip(f.display_name, f.x_name)]
    f["label_correct_wrong_unsure"] = ""
    return f.sort_values("sim")


if __name__ == "__main__":
    out = main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    out.to_csv(sys.stdout, index=False)
