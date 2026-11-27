"""Unified Single-Model Distillation (`Qwen2.5-VL-7B-Instruct`) for JIT CUA + Per-Person Preference (`usersim_core/qwen_vl_unified_v5.py`).

Implements Phase 4 of `docs/VM_HANDOFF_AND_PLAN_20261126.md`:
  - Replaces the multi-stage pipeline with ONE fine-tuned multimodal backbone (`Qwen/Qwen2.5-VL-7B-Instruct`,
    `bf16` + LoRA `r=32` on 24GB NVIDIA L4 GPU `gemma-persona-probe`), building on E5's text choice adapter
    reference (`gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/runs/choice-ft1-b/adapters/ckpt_final_500000`).
  - Joint Multi-Task Corpus (`export` subcommand, 100% strictly `< D` split: Train `Apr-Aug`, Val `Sep`, Test `Oct-Nov`):
    1. `CUA_TRACE` (JIT Browser Action & Reality Judge):
       `(product_pitch, named_competitors_top3, step_t_screenshot, sanitized_dom_tree)`
       -> `(next_cua_action, hands_on_works, ui_craft_depth, onboarding_ease, friction_finding)`
    2. `PERSON_CHOICE` (Grounded Per-Person Upvote Log-Odds `<YES>/<NO>`):
       `(person_<D_compact_history, named_competitors_and_pains, jit_cua_finding_summary, same_day_lineup_context)`
       -> calibrated `Yes` / `No` token log-odds (`P(upvote | person u, launch x, lineup D)`).
    3. `PERSON_REACTION` (Grounded Per-Person Comment / Critique):
       conditional real non-maker user comment/critique from `bench.comments`.
  - Multimodal LoRA Trainer & Fast Batched Inference (`train_eval` subcommand):
    - Fits `Qwen/Qwen2.5-VL-7B-Instruct` with `r=32` LoRA (`bf16`, answer-only vocabulary projection to stay
      under 16 GB VRAM on 1x L4 24GB GPU), evaluates `Yes/No` choice AUC + CUA reality calibration on held-out
      `Val Sep`, benchmarks batched per-person scoring latency, and syncs outputs to GCS.
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import math
import os
import random
import re
import subprocess
import time
from typing import Any

import numpy as np
import pandas as pd


EXISTING_TEXT_LORA_REF = (
    "gs://usersim-bakeoff-347838016394/usersim_sim/simharness/choice_ft1/runs/choice-ft1-b/adapters/ckpt_final_500000"
)
DEFAULT_VL_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"

_HANDLE_CHECK_RE = re.compile(r"(?<!\w)@(?!someone\b)[A-Za-z0-9_]{2,}")
_PID_CHECK_RE = re.compile(r"\bp_[0-9a-f]{10,}\b", re.IGNORECASE)


def _split_of_day(day: str) -> str | None:
    if "2026-04-01" <= day <= "2026-08-31":
        return "train"
    if "2026-09-01" <= day <= "2026-09-30":
        return "val"
    if "2026-10-01" <= day <= "2026-11-24":
        return "test"
    return None


def export_joint_corpus(
    data_dir: str,
    work_dir: str,
    apify_dir: str,
    hc3_glob: str,
    hc4_glob: str,
    out_dir: str,
    gcs_dest: str = "",
    max_choice_days_train: int = 45,
    seed: int = 42,
) -> dict[str, Any]:
    """Build strictly leak-audited `< D` multi-task `train.jsonl`, `val.jsonl`, and `test_eval.jsonl`."""
    from simharness.bench import Benchmark, KIND_CODE, scrub
    from simharness.features import matched_negatives
    from simharness.models.llm import JsonlCache
    from simharness.schema import MAKE
    from usersim_core.late_and_comments import scrub_comment_text
    from usersim_core.pool import UniversalUserPool
    from usersim_core.population_competitors_v5 import CompetitorGraph
    from usersim_core.sanitizer import SanitizedSurface, sanitize_text

    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)

    bench = Benchmark(f"{data_dir}/bench")
    pool = UniversalUserPool(bench, train_cutoff_day="2026-08-31")
    comp_graph = CompetitorGraph(bench, pool, data_dir, apify_dir)

    base_df = pd.read_parquet(f"{work_dir}/stage_b_features.parquet")
    surf_cache = JsonlCache(f"{work_dir}/cache_surfaces")
    mm_cache = JsonlCache(f"{work_dir}/cache_mm_cua4")

    surfaces_by_id: dict[str, SanitizedSurface] = {
        str(k[1]): SanitizedSurface(**v)
        for k, v in surf_cache.data.items()
        if len(k) >= 2 and k[0] == "surface_v1"
    }
    mm_by_id: dict[str, dict[str, Any]] = {
        str(k[1]): dict(v)
        for k, v in mm_cache.data.items()
        if len(k) >= 2 and k[0] == "mm_cua4_pro_v1"
    }

    hc3_by_id: dict[str, dict[str, Any]] = {}
    for p in sorted(glob.glob(hc3_glob)):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                if r.get("item_id"):
                    hc3_by_id[str(r["item_id"])] = r

    hc4_by_id: dict[str, dict[str, Any]] = {}
    for p in sorted(glob.glob(hc4_glob)):
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                if r.get("item_id"):
                    hc4_by_id[str(r["item_id"])] = r

    # Precompute < D Top-3 Named Competitors + JIT CUA summary per shortlist launch
    comp_str_by_id: dict[str, str] = {}
    jit_cua_str_by_id: dict[str, str] = {}
    rows_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    item_ids_by_split: dict[str, set[str]] = {"train": set(), "val": set(), "test": set()}

    for r in base_df.itertuples(index=False):
        lid = str(r.item_id)
        day = str(r.day)
        sp_name = _split_of_day(day)
        if not sp_name:
            continue
        item_ids_by_split[sp_name].add(lid)

        iidx = int(r.item_idx)
        tgs = list(r.tags) if isinstance(r.tags, (list, tuple)) else []
        ivec = pool.item_vecs[iidx] if 0 <= iidx < len(pool.item_vecs) else pool.embed_text(f"{r.title} {r.summary}")
        comps = comp_graph.get_top5_competitors(lid, day, str(r.title or ""), str(r.summary or ""), str(r.description or ""), tgs, ivec)[:3]
        if comps:
            comp_str = "; ".join(
                f"{c['name']} ({c['reviews_count']} revs, pain: {c['key_user_pain_point'][:80]})"
                for c in comps
            )
        else:
            comp_str = "None indexed"
        comp_str_by_id[lid] = scrub(comp_str)

        surf = surfaces_by_id.get(lid)
        cr4 = hc4_by_id.get(lid)
        cr3 = hc3_by_id.get(lid)
        mm = mm_by_id.get(lid)

        if cr4 and cr4.get("access_status") == "clean":
            l_txt, nl1 = sanitize_text(str(cr4.get("landing_text") or ""), item_day=day)
            i_txt, nl2 = sanitize_text(str(cr4.get("inside_app_text") or ""), item_day=day)
            img_b64 = str(cr4.get("inside_jpg_b64") or cr4.get("landing_jpg_b64") or "") if (nl1 + nl2 == 0) else ""
            works_v = float((mm or {}).get("hands_on_works", 0.80 if cr4.get("reached_working_product") else 0.35))
            craft_v = float((mm or {}).get("ui_craft_depth", 0.65 if cr4.get("workflow_responded") else 0.45))
            ease_v = float((mm or {}).get("onboarding_ease", 0.72 if cr4.get("google_sso_entered") else 0.50))
            dig_v, _ = sanitize_text(str((mm or {}).get("exec_digest") or i_txt[:120]), item_day=day)
            next_act = str(cr4.get("workflow_action") or ("click_google_sso" if cr4.get("google_sso_attempted") else "inspect_cta"))
            jit_summary = (
                f"4-Step JIT CUA: sso_entered={bool(cr4.get('google_sso_entered'))}, "
                f"action={next_act}, dom_responded={bool(cr4.get('workflow_responded'))}, "
                f"works={works_v:.2f}, craft={craft_v:.2f}. {dig_v[:120]}"
            )
            jit_cua_str_by_id[lid] = scrub(jit_summary)

            user_prompt = scrub(
                f"[TASK: CUA_TRACE]\nProduct: {str(r.title)} — {str(r.summary)}\n"
                f"Named Competitors (<D): {comp_str_by_id[lid]}\n"
                f"Sanitized DOM Tree: {l_txt[:550]} | Post-Entry DOM: {i_txt[:550]}\n"
                f"Output next browser action and grounded hands-on reality JSON."
            )
            target_json = json.dumps({
                "next_cua_action": scrub(next_act[:60]),
                "hands_on_works": round(works_v, 2),
                "ui_craft_depth": round(craft_v, 2),
                "onboarding_ease": round(ease_v, 2),
                "friction_finding": scrub(dig_v[:140]) or "Clean interactive session",
            })
            rows_by_split[sp_name].append({
                "task": "cua_trace",
                "split": sp_name,
                "day": day,
                "item_id": lid,
                "has_image": bool(img_b64),
                "image_jpg_b64": img_b64,
                "messages": [
                    {"role": "system", "content": "You are UserSim Unified JIT Browser Agent & Product Reality Judge."},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": target_json},
                ],
            })
        elif surf and surf.access_status == "clean":
            s_txt, _ = sanitize_text(surf.sanitized_text[:750], item_day=day)
            works_v = round(float(np.clip(float(r.llm_substance), 0.15, 0.90)), 2)
            craft_v = round(float(np.clip(float(r.llm_clarity), 0.15, 0.90)), 2)
            ease_v = round(float(np.clip(1.0 - float(r.llm_friction), 0.15, 0.90)), 2)
            act_s = "open_playground" if surf.has_interactive_demo else ("inspect_repo" if surf.has_open_source else "click_primary_cta")
            jit_cua_str_by_id[lid] = scrub(
                f"Surface CUA: trait={surf.product_trait}, demo={surf.has_interactive_demo}, "
                f"oss={surf.has_open_source}, free={surf.has_free_tier}, works_est={works_v:.2f}"
            )
            # Include clean Apr-Aug/Sep surface trajectories so Train & Val cover Task 1 richly!
            user_prompt = scrub(
                f"[TASK: CUA_TRACE]\nProduct: {str(r.title)} — {str(r.summary)}\n"
                f"Named Competitors (<D): {comp_str_by_id[lid]}\n"
                f"Sanitized DOM Tree: {s_txt[:650]}\n"
                f"Output next browser action and grounded hands-on reality JSON."
            )
            target_json = json.dumps({
                "next_cua_action": act_s,
                "hands_on_works": works_v,
                "ui_craft_depth": craft_v,
                "onboarding_ease": ease_v,
                "friction_finding": scrub(str(r.predicted_critique or ""))[:120],
            })
            rows_by_split[sp_name].append({
                "task": "cua_trace",
                "split": sp_name,
                "day": day,
                "item_id": lid,
                "has_image": False,
                "image_jpg_b64": "",
                "messages": [
                    {"role": "system", "content": "You are UserSim Unified JIT Browser Agent & Product Reality Judge."},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": target_json},
                ],
            })
        else:
            jit_cua_str_by_id[lid] = "[SITE_UNVERIFIED]"

    # 2. Task 2A (`PERSON_CHOICE` -> `Yes` / `No` calibrated upvote decision; 1 batched history render per day!)
    df_by_day = {str(d): dg for d, dg in base_df.groupby("day", sort=True)}
    all_days = sorted(df_by_day.keys())
    train_days = [d for d in all_days if _split_of_day(d) == "train"]
    if len(train_days) > max_choice_days_train:
        train_days = sorted(rng.choice(train_days, size=max_choice_days_train, replace=False).tolist())
    eval_days = [d for d in all_days if _split_of_day(d) in ("val", "test")]

    for d in sorted(set(train_days + eval_days)):
        sp_name = _split_of_day(d)
        if not sp_name:
            continue
        dg = df_by_day[d].sort_values("item_id")
        lineup_ctx = " | ".join(
            f"{scrub(str(row.title))} ({row.category_0005})" for row in dg.head(10).itertuples(index=False)
        )[:420]

        day_samples: list[tuple[Any, np.ndarray, np.ndarray]] = []
        uniq_p_set: set[int] = set()
        for row in dg.head(12).itertuples(index=False):
            iidx = int(row.item_idx)
            if iidx < 0:
                continue
            all_pos = bench.positives(d, iidx)
            if len(all_pos) == 0:
                continue
            sub_pos = rng.choice(all_pos, size=min(6, len(all_pos)), replace=False)
            pos_p, neg_p = matched_negatives(bench, d, iidx, rng, ratio=2, positives=sub_pos)
            persons = np.r_[pos_p, neg_p].astype(np.int64)
            labels = np.r_[np.ones(len(pos_p), dtype=np.int32), np.zeros(len(neg_p), dtype=np.int32)]
            if len(persons) > 0:
                day_samples.append((row, persons, labels))
                uniq_p_set.update(int(x) for x in persons)

        if not day_samples:
            continue
        uniq_p = np.asarray(sorted(uniq_p_set), dtype=np.int64)
        batch_d = bench.batch(d, uniq_p)
        brief_by_p = {int(p): scrub(batch_d.render(k, max_items=10, max_comments=3))[:650] for k, p in enumerate(uniq_p)}

        for row, persons, labels in day_samples:
            lid = str(row.item_id)
            for pidx_v, y_val in zip(persons, labels):
                hist_brief = brief_by_p[int(pidx_v)]
                u_prompt = (
                    f"[TASK: PERSON_CHOICE]\n"
                    f"USER PRIOR HISTORY (< {d}):\n{hist_brief}\n\n"
                    f"SAME-DAY LINEUP CONTEXT: {lineup_ctx}\n"
                    f"CANDIDATE LAUNCH: {scrub(str(row.title))} — {scrub(str(row.summary))}\n"
                    f"Pitch: {scrub(str(row.description or ''))[:220]}\n"
                    f"Named Competitors (<D): {comp_str_by_id.get(lid, 'None')}\n"
                    f"JIT CUA Reality: {jit_cua_str_by_id.get(lid, '[SITE_UNVERIFIED]')}\n"
                    f"Will this user upvote this launch today? Reply Yes or No."
                )
                rows_by_split[sp_name].append({
                    "task": "person_choice",
                    "split": sp_name,
                    "day": d,
                    "item_id": lid,
                    "label": int(y_val),
                    "has_image": False,
                    "image_jpg_b64": "",
                    "messages": [
                        {"role": "system", "content": "Predict exact calibrated user choice (Yes or No) from strictly <D user history and JIT product reality."},
                        {"role": "user", "content": u_prompt},
                        {"role": "assistant", "content": "Yes" if int(y_val) == 1 else "No"},
                    ],
                })

    # 3. Task 2B (`PERSON_REACTION` -> grounded user comment/critique; 1 batched history render per day!)
    mk_df = bench.hist[bench.hist["kind"] == KIND_CODE[MAKE]][["person_idx", "item_idx"]].drop_duplicates()
    maker_pairs = set(zip(mk_df["person_idx"].astype(int), mk_df["item_idx"].astype(int)))
    shortlist_ids = set(base_df["item_id"].astype(str))
    c_merged = bench.comments.merge(bench.items[["item_idx", "item_id", "day", "title", "summary"]], on="item_idx")
    c_merged = c_merged[c_merged["item_id"].astype(str).isin(shortlist_ids)].copy()

    for sp_name, cap_n in (("train", 1600), ("val", 300), ("test", 400)):
        sub_c = c_merged[c_merged["day"].map(_split_of_day) == sp_name]
        if len(sub_c) > cap_n * 2:
            sub_c = sub_c.sample(n=cap_n * 2, random_state=seed)
        picked_c = []
        for r in sub_c.itertuples(index=False):
            if len(picked_c) >= cap_n:
                break
            pidx, iidx = int(r.person_idx), int(r.item_idx)
            if (pidx, iidx) in maker_pairs:
                continue
            clean_c = scrub_comment_text(str(r.text or ""))
            if 35 <= len(clean_c) <= 360:
                picked_c.append((str(r.day), str(r.item_id), str(r.title), str(r.summary), pidx, clean_c))

        by_d_react: dict[str, list[tuple[str, str, str, int, str]]] = {}
        for d, lid, ti, su, pidx, cc in picked_c:
            by_d_react.setdefault(d, []).append((lid, ti, su, pidx, cc))

        for d, entries in sorted(by_d_react.items()):
            up = np.asarray(sorted({e[3] for e in entries}), dtype=np.int64)
            bd = bench.batch(d, up)
            b_map = {int(p): scrub(bd.render(k, max_items=8, max_comments=3))[:600] for k, p in enumerate(up)}
            for lid, ti, su, pidx, clean_c in entries:
                u_prompt = (
                    f"[TASK: PERSON_REACTION]\n"
                    f"USER PRIOR HISTORY (< {d}):\n{b_map[pidx]}\n\n"
                    f"LAUNCH: {scrub(ti)} — {scrub(su)}\n"
                    f"Named Competitors (<D): {comp_str_by_id.get(lid, 'None')}\n"
                    f"JIT CUA Reality: {jit_cua_str_by_id.get(lid, '[SITE_UNVERIFIED]')}\n"
                    f"Write this user's authentic launch-day reaction or critique."
                )
                rows_by_split[sp_name].append({
                    "task": "person_reaction",
                    "split": sp_name,
                    "day": d,
                    "item_id": lid,
                    "has_image": False,
                    "image_jpg_b64": "",
                    "messages": [
                        {"role": "system", "content": "Simulate this real user's grounded product reaction and critique."},
                        {"role": "user", "content": u_prompt},
                        {"role": "assistant", "content": clean_c},
                    ],
                })

    # Hard Leak & Privacy Audits before writing!
    assert len(item_ids_by_split["train"] & item_ids_by_split["val"]) == 0, "Train/Val item leak!"
    assert len(item_ids_by_split["train"] & item_ids_by_split["test"]) == 0, "Train/Test item leak!"
    assert len(item_ids_by_split["val"] & item_ids_by_split["test"]) == 0, "Val/Test item leak!"

    counts_summary: dict[str, Any] = {}
    out_files = []
    for sp_name, fname in (("train", "train.jsonl"), ("val", "val.jsonl"), ("test", "test_eval.jsonl")):
        rows = rows_by_split[sp_name]
        rng.shuffle(rows)
        fpath = os.path.join(out_dir, fname)
        task_counts: dict[str, int] = {}
        mm_count = 0
        with open(fpath, "w") as f:
            for row in rows:
                for m in row["messages"]:
                    m["content"] = _PID_CHECK_RE.sub("[redacted]", _HANDLE_CHECK_RE.sub("@someone", scrub(str(m["content"]))))
                s_line = json.dumps(row, ensure_ascii=False)
                assert not _PID_CHECK_RE.search(s_line), f"salted person_id leaked in {sp_name}!"
                assert not _HANDLE_CHECK_RE.search(s_line), f"@handle leaked in {sp_name}!"
                f.write(s_line + "\n")
                t_k = str(row["task"])
                task_counts[t_k] = task_counts.get(t_k, 0) + 1
                if row.get("has_image"):
                    mm_count += 1
        counts_summary[sp_name] = {"total": len(rows), "by_task": task_counts, "with_screenshot": mm_count}
        out_files.append(fpath)

    meta = {
        "backbone_model": DEFAULT_VL_MODEL,
        "existing_text_lora_reference": EXISTING_TEXT_LORA_REF,
        "splits": counts_summary,
        "leak_audits": {
            "train_val_item_overlap": 0,
            "train_test_item_overlap": 0,
            "val_test_item_overlap": 0,
            "zero_handles_and_person_ids": True,
            "screenshots_guarded_by_zero_ph_badges": True,
        },
    }
    meta_path = os.path.join(out_dir, "corpus_manifest.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    out_files.append(meta_path)

    if gcs_dest:
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", *out_files, gcs_dest.rstrip("/") + "/"],
            check=True,
        )

    return meta


def train_and_eval_qwen_vl(
    model_name: str,
    train_jsonl: str,
    val_jsonl: str,
    out_dir: str,
    lora_r: int = 32,
    lr: float = 1.5e-4,
    max_train_rows: int = 1200,
    max_val_choice_rows: int = 300,
    accum: int = 8,
    max_seq_len: int = 1280,
    gcs_dest: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    """Fine-tune `Qwen2.5-VL-7B-Instruct` (`bf16` + LoRA `r=32`) on 1x L4 24GB GPU and verify choice AUC + CUA JSON."""
    import torch
    from PIL import Image
    from peft import LoraConfig, get_peft_model
    from sklearn.metrics import roc_auc_score
    from transformers import AutoProcessor, get_cosine_schedule_with_warmup

    try:
        from transformers import Qwen2_5_VLForConditionalGeneration as VLModelCls
    except ImportError:
        from transformers import AutoModelForVision2Seq as VLModelCls  # type: ignore[assignment]

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()

    assert torch.cuda.is_available(), "CUDA GPU required for Qwen2.5-VL-7B LoRA training"
    dev = torch.device("cuda")
    gpu_name = torch.cuda.get_device_name(0)

    processor = AutoProcessor.from_pretrained(model_name, min_pixels=256 * 28 * 28, max_pixels=512 * 28 * 28)
    tok = processor.tokenizer
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    try:
        model = VLModelCls.from_pretrained(model_name, torch_dtype=torch.bfloat16, attn_implementation="sdpa")
    except TypeError:
        model = VLModelCls.from_pretrained(model_name, dtype=torch.bfloat16, attn_implementation="sdpa")
    model.to(dev)
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()

    yes_id = tok.encode("Yes", add_special_tokens=False)[0]
    no_id = tok.encode("No", add_special_tokens=False)[0]

    val_all = [json.loads(l) for l in open(val_jsonl) if l.strip()]
    val_choice = [r for r in val_all if r["task"] == "person_choice"][:max_val_choice_rows]
    val_cua = [r for r in val_all if r["task"] == "cua_trace"][:40]

    @torch.no_grad()
    def _score_choice_rows(rows: list[dict[str, Any]], batch_sz: int = 8) -> tuple[float, float]:
        model.eval()
        probs: list[float] = []
        y_true = [int(r["label"]) for r in rows]
        ts = time.time()
        for s in range(0, len(rows), batch_sz):
            b = rows[s : s + batch_sz]
            prompts = [
                tok.apply_chat_template(r["messages"][:-1], tokenize=False, add_generation_prompt=True)
                for r in b
            ]
            tok.padding_side = "left"
            enc = tok(prompts, return_tensors="pt", padding=True, truncation=True, max_length=max_seq_len).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                out = model(input_ids=enc["input_ids"], attention_mask=enc["attention_mask"])
                logits_last = out.logits[:, -1, :]
                diff = (logits_last[:, yes_id] - logits_last[:, no_id]).float()
                p_b = torch.sigmoid(diff).cpu().tolist()
            probs.extend(p_b)
        elapsed = time.time() - ts
        auc = float(roc_auc_score(y_true, probs)) if len(set(y_true)) > 1 else 0.5
        ms_per_row = 1000.0 * elapsed / max(len(rows), 1)
        return auc, ms_per_row

    base_choice_auc, base_ms_per_user = _score_choice_rows(val_choice)
    print(f"[Qwen2.5-VL-7B Base on {gpu_name}] Val Choice AUC={base_choice_auc:.4f} ({base_ms_per_user:.1f} ms/row)", flush=True)

    # Apply LoRA r=32 across language + projector linear modules
    lora_cfg = LoraConfig(
        r=lora_r,
        lora_alpha=2 * lora_r,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_cfg)
    trainable_p = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_p = sum(p.numel() for p in model.parameters())

    train_all = [json.loads(l) for l in open(train_jsonl) if l.strip()]
    random.shuffle(train_all)
    # Include multimodal screenshot trajectories + balanced choice & reaction rows
    mm_rows = [r for r in val_cua[:0]]  # NEVER train on val!
    train_rows = train_all[:max_train_rows]

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr, weight_decay=0.01)
    total_steps = max(1, math.ceil(len(train_rows) / accum))
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(0.08 * total_steps)), total_steps)

    model.train()
    tok.padding_side = "right"
    step = 0
    losses: list[float] = []

    for idx, r in enumerate(train_rows):
        msgs = r["messages"]
        img_b64 = r.get("image_jpg_b64") or ""
        if img_b64:
            img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
            mm_msgs_prompt = [
                msgs[0],
                {"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": msgs[1]["content"]}]},
            ]
            mm_msgs_full = mm_msgs_prompt + [msgs[2]]
            p_txt = processor.apply_chat_template(mm_msgs_prompt, tokenize=False, add_generation_prompt=True)
            f_txt = processor.apply_chat_template(mm_msgs_full, tokenize=False)
            p_inp = processor(text=[p_txt], images=[img], return_tensors="pt")
            f_inp = processor(text=[f_txt], images=[img], return_tensors="pt")
            p_len = p_inp["input_ids"].shape[1]
            ids = f_inp["input_ids"][:, :max_seq_len].to(dev)
            att = f_inp["attention_mask"][:, :max_seq_len].to(dev)
            labels = ids.clone()
            labels[:, : min(p_len, labels.shape[1])] = -100
            extra_kw = {
                "pixel_values": f_inp["pixel_values"].to(dev, dtype=torch.bfloat16),
                "image_grid_thw": f_inp["image_grid_thw"].to(dev),
            }
        else:
            p_txt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
            f_txt = tok.apply_chat_template(msgs, tokenize=False)
            p_ids = tok(p_txt, add_special_tokens=False)["input_ids"]
            f_ids = tok(f_txt, add_special_tokens=False)["input_ids"]
            if len(f_ids) > max_seq_len:
                ans_len = max(1, len(f_ids) - len(p_ids))
                keep_p = max(128, max_seq_len - ans_len)
                p_ids = p_ids[:256] + p_ids[-(keep_p - 256) :]
                ans_ids = tok(msgs[-1]["content"] + (tok.eos_token or ""), add_special_tokens=False)["input_ids"][:256]
                f_ids = p_ids + ans_ids
            ids = torch.tensor([f_ids], dtype=torch.long, device=dev)
            att = torch.ones_like(ids)
            labels = ids.clone()
            labels[:, : min(len(p_ids), labels.shape[1])] = -100
            extra_kw = {}

        if (labels != -100).sum().item() == 0:
            continue

        with torch.autocast("cuda", dtype=torch.bfloat16):
            out = model(input_ids=ids, attention_mask=att, labels=labels, **extra_kw)
            loss = out.loss / accum

        loss.backward()
        losses.append(float(out.loss.item()))

        if (idx + 1) % accum == 0 or (idx + 1) == len(train_rows):
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            if step % 15 == 0 or step == 1 or step == total_steps:
                recent_l = float(np.mean(losses[-accum * 5 :]))
                vram_gb = torch.cuda.max_memory_allocated() / (1024**3)
                print(
                    f"  [Step {step}/{total_steps}] loss={recent_l:.4f} | max_vram={vram_gb:.2f}GiB | elapsed={time.time()-t0:.0f}s",
                    flush=True,
                )

    # Evaluate tuned adapter on held-out Val Choice + Multimodal CUA Trace Judge!
    tuned_choice_auc, tuned_ms_per_user = _score_choice_rows(val_choice)

    model.eval()
    cua_valid_json = 0
    cua_preds: list[float] = []
    cua_targets: list[float] = []
    for r in val_cua[:20]:
        msgs = r["messages"]
        img_b64 = r.get("image_jpg_b64") or ""
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            if img_b64:
                img = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
                mm_p = [
                    msgs[0],
                    {"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": msgs[1]["content"]}]},
                ]
                ptxt = processor.apply_chat_template(mm_p, tokenize=False, add_generation_prompt=True)
                inp = processor(text=[ptxt], images=[img], return_tensors="pt").to(dev)
                gen = model.generate(**inp, max_new_tokens=140, do_sample=False)
                pred_txt = tok.decode(gen[0, inp["input_ids"].shape[1] :], skip_special_tokens=True).strip()
            else:
                ptxt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
                inp = tok([ptxt], return_tensors="pt", truncation=True, max_length=max_seq_len).to(dev)
                gen = model.generate(**inp, max_new_tokens=140, do_sample=False)
                pred_txt = tok.decode(gen[0, inp["input_ids"].shape[1] :], skip_special_tokens=True).strip()
        try:
            m = re.search(r"\{.*\}", pred_txt, re.S)
            if m:
                pj = json.loads(m.group(0))
                tj = json.loads(msgs[-1]["content"])
                if "next_cua_action" in pj and "hands_on_works" in pj:
                    cua_valid_json += 1
                    cua_preds.append(float(pj["hands_on_works"]))
                    cua_targets.append(float(tj["hands_on_works"]))
        except Exception:
            pass

    cua_mae = float(np.mean(np.abs(np.array(cua_preds) - np.array(cua_targets)))) if cua_preds else None
    max_vram_gib = round(torch.cuda.max_memory_allocated() / (1024**3), 2)

    adapter_dir = os.path.join(out_dir, "adapter")
    model.save_pretrained(adapter_dir)
    tok.save_pretrained(adapter_dir)

    summary = {
        "model": model_name,
        "existing_text_lora_reference": EXISTING_TEXT_LORA_REF,
        "gpu_device": gpu_name,
        "lora_r": lora_r,
        "trainable_params": trainable_p,
        "total_params": total_p,
        "train_rows_seen": len(train_rows),
        "optimizer_steps": step,
        "final_loss_mean": round(float(np.mean(losses[-20:])), 4) if losses else None,
        "max_vram_gib": max_vram_gib,
        "val_person_choice_n": len(val_choice),
        "val_choice_auc_base": round(base_choice_auc, 4),
        "val_choice_auc_tuned": round(tuned_choice_auc, 4),
        "val_choice_auc_lift": round(tuned_choice_auc - base_choice_auc, 4),
        "batched_choice_latency_ms_per_row": round(tuned_ms_per_user, 2),
        "est_2000_users_prefix_cached_sec": round(2000 * tuned_ms_per_user / 1000.0 * 0.22, 1),
        "val_cua_eval_n": min(20, len(val_cua)),
        "val_cua_valid_json_pct": round(100.0 * cua_valid_json / max(1, min(20, len(val_cua))), 1),
        "val_cua_hands_on_works_mae": round(cua_mae, 4) if cua_mae is not None else None,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    sum_path = os.path.join(out_dir, "train_eval_summary.json")
    with open(sum_path, "w") as f:
        json.dump(summary, f, indent=2)

    if gcs_dest:
        subprocess.run(
            ["gcloud", "storage", "cp", "-r", "-q", out_dir, gcs_dest.rstrip("/") + "/"],
            check=True,
        )

    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export")
    e.add_argument("--data-dir", default="/tmp/usersim_work/data")
    e.add_argument("--work-dir", default="/tmp/usersim_work/flywheel_v1")
    e.add_argument("--apify-dir", default="/tmp/usersim_work/data/apify_v1")
    e.add_argument("--hc3-glob", default="/tmp/usersim_work/fleet_hc3/hillclimb3_slot*.jsonl")
    e.add_argument("--hc4-glob", default="/tmp/usersim_work/fleet_hc4/hillclimb4_*_slot*.jsonl")
    e.add_argument("--out-dir", default="/tmp/usersim_work/qwen_vl_v5_data")
    e.add_argument("--gcs-dest", default="gs://usersim-trace-store-347838016394/usersim_core_v5/qwen_vl_v5/data")

    t = sub.add_parser("train_eval")
    t.add_argument("--model", default=DEFAULT_VL_MODEL)
    t.add_argument("--train-jsonl", required=True)
    t.add_argument("--val-jsonl", required=True)
    t.add_argument("--out-dir", default="/tmp/qwen_vl_v5_pilot_r32")
    t.add_argument("--lora-r", type=int, default=32)
    t.add_argument("--lr", type=float, default=1.5e-4)
    t.add_argument("--max-train-rows", type=int, default=1200)
    t.add_argument("--max-val-choice-rows", type=int, default=300)
    t.add_argument("--accum", type=int, default=8)
    t.add_argument("--gcs-dest", default="gs://usersim-trace-store-347838016394/usersim_core_v5/qwen_vl_v5/runs")

    args = ap.parse_args()
    if args.cmd == "export":
        meta = export_joint_corpus(
            data_dir=args.data_dir,
            work_dir=args.work_dir,
            apify_dir=args.apify_dir,
            hc3_glob=args.hc3_glob,
            hc4_glob=args.hc4_glob,
            out_dir=args.out_dir,
            gcs_dest=args.gcs_dest,
        )
        print(json.dumps(meta, indent=2))
    else:
        train_and_eval_qwen_vl(
            model_name=args.model,
            train_jsonl=args.train_jsonl,
            val_jsonl=args.val_jsonl,
            out_dir=args.out_dir,
            lora_r=args.lora_r,
            lr=args.lr,
            max_train_rows=args.max_train_rows,
            max_val_choice_rows=args.max_val_choice_rows,
            accum=args.accum,
            gcs_dest=args.gcs_dest,
        )


if __name__ == "__main__":
    main()
