#!/usr/bin/env python3
"""Zero-shot accuracy probe: Qwen3-14B, thinking off, greedy, 5 unseen studies.

Does not train. Scores paper individual accuracy (1 - normalized MAE),
plus the clipped variant. Writes predictions and SUMMARY under RESULTS_DIR.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

# Official FP8 checkpoint of Qwen3-14B. bf16 does not fit a 24GB L4, and this
# vLLM build has no bitsandbytes loader. Weights are the post-trained model.
MODEL = os.environ.get("PROBE_MODEL", "Qwen/Qwen3-14B-FP8")
# 0 means every unseen study. A positive value keeps the first N sorted ids.
N_STUDIES = int(os.environ.get("SMOKE_STUDIES", "5"))
RESULTS = Path(os.environ.get("RESULTS_DIR", "/opt/usersim_fm/results/acc_probe_qwen3_14b"))
SYSTEM = (
    "You are a participant in a survey experiment. "
    "Answer with a single number only when a numeric response is required."
)


def paper_accuracy(preds: list[dict], clip: bool) -> tuple[float | None, int, int]:
    cells: dict[tuple, list] = defaultdict(list)
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(h) and np.isfinite(m)):
            continue
        cells[(p["study_id"], str(p["condition_num"]), str(p["task_num"]))].append((h, m))
    ranges = {}
    for key, items in cells.items():
        hs = [h for h, _ in items]
        rmin, rmax = min(hs), max(hs)
        if rmax > rmin:
            ranges[key] = (rmin, rmax)
    per: dict[str, list] = defaultdict(list)
    used = 0
    for p in preds:
        if p.get("pred") is None:
            continue
        try:
            h = float(p["human"])
            m = float(p["pred"])
        except (TypeError, ValueError):
            continue
        key = (p["study_id"], str(p["condition_num"]), str(p["task_num"]))
        if key not in ranges:
            continue
        rmin, rmax = ranges[key]
        if clip:
            m = min(max(m, rmin), rmax)
        per[p["study_id"]].append(abs(m - h) / (rmax - rmin))
        used += 1
    study = {s: 1.0 - float(np.mean(errs)) for s, errs in per.items() if errs}
    overall = float(np.mean(list(study.values()))) if study else None
    return overall, len(study), used


def sample_id(rec: dict) -> str:
    return (
        f"{rec['study_id']}|{rec['sample_id']}|{rec['condition_num']}|"
        f"{rec['task_num']}|{rec['participant']}"
    )


def load_done_ids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            done.add(json.loads(line)["sample_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def parse_pred(text: str) -> tuple[float | None, bool]:
    stripped = (text or "").strip()
    bare = re_fullmatch_number(stripped)
    try:
        return float(stripped), bare
    except ValueError:
        import re

        match = re.search(r"[-+]?\d*\.?\d+", stripped.replace(",", ""))
        if not match:
            return None, bare
        try:
            return float(match.group(0)), bare
        except ValueError:
            return None, bare


def main() -> None:
    from datasets import load_dataset
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    RESULTS.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(
        Path(
            hf_hub_download(
                "socratesft/SocSci210",
                "metadata/participant_mapping.json",
                repo_type="dataset",
            )
        ).read_text()
    )
    unseen = sorted(mapping["unseen"])
    keep = set(unseen if N_STUDIES <= 0 else unseen[:N_STUDIES])
    print(f"studies={len(keep)} model={MODEL}", flush=True)

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    cache = RESULTS / "rows.jsonl"
    if cache.exists() and cache.stat().st_size > 0:
        rows = [json.loads(line) for line in cache.read_text().splitlines() if line.strip()]
        print(f"rows={len(rows)} from cache", flush=True)
    else:
        print("loading rows", flush=True)
        rows = []
        ds = load_dataset("socratesft/SocSci210", split="train")
        for rec in ds:
            if rec["study_id"] in keep:
                rows.append(rec)
        with cache.open("w") as fout:
            for rec in rows:
                fout.write(json.dumps(rec) + "\n")
        print(f"rows={len(rows)}", flush=True)

    by_study: dict[str, list] = defaultdict(list)
    for rec in rows:
        by_study[rec["study_id"]].append(rec)
    study_dir = RESULTS / "studies"
    study_dir.mkdir(parents=True, exist_ok=True)

    def study_pending(study: str) -> list[dict]:
        done = load_done_ids(study_dir / f"{study}.jsonl")
        return [rec for rec in by_study[study] if sample_id(rec) not in done]

    pending_studies = [s for s in sorted(by_study) if study_pending(s)]
    for study in sorted(by_study):
        marker = study_dir / f"{study}.done"
        if study not in pending_studies and not marker.exists():
            marker.write_text("already complete\n")
    print(
        f"studies_total={len(by_study)} studies_done={len(by_study) - len(pending_studies)} "
        f"studies_left={len(pending_studies)}",
        flush=True,
    )

    temperature = float(os.environ.get("TEMPERATURE", "0"))
    top_p = float(os.environ.get("TOP_P", "0.9"))
    llm = None
    sampling = None
    if pending_studies:
        probe = tok.apply_chat_template(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Reply with 1."},
            ],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        if "<think>" in probe and "</think>" not in probe:
            raise SystemExit("thinking still open in the prompt")
        lora_path = os.environ.get("LORA_PATH", "").strip()
        print("loading model", flush=True)
        llm_kwargs = dict(
            model=MODEL,
            max_model_len=4096,
            gpu_memory_utilization=0.90,
            trust_remote_code=True,
        )
        if lora_path:
            llm_kwargs.update(enable_lora=True, max_loras=1, max_lora_rank=16)
        llm = LLM(**llm_kwargs)
        lora_request = None
        if lora_path:
            from vllm.lora.request import LoRARequest

            lora_request = LoRARequest("distmatch", 1, lora_path)
            print(f"lora={lora_path}", flush=True)
        if temperature <= 0:
            sampling = SamplingParams(temperature=0.0, max_tokens=16)
        else:
            sampling = SamplingParams(temperature=temperature, top_p=top_p, max_tokens=16)
        print(f"sampling temperature={temperature} top_p={top_p}", flush=True)

    started = time.time()
    total_rows = len(rows)
    for study in pending_studies:
        pending = study_pending(study)
        prompts = [
            tok.apply_chat_template(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": rec["prompt"]},
                ],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            for rec in pending
        ]
        path = study_dir / f"{study}.jsonl"
        print(f"study {study} pending={len(pending)}/{len(by_study[study])}", flush=True)
        with path.open("a") as fout:
            for i in range(0, len(prompts), 256):
                outs = llm.generate(prompts[i : i + 256], sampling, lora_request=lora_request)
                for rec, out in zip(pending[i : i + 256], outs):
                    text = out.outputs[0].text if out.outputs else ""
                    pred, _bare = parse_pred(text)
                    fout.write(
                        json.dumps(
                            {
                                "sample_id": sample_id(rec),
                                "study_id": rec["study_id"],
                                "condition_num": str(rec["condition_num"]),
                                "task_num": str(rec["task_num"]),
                                "human": rec["response"],
                                "pred_raw": text,
                                "pred": pred,
                            }
                        )
                        + "\n"
                    )
                fout.flush()
                os.fsync(fout.fileno())
        (study_dir / f"{study}.done").write_text(
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n"
        )
        done_n = sum(len(load_done_ids(study_dir / f"{s}.jsonl")) for s in by_study)
        print(f"study_done {study} progress={done_n}/{total_rows}", flush=True)
        (RESULTS / "PROGRESS.json").write_text(
            json.dumps(
                {
                    "last_study": study,
                    "studies_done": len(list(study_dir.glob("*.done"))),
                    "studies_total": len(by_study),
                    "n_preds": done_n,
                    "n_rows": total_rows,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                indent=2,
            )
            + "\n"
        )

    preds = []
    for path in sorted(study_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                preds.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by_id = {p["sample_id"]: p for p in preds if "sample_id" in p}
    preds = list(by_id.values())
    acc_raw, n_studies, used = paper_accuracy(preds, clip=False)
    acc_clip, _, _ = paper_accuracy(preds, clip=True)
    per_acc: dict[str, float] = {}
    # Recompute per-study accuracy with the same raw definition.
    grouped: dict[str, list] = defaultdict(list)
    for pred in preds:
        grouped[pred["study_id"]].append(pred)
    for study, items in grouped.items():
        study_acc, _, _ = paper_accuracy(items, clip=False)
        if study_acc is not None:
            per_acc[study] = study_acc
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from socrates_metric import score as wasserstein_score

    wagg = wasserstein_score(preds)
    parsed = sum(1 for p in preds if p.get("pred") is not None)
    bare = sum(1 for p in preds if re_fullmatch_number((p.get("pred_raw") or "").strip()))
    summary = {
        "model": MODEL,
        "lora": os.environ.get("LORA_PATH", "").strip() or None,
        "role": "distmatch_qlora_gate" if os.environ.get("LORA_PATH", "").strip() else "zero_shot_instruct_probe",
        "thinking": False,
        "temperature": temperature,
        "top_p": top_p if temperature > 0 else None,
        "studies": sorted(keep),
        "n_preds": len(preds),
        "n_parsed": parsed,
        "bare_numeric": bare,
        "parse_rate": parsed / len(preds) if preds else None,
        "accuracy_raw": acc_raw,
        "accuracy_clipped": acc_clip,
        "per_study_acc": per_acc,
        "wasserstein_mean": wagg.get("wasserstein_mean"),
        "uniform_control": wagg.get("uniform_control"),
        "per_study_w": wagg.get("per_study"),
        "n_studies": n_studies,
        "n_used": used,
        "elapsed_s": round(time.time() - started, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (RESULTS / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in summary if not str(k).startswith("per_study") and k != "studies"}, indent=2), flush=True)


def re_fullmatch_number(text: str) -> bool:
    import re

    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text.strip()))


if __name__ == "__main__":
    main()
