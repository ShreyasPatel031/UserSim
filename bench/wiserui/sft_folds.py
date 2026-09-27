#!/usr/bin/env python3
"""Supervised fine-tuning of gemini-2.5-flash on the short-pick prompt, with 5-fold cross-validation (research only).

WiserUI-Bench is CC BY-NC-SA: tuned models are for this experiment only and are never wired into the product.

Subcommands (run in order):
  folds   seeded 5-fold split of the 252 clean pairs, stratified by source; writes fullset/sft_folds.json (indices only)
  build   per fold, training rows for every pair NOT in the fold, both presentation orders: the exact short-pick user
          turn (mvp.pairwise.short_pick_prompt + both screenshots fit to 768 px) and the target
          "Better version: First/Second" + "Reason: <one or two sentences>". The reason is the baseline G-FOCUS
          Evaluator's own Key Rationale (first bullet, condensed) where it picked correctly, else the pick alone.
          The dataset's rationale / ui_change / UX-law text is never used. Images and JSONL go to GCS
          ($SFT_GCS, private project bucket); local copies stay in $WISERUI_BENCH/ft/sft (not committed).
  count   count tokens of sample rows (training-cost estimate before launching)
  launch  one Vertex SFT job per fold (gemini-2.5-flash, --epochs), all at once; job names -> ft/sft/jobs.json
  status  poll the jobs: state, times, tuned endpoint, billed training tokens
  merge   merge per-fold held-out runs (results/sft_tuned_fold{k}) into one out-of-fold run dir

Single split (one job instead of five): ``build-split`` trains on the 177 non-dev clean pairs x 2 orders
(fullset/heldout177_indices.txt) and tests on the 75 dev pairs (dev_indices.txt), same row builder; ``count --split``,
``launch --split`` (exactly one job; refuses if ft/sft/split_job.json already names one) and ``status --split``.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(HERE)]

import run_bench as rb  # noqa: E402
from mvp.pairwise import fit_image, short_pick_prompt  # noqa: E402

BENCH = rb.BENCH
SFT = BENCH / "ft" / "sft"
FOLDS = HERE / "fullset" / "sft_folds.json"
MAIN = HERE / "fullset" / "final_indices_main.txt"
BASE_ROWS = BENCH / "ft" / "flash_inputs_base.jsonl"  # export_ft.py rows of the baseline G-FOCUS single-judge run
GCS = os.environ.get("SFT_GCS", "gs://usersim-bakeoff-347838016394/wiserui-sft")
MAX_PX = 768
K = 5
SEED = 20260927


def indices() -> list[int]:
    return [int(x) for x in MAIN.read_text().replace("\n", ",").split(",") if x.strip()]


def data() -> dict[int, dict]:
    return {x["index"]: x for x in json.load(open(rb.DATA))}


def cmd_folds(_a) -> None:
    d = data()
    by_src: dict[str, list[int]] = collections.defaultdict(list)
    for i in indices():
        by_src[rb.source_of(d[i])].append(i)
    rng = random.Random(SEED)
    folds: list[list[int]] = [[] for _ in range(K)]
    start = 0
    for src in sorted(by_src):
        xs = sorted(by_src[src])
        rng.shuffle(xs)
        for j, i in enumerate(xs):
            folds[(start + j) % K].append(i)
        start = (start + len(xs)) % K  # keep fold sizes within 1 of each other overall
    FOLDS.write_text(json.dumps({"seed": SEED, "k": K, "stratified_by": "source",
                                 "folds": [sorted(f) for f in folds]}, indent=0))
    for k, f in enumerate(folds):
        c = collections.Counter(rb.source_of(d[i]) for i in f)
        print(f"fold {k}: n={len(f)} {dict(c)}")


def load_folds() -> list[list[int]]:
    return json.loads(FOLDS.read_text())["folds"]


def condense(brief: str, max_chars: int = 320) -> str:
    """First Key-Rationale bullet, markdown stripped, cut to 1-2 sentences (<= max_chars where possible)."""
    t = (brief or "").replace("**", "").strip()
    bullets = [b.strip() for b in re.split(r"(?:^|\s)\*\s+", t) if b.strip()]
    first = bullets[0] if bullets else t
    first = " ".join(first.replace("*", "").split())
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", first)
    out = sents[0]
    if len(sents) > 1 and len(out) + 1 + len(sents[1]) <= max_chars:
        out += " " + sents[1]
    if len(out) > 450:  # one run-on sentence: cut at a word boundary
        out = out[:450].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return out


def target(gold: str, row: dict | None) -> str:
    if row and row.get("correct") and row.get("pick") == gold and row.get("brief_reasoning"):
        r = condense(row["brief_reasoning"])
        if r:
            return f"Better version: {gold}\nReason: {r}"
    return f"Better version: {gold}"


def pair_rows(i: int, item: dict, base: dict) -> list[dict]:
    """Both presentation orders of pair i: {'index','order','first','second','gold','target'} (first/second = win|lose)."""
    aw = rb.a_is_win(i)
    a, b = ("win", "lose") if aw else ("lose", "win")
    out = []
    for o in ("ab", "ba"):
        first, second = (a, b) if o == "ab" else (b, a)
        gold = "First" if first == "win" else "Second"
        br = base.get((i, o))
        if br is not None:
            assert br["gold"] == gold, (i, o, br["gold"], gold)
        out.append({"index": i, "order": o, "first": first, "second": second, "gold": gold,
                    "target": target(gold, br), "ctx": rb.ctx_of(item)})
    return out


def img_local(i: int, label: str) -> Path:
    return SFT / "img" / f"{i}_{label}.png"


def img_uri(i: int, label: str) -> str:
    return f"{GCS}/img/{i}_{label}.png"


def sft_record(r: dict) -> dict:
    return {"contents": [
        {"role": "user", "parts": [
            {"text": short_pick_prompt(r["ctx"])},
            {"fileData": {"mimeType": "image/png", "fileUri": img_uri(r["index"], r["first"])}},
            {"fileData": {"mimeType": "image/png", "fileUri": img_uri(r["index"], r["second"])}}]},
        {"role": "model", "parts": [{"text": r["target"]}]}]}


def gcs_bucket():
    from google.cloud import storage

    from config import GCP_PROJECT

    bucket, _, prefix = GCS[5:].partition("/")
    return storage.Client(project=os.environ.get("GCP_PROJECT") or GCP_PROJECT).bucket(bucket), prefix


def cmd_build(a) -> None:
    d = data()
    base = {(r["index"], r["order"]): r for r in map(json.loads, BASE_ROWS.open())}
    folds = load_folds()
    (SFT / "img").mkdir(parents=True, exist_ok=True)
    rows = {i: pair_rows(i, d[i], base) for f in folds for i in f}
    for i in rows:
        for lab in ("win", "lose"):
            p = img_local(i, lab)
            if not p.exists():
                p.write_bytes(fit_image((rb.image_dir(i) / f"{lab}.png").read_bytes(), MAX_PX))
    stats = {}
    for k, test in enumerate(folds):
        train = [r for f in folds[:k] + folds[k + 1:] for i in f for r in rows[i]]
        random.Random(SEED + k).shuffle(train)
        with (SFT / f"fold{k}_train.jsonl").open("w") as f:
            for r in train:
                f.write(json.dumps(sft_record(r), ensure_ascii=False) + "\n")
        (SFT / f"fold{k}_test_indices.txt").write_text(",".join(map(str, test)))
        c = collections.Counter(r["gold"] for r in train)
        stats[k] = {"train_rows": len(train), "train_pairs": len(train) // 2, "test_pairs": len(test),
                    "first": c["First"], "second": c["Second"],
                    "with_reason": sum("\nReason:" in r["target"] for r in train)}
        print(f"fold {k}: {stats[k]}")
    allr = [r for v in rows.values() for r in v]
    lens = [len(r["target"]) for r in allr if "\nReason:" in r["target"]]
    print(f"all rows {len(allr)}: with reason {len(lens)}, pick-only {len(allr) - len(lens)}, "
          f"reason chars median {sorted(lens)[len(lens) // 2]}, max {max(lens)}")
    (SFT / "build_stats.json").write_text(json.dumps(stats, indent=1))
    with (SFT / "targets_preview.jsonl").open("w") as f:
        for r in allr:
            f.write(json.dumps({k: r[k] for k in ("index", "order", "gold", "target")}, ensure_ascii=False) + "\n")
    if a.upload:
        bucket, prefix = gcs_bucket()
        from concurrent.futures import ThreadPoolExecutor

        def up(p: Path, name: str, ctype: str) -> None:
            bl = bucket.blob(f"{prefix}/{name}")
            if name.startswith("img/") and bl.exists():
                return
            bl.upload_from_filename(str(p), content_type=ctype)

        jobs = [(img_local(i, lab), f"img/{i}_{lab}.png", "image/png") for i in rows for lab in ("win", "lose")]
        jobs += [(SFT / f"fold{k}_train.jsonl", f"fold{k}_train.jsonl", "application/jsonl") for k in range(K)]
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(lambda j: up(*j), jobs))
        print(f"uploaded {len(jobs)} objects to {GCS}")


SPLIT_TRAIN = HERE / "fullset" / "heldout177_indices.txt"
SPLIT_TEST = HERE / "dev_indices.txt"
SPLIT_JOB = SFT / "split_job.json"


def cmd_build_split(a) -> None:
    d = data()
    base = {(r["index"], r["order"]): r for r in map(json.loads, BASE_ROWS.open())}
    ids = lambda f: [int(x) for x in f.read_text().replace("\n", ",").split(",") if x.strip()]  # noqa: E731
    train_ids, test_ids = ids(SPLIT_TRAIN), ids(SPLIT_TEST)
    assert not set(train_ids) & set(test_ids)
    (SFT / "img").mkdir(parents=True, exist_ok=True)
    for i in train_ids:
        for lab in ("win", "lose"):
            p = img_local(i, lab)
            if not p.exists():
                p.write_bytes(fit_image((rb.image_dir(i) / f"{lab}.png").read_bytes(), MAX_PX))
    train = [r for i in train_ids for r in pair_rows(i, d[i], base)]
    random.Random(SEED).shuffle(train)
    with (SFT / "split_train.jsonl").open("w") as f:
        for r in train:
            f.write(json.dumps(sft_record(r), ensure_ascii=False) + "\n")
    (SFT / "split_test_indices.txt").write_text(",".join(map(str, test_ids)))
    c = collections.Counter(r["gold"] for r in train)
    stats = {"train_rows": len(train), "train_pairs": len(train_ids), "test_pairs": len(test_ids), "first": c["First"],
             "second": c["Second"], "with_reason": sum("\nReason:" in r["target"] for r in train)}
    (SFT / "split_stats.json").write_text(json.dumps(stats, indent=1))
    print(stats)
    if a.upload:
        bucket, prefix = gcs_bucket()
        from concurrent.futures import ThreadPoolExecutor

        def up(p: Path, name: str, ctype: str) -> None:
            bl = bucket.blob(f"{prefix}/{name}")
            if name.startswith("img/") and bl.exists():
                return
            bl.upload_from_filename(str(p), content_type=ctype)

        jobs = [(img_local(i, lab), f"img/{i}_{lab}.png", "image/png") for i in train_ids for lab in ("win", "lose")]
        jobs.append((SFT / "split_train.jsonl", "split_train.jsonl", "application/jsonl"))
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(lambda j: up(*j), jobs))
        print(f"uploaded {len(jobs)} objects to {GCS}")


def client(location: str = "us-central1"):
    from mvp.e2e_ui_run import _gemini_client_at

    return _gemini_client_at(location)


def cmd_count(a) -> None:
    from google.genai import types

    cl = client()
    src = SFT / ("split_train.jsonl" if a.split else "fold0_train.jsonl")
    allrecs = [json.loads(line) for line in src.open()]
    recs = random.Random(1).sample(allrecs, min(a.n, len(allrecs)))
    tot = []
    for rec in recs:
        parts = []
        for turn in rec["contents"]:
            ps = []
            for p in turn["parts"]:
                if "text" in p:
                    ps.append(types.Part.from_text(text=p["text"]))
                else:
                    name = p["fileData"]["fileUri"].rsplit("/", 1)[1]
                    ps.append(types.Part.from_bytes(data=(SFT / "img" / name).read_bytes(), mime_type="image/png"))
            parts.append(types.Content(role=turn["role"], parts=ps))
        n = cl.models.count_tokens(model="gemini-2.5-flash", contents=parts).total_tokens
        tot.append(n)
    mean = sum(tot) / len(tot)
    rows = (len(allrecs) if a.split else
            sum(json.loads((SFT / "build_stats.json").read_text())[str(k)]["train_rows"] for k in range(K)))
    print(f"tokens/row over {len(tot)} rows: mean {mean:.0f} min {min(tot)} max {max(tot)}")
    for ep in (2, 3):
        t = mean * rows * ep
        print(f"  {ep} epochs: {rows} rows x {ep} = {t / 1e6:.2f}M training tokens -> ${t / 1e6 * 5:.2f} at $5/1M")


def cmd_launch(a) -> None:
    from google.genai import types

    if a.split:
        if SPLIT_JOB.exists():
            raise SystemExit(f"already launched: {json.loads(SPLIT_JOB.read_text())['name']}")
        job = client(a.location).tunings.tune(
            base_model="gemini-2.5-flash",
            training_dataset=types.TuningDataset(gcs_uri=f"{GCS}/split_train.jsonl"),
            config=types.CreateTuningJobConfig(epoch_count=a.epochs, tuned_model_display_name="wiserui-shortpick-split"),
        )
        SPLIT_JOB.write_text(json.dumps({"name": job.name, "location": a.location, "epochs": a.epochs,
                                         "launched": time.time()}, indent=1))
        print(f"split: {job.name} {job.state}")
        return

    jf = SFT / "jobs.json"
    jobs = json.loads(jf.read_text()) if jf.exists() else {}
    for k in range(K):
        if str(k) in jobs:
            print(f"fold {k}: already launched {jobs[str(k)]['name']}")
            continue
        loc = a.location
        job = client(loc).tunings.tune(
            base_model="gemini-2.5-flash",
            training_dataset=types.TuningDataset(gcs_uri=f"{GCS}/fold{k}_train.jsonl"),
            config=types.CreateTuningJobConfig(epoch_count=a.epochs, tuned_model_display_name=f"wiserui-shortpick-f{k}"),
        )
        jobs[str(k)] = {"name": job.name, "location": loc, "epochs": a.epochs, "launched": time.time()}
        jf.write_text(json.dumps(jobs, indent=1))
        print(f"fold {k}: {job.name} {job.state}")


def cmd_status(a) -> None:
    jf = SPLIT_JOB if a.split else SFT / "jobs.json"
    jobs = {"split": json.loads(jf.read_text())} if a.split else json.loads(jf.read_text())
    for k, j in sorted(jobs.items()):
        job = client(j["location"]).tunings.get(name=j["name"])
        j["state"] = str(job.state)
        j["create_time"] = str(job.create_time)
        j["start_time"] = str(job.start_time)
        j["end_time"] = str(job.end_time)
        if job.tuned_model and job.tuned_model.endpoint:
            j["endpoint"] = job.tuned_model.endpoint
        ds = getattr(job, "tuning_data_stats", None)
        sd = getattr(ds, "supervised_tuning_data_stats", None) if ds else None
        if sd:
            j["billable_tokens"] = getattr(sd, "total_billable_token_count", None)
            j["tuning_dataset_examples"] = getattr(sd, "tuning_dataset_example_count", None)
            j["tuning_step_count"] = getattr(sd, "tuning_step_count", None)
        if job.error:
            j["error"] = str(job.error)[:300]
        print(f"fold {k}: {j['state']} created {j['create_time']} ended {j['end_time']} "
              f"billable={j.get('billable_tokens')} endpoint={j.get('endpoint')}")
    jf.write_text(json.dumps(jobs["split"] if a.split else jobs, indent=1))


def cmd_merge(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    with (out / "pairs.jsonl").open("w") as fp, (out / "calls.jsonl").open("w") as fc:
        for k in range(K):
            src = Path(a.pattern.format(k=k))
            for line in (src / "pairs.jsonl").open():
                rec = json.loads(line)
                assert rec["index"] not in seen
                seen.add(rec["index"])
                rec["fold"] = k
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for line in (src / "calls.jsonl").open():
                fc.write(line)
    print(f"merged {len(seen)} pairs into {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("folds")
    b = sub.add_parser("build")
    b.add_argument("--upload", action="store_true")
    bs = sub.add_parser("build-split")
    bs.add_argument("--upload", action="store_true")
    c = sub.add_parser("count")
    c.add_argument("--n", type=int, default=12)
    c.add_argument("--split", action="store_true")
    la = sub.add_parser("launch")
    la.add_argument("--split", action="store_true")
    la.add_argument("--epochs", type=int, default=3)
    la.add_argument("--location", default="us-central1")
    st = sub.add_parser("status")
    st.add_argument("--split", action="store_true")
    m = sub.add_parser("merge")
    m.add_argument("--pattern", default=str(BENCH / "results" / "sft_tuned_fold{k}"))
    m.add_argument("--out", default=str(BENCH / "results" / "sft_tuned_oof"))
    a = ap.parse_args()
    globals()[f"cmd_{a.cmd.replace('-', '_')}"](a)


if __name__ == "__main__":
    main()
