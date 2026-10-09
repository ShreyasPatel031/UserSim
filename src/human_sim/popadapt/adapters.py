"""Data sources -> ResponseTable. Adding a source means adding a function here; the engine never changes."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from human_sim.popadapt.contract import ResponseTable, one_hot

ROOT = Path(__file__).resolve().parents[3]
CKEYS = ("country", "cntry", "COUNTRY_NAME", "country_name", "UserCountry3", "rater_locale")


def _country_and_rest(attrs):
    c = next((str(attrs[k]) for k in CKEYS if k in attrs), "")
    return c, {k: str(v) for k, v in attrs.items() if k not in CKEYS}


def group_overlap(attrs_by_unit):
    """Overlap rule for group-level data: different country -> disjoint; same country -> overlapping, unless both are
    single-attribute groups on the same attribute with non-overlapping values (e.g. age 18-29 vs age 50-64)."""
    from human_sim import simbench_structure_xnat as XN
    meta = {u: _country_and_rest(a) for u, a in attrs_by_unit.items()}

    def overlap(a, b):
        if a == b:
            return True
        (ca, ra), (cb, rb) = meta[a], meta[b]
        if ca != cb:
            return False
        if len(ra) == 1 and len(rb) == 1 and set(ra) == set(rb):
            (k, va), = ra.items()
            return XN.values_overlap(va, rb[k])
        return True
    return overlap


def simbench(dataset):
    """One SimBench dataset as group-level units (country totals and subgroups) x question stems."""
    from human_sim import simbench_ablate as A
    from human_sim.simbench_divided_anatomy import parse_options
    rows = pd.concat([A.load_split("Pop"), A.load_split("Grouped")], ignore_index=True)
    rows = rows[rows.dataset_name == dataset]
    acc, attrs, items = defaultdict(list), {}, {}
    for _, r in rows.iterrows():
        vm = r.group_prompt_variable_map or {}
        u = json.dumps(sorted((str(k), str(v)) for k, v in vm.items()))
        st = A._stem(r.input_template)
        keys = list(r.human_answer)
        if st not in items:
            labels = parse_options(r.input_template)
            items[st] = {"text": st, "options": [labels.get(k, k) for k in keys], "keys": keys, "block": dataset}
        if set(keys) != set(items[st]["keys"]):
            continue
        v = np.array([r.human_answer[k] for k in items[st]["keys"]], float)
        if not np.isfinite(v).all() or v.sum() <= 0:
            continue
        acc[(u, st)].append((v / v.sum(), float(r.get("group_size", 0) or 0)))
        attrs[u] = {str(k): str(v) for k, v in vm.items()}
    resp = pd.DataFrame([{"unit": u, "item": st, "dist": np.mean([x for x, _ in vs], axis=0), "n": sum(n for _, n in vs)} for (u, st), vs in acc.items()])
    units = pd.DataFrame([attrs[u] for u in attrs], index=list(attrs)).fillna("")
    units.index.name = "unit_id"
    itm = pd.DataFrame.from_dict(items, orient="index")
    itm.index.name = "item_id"
    return ResponseTable(f"SimBench:{dataset}", "group", units, itm, resp, group_overlap(attrs))


def twin2k(path=ROOT / "data" / "twin2k"):
    """Twin-2K-500: 2,058 US adults (person level). Download (CC BY 4.0) into data/twin2k/ from
    https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500/tree/main/question_catalog_and_human_response_csv
    (question_catalog.json, wave1_3_response.csv, wave1_3_response_label.csv, wave4_response.csv). Items: every single-choice question and Likert / bipolar matrix row
    from waves 1-3, demographics excluded (they are unit attributes). Block = the survey block (e.g. 'Product
    Preferences - Pricing', 'Personality')."""
    cat = json.load(open(path / "question_catalog.json"))
    num = pd.read_csv(path / "wave1_3_response.csv").set_index("pid")
    lab = pd.read_csv(path / "wave1_3_response_label.csv", low_memory=False).set_index("pid")
    demo_q = [q for q in cat if q.get("BlockName", "").strip() == "Demographics"]
    names = {"QID11": "region", "QID12": "sex", "QID13": "age", "QID14": "education", "QID15": "race", "QID16": "citizen", "QID17": "marital",
             "QID18": "religion", "QID19": "attendance", "QID20": "party", "QID21": "income", "QID22": "ideology", "QID23": "household", "QID24": "employment"}
    units = pd.DataFrame({names.get(q["QuestionID"], q["QuestionID"]): lab[q["QuestionID"]].astype(str) for q in demo_q if q["QuestionID"] in lab.columns}, index=lab.index)
    units.index = units.index.astype(str)
    units.index.name = "unit_id"
    items, recs = {}, []
    for q in cat:
        block = q.get("BlockName", "").strip()
        if block == "Demographics" or q.get("is_descriptive"):
            continue
        sel = (q.get("Settings") or {}).get("Selector", "")
        if q["QuestionType"] == "MC" and sel in ("SAVR", "SAHR") and q.get("Options"):
            cols = [(q["csv_columns"][0], q["QuestionText"], q["Options"])] if q.get("csv_columns") else []
        elif q["QuestionType"] == "Matrix" and q.get("Columns"):
            cols = [(c, f'{q["QuestionText"]} | {row}', q["Columns"]) for c, row in zip(q.get("csv_columns", []), q.get("Rows", []))]
        else:
            continue
        for col, text, opts in cols:
            if col not in num.columns or not 2 <= len(opts) <= 12:
                continue
            x = num[col]
            ok = x.notna() & (x >= 1) & (x <= len(opts))
            if ok.sum() < 50:
                continue
            items[col] = {"text": " ".join(str(text).split())[:300], "options": list(opts), "block": block}
            k = len(opts)
            recs += [{"unit": str(pid), "item": col, "dist": one_hot(k, int(v) - 1), "n": 1.0} for pid, v in x[ok].items()]
    itm = pd.DataFrame.from_dict(items, orient="index")
    itm.index.name = "item_id"
    return ResponseTable("Twin-2K-500", "person", units, itm, pd.DataFrame(recs), lambda a, b: a == b)


def twin2k_retest(path=ROOT / "data" / "twin2k"):
    """Wave-4 answers to items repeated from waves 1-3 (same column names): the person-level test-retest ceiling."""
    w4 = pd.read_csv(path / "wave4_response.csv").set_index("pid")
    w4.index = w4.index.astype(str)
    return w4
