"""Twin-2K-500 Mega-Study as a held-out benchmark for population-level knowledge.

Claim under test: with only what the benchmark gives about a person (14 demographic answers, no earlier answers),
UserSim's public population data and harness beat the bare model on 19 new studies (164 outcomes).

Pipeline
  1. prompts:   their system instruction + demographic persona + the per-person `survey_text` from the HF dataset
  2. model:     Gemini via Vertex (same client as humaine_predict), cached per (arm, study, PID)
  3. converter: LLM JSON answers -> the study's Qualtrics value columns, learned from the human file (position ->
                recode value), written as consolidated_llm_values.csv next to a copy of the human file
  4. scoring:   the authors' own mega_study_evaluation/<study>/mega_study_evaluation.py, so numbers are comparable
                to the published arms (demographics_only, empty_persona, full persona).

Rule: no Mega-Study answers are used by any arm. The human file is used only to score and to learn the answer
encoding (format, not content). Arms differ only in the context added to the prompt.

Usage:
  python -m human_sim.mega_pipeline check STUDY            # converter sanity check: human answers as 'twins'
  python -m human_sim.mega_pipeline run ARM STUDY [LIMIT]  # simulate + convert + score
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MEGA = ROOT / "third_party" / "Twin-2K-500-Mega-Study"
HF = ROOT / "data" / "twin2k_mega" / "data"
TWIN = ROOT / "data" / "twin2k"
OUT = ROOT / "results" / "twin_mega"
MODEL = os.environ.get("MEGA_MODEL", "gemini-2.5-flash")
TEMPERATURE = float(os.environ.get("MEGA_TEMPERATURE", "0.7"))  # the published demographics_only arm used 0.7

SYSTEM = ("You are an AI assistant. Your task is to answer the 'New Survey Question' as if you are the person described in the "
          "'Persona Profile' (which consists of their past survey responses). \nRemain consistent with the persona's previous "
          "answers and stated traits. Simulate their responses to new questions while accounting for human cognitive limitations, "
          "uncertainty, and biases.\nFollow all instructions provided for the new question carefully regarding the format of your answer.")
PERSONA_HEADER = "## Persona Profile (This individual's past survey responses):\n"
SEPARATOR = "## New Survey Question & Instructions (Please respond as the persona described above):\n"
DEMO_QIDS = [f"QID{i}" for i in range(11, 25)]


# ---------------------------------------------------------------- persona (demographics only)
_demo = None


def demographics_text(pid) -> str:
    global _demo
    if _demo is None:
        cat = {q["QuestionID"]: q for q in json.loads((TWIN / "question_catalog.json").read_text())}
        lab = pd.read_csv(TWIN / "wave1_3_response_label.csv", usecols=["pid"] + DEMO_QIDS).set_index("pid")
        _demo = (cat, lab)
    cat, lab = _demo
    row = lab.loc[int(pid_key(pid))]
    lines = []
    for q in DEMO_QIDS:
        v = row[q]
        if pd.isna(v):
            continue
        lines.append(f"Q: {re.sub(r'<[^>]+>', '', cat[q]['QuestionText']).strip()}\nAnswer: {v}")
    return PERSONA_HEADER + "\n\n".join(lines) + "\n"


# ---------------------------------------------------------------- study data
def study_rows(study):
    d = pd.read_parquet(HF / f"{study}.parquet")
    return d


def questions(survey_json: str):
    """Non-descriptive questions in display order (= Q1..Qn in survey_text)."""
    j = json.loads(survey_json)
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "QuestionID" in x and "QuestionType" in x:
                if not x.get("is_descriptive") and x.get("QuestionType") != "DB":
                    out.append(x)
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(j)
    return out


def items(q, answers):
    """Flatten one question's answers into [(item_index, raw_value)] with numbers where possible."""
    a = answers or {}
    if "SelectedByPosition" in a:
        v = a["SelectedByPosition"]
        if isinstance(v, list):
            return [(k, v[k]) for k in range(len(v))]
        return [(0, v)]
    if "Values" in a:
        return [(k, a["Values"][k]) for k in range(len(a["Values"]))]
    if "Text" in a:
        return [(0, a["Text"])]
    return []


def pid_key(pid) -> str:
    return str(pid).replace("pid_", "")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- published files (human, and a template twin file)
def spec_dir(study, prefer="demographics_only"):
    base = MEGA / "results" / study
    for p in sorted(base.iterdir()):
        if p.is_dir() and p.name.startswith(prefer + "_2"):
            return p
    return next(p for p in sorted(base.iterdir()) if p.is_dir())


def read_qualtrics(path):
    with gzip.open(path, "rt") if str(path).endswith(".gz") else open(path) as fh:
        df = pd.read_csv(fh, header=None, dtype=str, keep_default_na=False)
    cols = list(df.iloc[0])
    seen = {}
    for i, c in enumerate(cols):  # pandas-style de-duplication (Q2_1, Q2_1.1)
        if c in seen:
            seen[c] += 1
            cols[i] = f"{c}.{seen[c]}"
        else:
            seen[c] = 0
    head = df.iloc[1:3].copy()
    body = df.iloc[3:].copy()
    head.columns = body.columns = cols
    return cols, head, body.reset_index(drop=True)


def answer_columns(study):
    """Columns the published converter filled from the LLM (they differ between human and twin files)."""
    sd = spec_dir(study)
    _, _, hum = read_qualtrics(sd / "consolidated_original_answers_values.csv.gz")
    _, _, twn = read_qualtrics(sd / "consolidated_llm_values.csv.gz")
    h = hum.set_index("TWIN_ID")
    t = twn.set_index("TWIN_ID")
    common = h.index.intersection(t.index)
    cols = [c for c in h.columns if c in t.columns and (h.loc[common, c] != t.loc[common, c]).any()]
    return cols


# ---------------------------------------------------------------- learn the answer encoding from human data
def learn_map(study):
    """(QuestionID, item) -> (column, {raw_value: csv_value} or 'identity')."""
    sd = spec_dir(study)
    _, _, hum = read_qualtrics(sd / "consolidated_original_answers_values.csv.gz")
    hum = hum.set_index("TWIN_ID")
    acols = answer_columns(study)
    rows = study_rows(study)
    obs = {}  # (qid, item) -> {pid: raw}
    names = {}
    for r in rows.itertuples():
        pid = pid_key(r.PID)
        for q in questions(r.survey_json_with_human_response):
            names[q["QuestionID"]] = q.get("QuestionName", "")
            for k, v in items(q, q.get("Answers")):
                if v in (None, ""):
                    continue
                obs.setdefault((q["QuestionID"], k), {})[pid] = v
    mapping = {}
    used = set()
    for key, vals in sorted(obs.items(), key=lambda kv: -len(kv[1])):
        pids = [p for p in vals if p in hum.index]
        if len(pids) < 5:
            continue
        best = None
        for c in acols:
            if c in used:
                continue
            col = hum.loc[pids, c]
            pairs = [(vals[p], col[p]) for p in pids if col[p] != ""]
            if len(pairs) < max(5, 0.5 * len(pids)):
                continue
            # numeric identity?
            ident = sum(1 for a, b in pairs if _num(a) is not None and _num(b) is not None and abs(_num(a) - _num(b)) < 1e-6)
            # categorical recode: modal csv value per raw value
            m = {}
            for a, b in pairs:
                m.setdefault(str(a), {}).setdefault(b, 0)
                m[str(a)][b] += 1
            recode = {a: max(cnt, key=cnt.get) for a, cnt in m.items()}
            agree = sum(1 for a, b in pairs if recode[str(a)] == b)
            injective = len(set(recode.values())) == len(recode)
            for kind, score in (("identity", ident), ("recode", agree if injective else 0)):
                cons = score / len(pairs)
                if cons >= 0.9 and (best is None or score > best[2]):
                    best = (c, kind, score, recode if kind == "recode" else None, cons, len(pairs))
        if best:
            used.add(best[0])
            mapping[key] = {"column": best[0], "kind": best[1], "recode": best[3], "consistency": round(best[4], 3), "n": best[5],
                            "question_name": names.get(key[0], "")}
    unmapped = [c for c in acols if c not in used]
    return mapping, unmapped


# ---------------------------------------------------------------- write a twin file and score it with the authors' script
def write_twin_file(study, arm, answers_by_pid, mapping):
    """answers_by_pid: pid -> {QuestionID: Answers dict}. Writes files byte-compatible with the published layout."""
    sd = spec_dir(study)
    cols, head, hum = read_qualtrics(sd / "consolidated_original_answers_values.csv.gz")
    with gzip.open(sd / "consolidated_llm_values.csv.gz", "rt") as fh:
        traw = pd.read_csv(fh, header=None, dtype=str, keep_default_na=False)
    tcols, _, _ = read_qualtrics(sd / "consolidated_llm_values.csv.gz")
    acols = set(answer_columns(study))
    twin = pd.DataFrame("", index=range(len(hum)), columns=tcols)
    for c in tcols:
        if c in hum.columns and c not in acols:
            twin[c] = hum[c].values
    by = {}
    for (qid, k), m in mapping.items():
        by.setdefault(qid, []).append((k, m))
    idx = {pid_key(p): i for i, p in enumerate(hum["TWIN_ID"])}
    for pid, ans in answers_by_pid.items():
        i = idx.get(pid_key(pid))
        if i is None:
            continue
        for qid, a in ans.items():
            vals = dict(items(None, a))
            for k, m in by.get(qid, []):
                if k not in vals or vals[k] in (None, "") or m["column"] not in twin.columns:
                    continue
                v = vals[k]
                out = v if m["kind"] == "identity" else m["recode"].get(str(v))
                if out is None:
                    continue
                twin.iat[i, twin.columns.get_loc(m["column"])] = str(out)
    rd = OUT / study / arm
    rd.mkdir(parents=True, exist_ok=True)
    keep = np.array([pid_key(p) in {pid_key(x) for x in answers_by_pid} for p in hum["TWIN_ID"]])
    with gzip.open(sd / "consolidated_original_answers_values.csv.gz", "rt") as fh:
        hraw = pd.read_csv(fh, header=None, dtype=str, keep_default_na=False)
    hout = pd.concat([hraw.iloc[:3], hraw.iloc[3:].reset_index(drop=True)[keep]], ignore_index=True)
    hout.to_csv(rd / "consolidated_original_answers_values.csv", header=False, index=False)
    out = pd.concat([traw.iloc[:3], pd.DataFrame(twin.values[keep], columns=traw.columns)], ignore_index=True)
    out.to_csv(rd / "consolidated_llm_values.csv", header=False, index=False)
    lab_path = sd / "consolidated_llm_labels.csv.gz"
    if lab_path.exists():  # some scoring scripts read option labels instead of values: map value -> label per column
        with gzip.open(lab_path, "rt") as fh:
            lraw = pd.read_csv(fh, header=None, dtype=str, keep_default_na=False)
        _, _, pv = read_qualtrics(sd / "consolidated_llm_values.csv.gz")
        lcols, _, pl = read_qualtrics(lab_path)
        lab = pd.DataFrame(twin.values[keep], columns=tcols).copy()
        for c in lcols:
            if c in pv.columns and c in acols:
                vm = {}
                for v, l in zip(pv[c], pl[c]):
                    if v != "":
                        vm.setdefault(v, l)
                hv, hl = hum[c], None
                lab[c] = [vm.get(v, v) for v in lab[c]]
        lout = pd.concat([lraw.iloc[:3], pd.DataFrame(lab[lcols].values if all(c in lab.columns for c in lcols) else lab.values, columns=lraw.columns)], ignore_index=True)
        lout.to_csv(rd / "consolidated_llm_labels.csv", header=False, index=False)
    for extra in sd.parent.glob("*human data*"):
        dst = rd.parent / extra.name.replace(".gz", "")
        if not dst.exists():
            with gzip.open(extra) as fi, open(dst, "wb") as fo:
                shutil.copyfileobj(fi, fo)
    return rd


def score(study, rd):
    script = MEGA / "mega_study_evaluation" / study / "mega_study_evaluation.py"
    p = subprocess.run([sys.executable, str(script), "--results-dir", str(rd)], cwd=str(MEGA / "mega_study_evaluation"),
                       capture_output=True, text=True)
    meta = rd / "meta analysis.csv"
    if not meta.exists():
        raise RuntimeError(p.stdout[-2000:] + p.stderr[-2000:])
    return pd.read_csv(meta)


def summarize(meta):
    c = "correlation between the responses from humans vs. their twins"
    a = "accuracy between humans vs. their twins"
    m = meta.copy()
    m["bias_sd"] = (m.mean_twin - m.mean_human).abs() / m.std_human
    m["sd_ratio"] = m.std_twin / m.std_human
    return {"outcomes": int(len(m)), "corr": round(float(m[c].mean()), 4), "acc": round(float(m[a].mean()), 4),
            "bias_sd_median": round(float(m.bias_sd.median()), 3), "sd_ratio_median": round(float(m.sd_ratio.median()), 3)}


# ---------------------------------------------------------------- converter check: human answers through our converter
def check(study):
    mapping, unmapped = learn_map(study)
    rows = study_rows(study)
    ans = {pid_key(r.PID): {q["QuestionID"]: q.get("Answers") for q in questions(r.survey_json_with_human_response)} for r in rows.itertuples()}
    rd = write_twin_file(study, "_check_human", ans, mapping)
    meta = score(study, rd)
    s = summarize(meta)
    print(study, f"mapped {len(mapping)} items, unmapped answer columns {len(unmapped)}: {unmapped[:12]}", s)
    return s, unmapped


# ---------------------------------------------------------------- simulation
_client = None


def client():
    global _client
    if _client is None:
        sys.path.insert(0, str(ROOT / "src"))
        import auth
        from google import genai
        p = auth._materialize_adc_from_env()
        if p:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p)
        _client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                               location=os.environ.get("VERTEX_LOCATION", "us-central1"), credentials=auth.vertex_credentials())
    return _client


def ask(system, prompt, retries=6):
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=TEMPERATURE, max_output_tokens=8192,
                                      response_mime_type="application/json", thinking_config=types.ThinkingConfig(thinking_budget=0))
    for i in range(retries):
        try:
            r = client().models.generate_content(model=MODEL, contents=prompt, config=cfg)
            return r.text or ""
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                return f"ERROR: {e}"
            time.sleep(min(60, 2 ** i + np.random.rand()))


def parse_llm(text, qs):
    """LLM JSON {"Q1": {"Answers": {...}}, ...} -> {QuestionID: Answers}."""
    try:
        d = json.loads(text)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", text or "", re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:  # noqa: BLE001
            d = {}
    out = {}
    for i, q in enumerate(qs, 1):
        v = d.get(f"Q{i}")
        if isinstance(v, dict):
            out[q["QuestionID"]] = v.get("Answers", v)
    return out


ARMS = {}  # name -> function(pid, study, survey_text) -> extra context string (inserted before the survey)


def arm(name):
    def deco(f):
        ARMS[name] = f
        return f
    return deco


@arm("A0_demographics")
def _a0(pid, study, survey_text):
    return ""


def run(arm_name, study, limit=None, workers=24):
    rows = study_rows(study)
    if limit:
        rows = rows.sample(min(limit, len(rows)), random_state=0)
    cache = OUT / study / arm_name / "raw.jsonl"
    cache.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["pid"]] = rec
    todo = [r for r in rows.itertuples() if str(r.PID) not in done]
    ctx_fn = ARMS[arm_name]

    def job(r):
        extra = ctx_fn(r.PID, study, r.survey_text)
        prompt = demographics_text(r.PID) + "\n" + (extra + "\n" if extra else "") + SEPARATOR + r.survey_text
        return {"pid": str(r.PID), "raw": ask(SYSTEM, prompt)}

    with open(cache, "a") as fh, ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(job, r) for r in todo]
        for k, f in enumerate(as_completed(futs)):
            rec = f.result()
            fh.write(json.dumps(rec) + "\n")
            done[rec["pid"]] = rec
            if (k + 1) % 100 == 0:
                fh.flush()
                print(f"  {study}/{arm_name}: {k + 1}/{len(todo)}", flush=True)
    keep = {str(p) for p in rows.PID}
    qs = {str(r.PID): questions(r.survey_json_with_human_response) for r in rows.itertuples()}
    answers = {pid: parse_llm(rec["raw"], qs[pid]) for pid, rec in done.items() if pid in keep}
    fails = sum(1 for a in answers.values() if not a)
    mapping, _ = learn_map(study)
    rd = write_twin_file(study, arm_name, answers, mapping)
    s = summarize(score(study, rd)) | {"people": len(answers), "parse_failures": fails}
    (rd / "summary.json").write_text(json.dumps(s, indent=1))
    print(study, arm_name, s, flush=True)
    return s




# ================================================================ population-knowledge arms (A3 naive RAG, A4 harness)
EMB_MODEL = "text-embedding-005"
EMB_CACHE = ROOT / "data" / "people_repo" / "emb_cache.pkl"
_emb = None
_index = None
_qcache = {}


def embed(texts):
    import pickle
    global _emb
    if _emb is None:
        _emb = pickle.loads(EMB_CACHE.read_bytes()) if EMB_CACHE.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if t not in _emb]
    for i in range(0, len(missing), 50):
        chunk = missing[i:i + 50]
        for attempt in range(6):
            try:
                resp = client().models.embed_content(model=EMB_MODEL, contents=chunk)
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 ** attempt)
        for t, e in zip(chunk, resp.embeddings):
            _emb[t] = np.asarray(e.values, np.float32)
    if missing:
        EMB_CACHE.parent.mkdir(parents=True, exist_ok=True)
        EMB_CACHE.write_bytes(pickle.dumps(_emb))
    return np.stack([_emb[t] for t in texts])


def item_text(it):
    return f"{it['text']} | options: {'; '.join(it['options'][:8])}"


def index():
    global _index
    if _index is None:
        from human_sim import people_repo as PR
        items = [it for it in PR.load() if it.get("overall") or it.get("by")]
        E = embed([item_text(it) for it in items])
        E /= np.linalg.norm(E, axis=1, keepdims=True)
        _index = (items, E)
    return _index


def clean(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(t))).strip()[:400]


def study_questions(study):
    """Distinct question texts shown in a study (for retrieval)."""
    if study not in _qcache:
        rows = study_rows(study)
        seen = {}
        for s in rows.survey_json_with_human_response.head(200):
            for q in questions(s):
                t = clean(q.get("QuestionText", ""))
                rows_ = q.get("Rows") or []
                if rows_:
                    t = f"{t} {clean(' / '.join(map(str, rows_[:3])))}"
                if len(t) > 15:
                    seen[t] = 1
        _qcache[study] = list(seen)
    return _qcache[study]


def retrieve(study, per_q=3, cap=8):
    items, E = index()
    qs = study_questions(study)
    Q = embed(qs)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    S = Q @ E.T
    best = {}
    for i in range(len(qs)):
        for j in np.argsort(-S[i])[:per_q]:
            best[j] = max(best.get(j, -1), float(S[i, j]))
    order = sorted(best.items(), key=lambda kv: -kv[1])[:cap]
    return [(items[j], s) for j, s in order]


def fmt_dist(options, p):
    return "; ".join(f"{o} {100 * x:.0f}%" for o, x in zip(options, p))


_retr = {}


@arm("A3_naive_rag")
def _a3(pid, study, survey_text):
    """Generic RAG: the most similar public survey items with their overall answer distributions, same for everyone."""
    if study not in _retr:
        _retr[study] = retrieve(study)
    lines = ["## Public survey data that may be relevant (US adults):"]
    for it, s in _retr[study]:
        if it.get("overall"):
            lines.append(f"- [{it['source']}] \"{it['text']}\": {fmt_dist(it['options'], it['overall'])}")
    return "\n".join(lines)


_profiles = None


def profile(pid):
    global _profiles
    from human_sim import people_repo as PR
    if _profiles is None:
        lab = pd.read_csv(TWIN / "wave1_3_response_label.csv", usecols=["pid"] + DEMO_QIDS).set_index("pid")
        _profiles = lab
    row = _profiles.loc[int(pid_key(pid))].to_dict()
    return PR.twin_profile(row)


SIM_MIN = 0.60  # retrieval similarity floor for A4, fixed from item-text inspection only (no Mega-Study answers)
_sketch_pool = None


def sketch(prof, k=8):
    """What distinguishes people with this profile from the average US adult, from GSS items (largest shifts)."""
    from human_sim import people_repo as PR
    global _sketch_pool
    if _sketch_pool is None:
        items, _ = index()
        _sketch_pool = [it for it in items if it["source"] == "GSS" and it.get("overall") and max(it["years"]) >= 2010 and len(it["options"]) <= 7]
    scored = []
    for it in _sketch_pool:
        p, used = PR.conditional(it, prof)
        if p is None or len(used) < 3:
            continue
        o = np.asarray(it["overall"])
        d = np.asarray(p) - o
        j = int(np.argmax(np.abs(d)))
        scored.append((0.5 * np.abs(d).sum(), it, j, p))
    scored.sort(key=lambda x: -x[0])
    out = []
    for tvd, it, j, p in scored[:k]:
        more = "more" if p[j] > it["overall"][j] else "less"
        out.append(f"- \"{it['text']}\": people with this profile are {more} likely than average to answer \"{it['options'][j]}\" "
                   f"({100 * p[j]:.0f}% vs {100 * it['overall'][j]:.0f}%)")
    return out


@arm("A4_harness")
def _a4(pid, study, survey_text):
    """UserSim harness: retrieved items conditioned on this person's demographic profile, a data-based sketch of how
    people like them differ from average, and instructions to use real spread rather than the modal answer."""
    from human_sim import people_repo as PR
    if study not in _retr:
        _retr[study] = retrieve(study)
    prof = profile(pid)
    lines = ["## What public survey data says about people like this person (US adults; GSS and Pew panels)"]
    rel = [(it, s) for it, s in _retr[study] if s >= SIM_MIN]
    if rel:
        lines.append("Answers to related questions — everyone vs. people with this person's profile:")
        for it, s in rel:
            p, used = PR.conditional(it, prof)
            if p is None:
                continue
            base = fmt_dist(it["options"], it["overall"]) if it.get("overall") else "n/a"
            lines.append(f"- \"{it['text']}\"\n    everyone: {base}\n    people like this person ({', '.join(used) or 'no group data'}): {fmt_dist(it['options'], p)}")
    sk = sketch(prof)
    if sk:
        lines.append("How people with this profile differ from the average adult:")
        lines += sk
    lines.append("Use this as evidence about where this person likely falls. Real people differ a lot from one another: "
                 "do not default to the most common or the most moderate answer; answer where someone with this profile "
                 "would typically land, including strong or negative answers when the data points that way.")
    return "\n".join(lines)


# ================================================================ comparison across arms
def compare(arms=("A0_demographics", "A3_naive_rag", "A4_harness")):
    """Pool per-outcome results over studies where every arm finished; add the published GPT-4.1 arms as references."""
    c = "correlation between the responses from humans vs. their twins"
    a = "accuracy between humans vs. their twins"
    rows = []
    for sd in sorted(OUT.iterdir()):
        if not sd.is_dir():
            continue
        metas = {}
        for arm_name in arms:
            f = sd / arm_name / "meta analysis.csv"
            if f.exists():
                metas[arm_name] = pd.read_csv(f)
        if len(metas) < len(arms):
            continue
        for arm_name, m in metas.items():
            m = m.assign(study=sd.name, arm=arm_name)
            rows.append(m)
    if not rows:
        return None
    d = pd.concat(rows)
    d["bias_sd"] = (d.mean_twin - d.mean_human).abs() / d.std_human
    d["sd_ratio"] = d.std_twin / d.std_human
    d["sd_err"] = (np.log(d.sd_ratio.clip(1e-3))).abs()
    key = ["study", "variable name"]
    common = d.groupby(key).arm.nunique()
    common = common[common == len(arms)].index
    d = d.set_index(key).loc[common].reset_index()
    out = d.groupby("arm").agg(outcomes=(c, "size"), corr=(c, "mean"), acc=(a, "mean"), bias_sd=("bias_sd", "mean"),
                               sd_ratio_median=("sd_ratio", "median"), sd_log_err=("sd_err", "mean")).round(4)
    # paired bootstrap of A4 - A0 and A4 - A3 over outcomes
    piv = d.pivot_table(index=key, columns="arm", values=[c, "bias_sd", "sd_err"])
    rng = np.random.default_rng(0)
    deltas = {}
    for x, y in (("A4_harness", "A0_demographics"), ("A3_naive_rag", "A0_demographics"), ("A4_harness", "A3_naive_rag")):
        for metric, sign in ((c, 1), ("bias_sd", -1), ("sd_err", -1)):
            diff = (piv[(metric, x)] - piv[(metric, y)]).to_numpy() * sign
            bs = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(2000)]
            deltas[f"{x} vs {y} | {metric[:11]} (higher=better)"] = [round(float(diff.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
    by_study = d.pivot_table(index="study", columns="arm", values=c, aggfunc="mean").round(3)
    res = {"summary": out.reset_index().to_dict("records"), "deltas": deltas, "corr_by_study": by_study.reset_index().to_dict("records")}
    (OUT / "comparison.json").write_text(json.dumps(res, indent=1))
    print(out.to_string()); print(json.dumps(deltas, indent=1)); print(by_study.to_string())
    return res


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "check":
        check(sys.argv[2])
    elif cmd == "run":
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else None)
    elif cmd == "compare":
        compare()
