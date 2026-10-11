"""UserSim people-data repository: public survey items with answer distributions overall and by demographic group.

Sources (v0)
  GSS 1972-2024 cumulative file (NORC; free download). Weighted by wtssps (fallback wtssall). For each item we keep the
      most recent three survey years it was asked, so distributions describe today's population as closely as possible.
  SimBench OpinionQA rows (Pew ATP; CC BY-NC-SA, research use): overall and by US demographic group.

Demographic attributes are mapped onto the 14 Twin-2K demographic questions so a person described by those answers can
be matched to group distributions: AGE, SEX, EDUCATION, RACE, REGION, PARTY, IDEOLOGY, INCOME, RELIGION, ATTEND, MARITAL.

Output: data/people_repo/items.jsonl (gitignored; rebuilt by `python -m human_sim.people_repo build`).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GSS = ROOT / "data" / "repo_raw" / "gss" / "GSS_stata" / "gss7224_r3a.dta"
OUTDIR = ROOT / "data" / "people_repo"
ATTRS = ["AGE", "SEX", "EDUCATION", "RACE", "REGION", "PARTY", "IDEOLOGY", "INCOME", "RELIGION", "ATTEND", "MARITAL"]
SKIP = set("""id year wtssall wtssps wtssnrps wtsscomp wtssnr vpsu vstrat sampcode sample oversamp formwt ballot version
issp phase spanself spanint spaneng intage intsex intethn intrace intyrs mode dateintv cohort age sex race hispanic degree educ
region partyid polviews realinc income income16 income06 income98 income91 income86 income77 income72 relig attend marital
wrkstat hompop babies preteen teens adults earnrs reg16 res16 srcbelt xnorcsiz size""".split())
CPI_1986_TO_2024 = 2.87  # realinc is in constant 1986 dollars


# ---------------------------------------------------------------- demographic mapping (GSS -> Twin-2K categories)
def gss_attrs(df):
    a = pd.DataFrame(index=df.index)
    age = df["age"]
    a["AGE"] = pd.cut(age, [17, 29, 49, 64, 120], labels=["18-29", "30-49", "50-64", "65+"]).astype(object)
    a["SEX"] = df["sex"].map({1: "Male", 2: "Female"})
    edu = df["degree"].map({0: "Less than high school", 1: "High school graduate", 2: "Associate's degree",
                            3: "College graduate/some postgrad", 4: "Postgraduate"})
    some = (df["degree"] == 1) & (df["educ"] >= 13)
    edu[some] = "Some college, no degree"
    a["EDUCATION"] = edu
    race = df["race"].map({1: "White", 2: "Black", 3: "Other"})
    if "hispanic" in df:
        race[df["hispanic"].fillna(1) > 1] = "Hispanic"
    a["RACE"] = race
    a["REGION"] = df["region"].map({1: "Northeast", 2: "Northeast", 3: "Midwest", 4: "Midwest", 5: "South", 6: "South", 7: "South",
                                    8: "West", 9: "West"})
    a["PARTY"] = df["partyid"].map({0: "Democrat", 1: "Democrat", 2: "Independent", 3: "Independent", 4: "Independent",
                                    5: "Republican", 6: "Republican", 7: "Something else"})
    a["IDEOLOGY"] = df["polviews"].map({1: "Very liberal", 2: "Liberal", 3: "Liberal", 4: "Moderate", 5: "Conservative",
                                        6: "Conservative", 7: "Very conservative"})
    inc = df["realinc"] * CPI_1986_TO_2024
    a["INCOME"] = pd.cut(inc, [-1, 30000, 50000, 75000, 100000, 1e12],
                         labels=["Less than $30,000", "$30,000-$50,000", "$50,000-$75,000", "$75,000-$100,000", "$100,000 or more"]).astype(object)
    a["RELIGION"] = df["relig"].map({1: "Protestant", 2: "Roman Catholic", 3: "Jewish", 4: "Nothing in particular", 5: "Other",
                                     6: "Buddhist", 7: "Hindu", 8: "Other", 9: "Muslim", 10: "Orthodox", 11: "Protestant", 12: "Other", 13: "Other"})
    a["ATTEND"] = df["attend"].map({0: "Never", 1: "Seldom", 2: "Seldom", 3: "A few times a year", 4: "Once or twice a month",
                                    5: "Once or twice a month", 6: "Once a week", 7: "Once a week", 8: "More than once a week"})
    a["MARITAL"] = df["marital"].map({1: "Married", 2: "Widowed", 3: "Divorced", 4: "Separated", 5: "Never been married"})
    return a


TWIN_TO_ATTR = {"QID11": "REGION", "QID12": "SEX", "QID13": "AGE", "QID14": "EDUCATION", "QID15": "RACE", "QID17": "MARITAL",
                "QID18": "RELIGION", "QID19": "ATTEND", "QID20": "PARTY", "QID21": "INCOME", "QID22": "IDEOLOGY"}


def twin_profile(labels_row) -> dict:
    """Twin-2K demographic answers (labels) -> {ATTR: category}."""
    out = {}
    for q, a in TWIN_TO_ATTR.items():
        v = labels_row.get(q)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        v = str(v)
        if a == "REGION":
            v = v.split(" (")[0].replace("Pacific", "West")
        if a == "RELIGION" and v in ("Atheist", "Agnostic"):
            v = "Nothing in particular"
        if a == "MARITAL" and v == "Living with a partner":
            v = "Married"
        if a == "RACE" and v == "Asian":
            v = "Other"
        out[a] = v
    return out


# ---------------------------------------------------------------- GSS items
def build_gss():
    rdr = pd.io.stata.StataReader(str(GSS))
    varlab = rdr.variable_labels()
    lblname = dict(zip(rdr._varlist, rdr._lbllist))
    vlabels = rdr.value_labels()
    df = pd.read_stata(str(GSS), convert_categoricals=False)
    w = df["wtssps"].fillna(df["wtssall"]).fillna(1.0).astype(float)
    attrs = gss_attrs(df)
    items = []
    for var in df.columns:
        if var in SKIP or var.startswith(("wt", "v", "samp")):
            continue
        labs = vlabels.get(lblname.get(var, ""), {})
        col = df[var]
        if not labs or col.dtype.kind not in "fiu":
            continue
        valid = col.notna() & col.isin(list(labs.keys()))
        if valid.sum() < 400:
            continue
        codes = sorted(int(c) for c in col[valid].unique())
        if not 2 <= len(codes) <= 11:
            continue
        yrs = sorted(df.loc[valid, "year"].unique())
        recent = yrs[-3:]
        m = valid & df["year"].isin(recent)
        if m.sum() < 300:
            continue
        opts = [str(labs[c]) for c in codes]
        idx = {c: i for i, c in enumerate(codes)}

        def dist(mask):
            y = col[mask].map(idx).astype(int).to_numpy()
            ww = w[mask].to_numpy()
            p = np.bincount(y, weights=ww, minlength=len(codes))
            return (p / p.sum()).round(4).tolist() if p.sum() > 0 else None
        by = {}
        for a in ATTRS:
            g = {}
            for val, sub in attrs.loc[m, a].dropna().groupby(attrs.loc[m, a].dropna()):
                mm = m & (attrs[a] == val)
                if mm.sum() >= 40:
                    g[str(val)] = {"p": dist(mm), "n": int(mm.sum())}
            if g:
                by[a] = g
        items.append({"id": f"gss:{var}", "source": "GSS", "text": varlab.get(var, var), "options": opts,
                      "years": [int(y) for y in recent], "n": int(m.sum()), "overall": dist(m), "by": by})
    return items


# ---------------------------------------------------------------- SimBench OpinionQA (US, by group)
SB_KEY = {"CREGION": "REGION", "AGE": "AGE", "SEX": "SEX", "EDUCATION": "EDUCATION", "RACE": "RACE", "POLPARTY": "PARTY",
          "POLIDEOLOGY": "IDEOLOGY", "INCOME": "INCOME", "RELIG": "RELIGION", "RELIGATTEND": "ATTEND", "MARITAL": "MARITAL"}
SB_VAL = {"male": "Male", "female": "Female", "Other": "Something else", "very conservative": "Very conservative",
          "conservative": "Conservative", "moderate": "Moderate", "liberal": "Liberal", "very liberal": "Very liberal",
          "protestant": "Protestant", "roman catholic": "Roman Catholic", "nothing in particular": "Nothing in particular",
          "a few times a year": "A few times a year", "more than once a week": "More than once a week", "never": "Never",
          "once a week": "Once a week", "once or twice a month": "Once or twice a month", "seldom": "Seldom",
          "divorced": "Divorced", "married": "Married", "never been married": "Never been married", "high school graduate": "High school graduate",
          "associate's degree": "Associate's degree", "college graduate/some postgrad": "College graduate/some postgrad",
          "postgraduate": "Postgraduate", "some college, no degree": "Some college, no degree", "less than high school": "Less than high school"}


def build_simbench():
    items = {}
    opt_re = re.compile(r"^\(([A-Z])\):\s*(.+)$", re.M)
    for split in ("Pop", "Grouped"):
        d = pd.read_pickle(ROOT / "data" / "simbench" / f"SimBench{split}.pkl")
        d = d[d.dataset_name == "OpinionQA"]
        for r in d.itertuples():
            q = str(r.input_template).split("\n\nOptions:")[0].strip()
            opts = dict(opt_re.findall(str(r.input_template)))
            ha = r.human_answer if isinstance(r.human_answer, dict) else ast.literal_eval(r.human_answer)
            keys = [k for k in ha if k in opts]
            if len(keys) < 2:
                continue
            p = np.array([ha[k] for k in keys], float)
            p = (p / p.sum()).round(4).tolist()
            it = items.setdefault(q, {"id": f"opinionqa:{abs(hash(q)) % 10**9}", "source": "Pew ATP (OpinionQA via SimBench)",
                                      "text": q, "options": [opts[k] for k in keys], "years": [], "n": 0, "overall": None, "by": {}})
            gm = r.group_prompt_variable_map if split == "Grouped" else None
            gm = gm if isinstance(gm, dict) else (ast.literal_eval(gm) if isinstance(gm, str) and gm else {})
            if split == "Pop" or not gm:
                it["overall"] = p
            else:
                for k, v in gm.items():
                    if k in SB_KEY:
                        it["by"].setdefault(SB_KEY[k], {})[SB_VAL.get(str(v), str(v))] = {"p": p, "n": int(getattr(r, "group_size", 0) or 0)}
    return [it for it in items.values() if it["overall"] or it["by"]]


def build():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    items = build_gss()
    print("GSS items", len(items), flush=True)
    sb = build_simbench()
    print("OpinionQA items", len(sb), flush=True)
    with open(OUTDIR / "items.jsonl", "w") as fh:
        for it in items + sb:
            fh.write(json.dumps(it) + "\n")
    print("wrote", len(items) + len(sb))


_items = None


def load():
    global _items
    if _items is None:
        _items = [json.loads(l) for l in (OUTDIR / "items.jsonl").read_text().splitlines() if l.strip()]
    return _items


def conditional(item, profile, shrink=0.5):
    """Distribution for a person: overall prior adjusted by each matched group's log-ratio, shrunk (fixed a priori)."""
    base = item.get("overall")
    groups = [(a, item["by"][a][v]["p"]) for a, v in profile.items() if a in item.get("by", {}) and v in item["by"][a]]
    if base is None:
        if not groups:
            return None, []
        base = np.mean([g for _, g in groups], axis=0).tolist()
    lp = np.log(np.clip(np.asarray(base, float), 1e-4, None))
    out = lp.copy()
    for _, g in groups:
        out += shrink * (np.log(np.clip(np.asarray(g, float), 1e-4, None)) - lp)
    p = np.exp(out - out.max())
    return (p / p.sum()).tolist(), [a for a, _ in groups]


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build()
