#!/usr/bin/env python3
"""Reproduce Minitaur NLL on Psych-101-test (held-out participants).

Engine: vLLM continuous batching + LoRA (default). Teacher-forced NLL via
prompt_logprobs, with the same <<...>> span mask as the Unsloth runner.

Full run: all 6561 rows. SMOKE_N>0 requires ALLOW_PARTIAL=1 and writes
PARTIAL.*.json, never SUMMARY.json.

Resume: results/minitaur/scores.jsonl (row_idx → nll).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path("/content/fm_baselines")
DATA = ROOT / "data" / "Psych-101-test" / "prompts_testing_t1.jsonl"
RESULTS = ROOT / "results" / "minitaur"
SCORES = RESULTS / "scores.jsonl"
ADAPTER = os.environ.get(
    "MINITAUR_ADAPTER", "marcelbinz/Llama-3.1-Minitaur-8B-adapter"
)
# Adapter card base is unsloth/Meta-Llama-3.1-8B-bnb-4bit. Use the ungated
# Unsloth fp16 twin + vLLM bitsandbytes (meta-llama/* is gated / 403 here).
BASE = os.environ.get("MINITAUR_BASE", "unsloth/Meta-Llama-3.1-8B")
MAX_SEQ = int(os.environ.get("MAX_SEQ", "4096"))
EXPECTED_ITEMS = 6561
CHUNK = int(os.environ.get("CHUNK", "256"))
MAX_NUM_SEQS = int(os.environ.get("MAX_NUM_SEQS", "32"))
GPU_MEM_UTIL = float(os.environ.get("GPU_MEM_UTIL", "0.90"))
# Length-bucket schedule: (max_tokens_inclusive, generate_chunk). Short-first so
# vLLM continuous batching packs many short prompts; long buckets stay small.
def _parse_schedule(raw: str | None) -> list[tuple[int, int]]:
    if not raw or not raw.strip():
        return [
            (512, 256),
            (1024, 128),
            (2048, 64),
            (3072, 32),
            (4096, 16),
        ]
    out: list[tuple[int, int]] = []
    for part in raw.split(","):
        a, b = part.strip().split(":")
        out.append((int(a), int(b)))
    return out


BATCH_SCHEDULE = _parse_schedule(os.environ.get("BATCH_SCHEDULE"))


_REPO = Path(__file__).resolve().parents[2]
if (_REPO / "scripts" / "fm_baselines").is_dir():
    sys.path.insert(0, str(_REPO / "scripts" / "fm_baselines"))
if (ROOT / "scripts").is_dir():
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    from gate_contract import (  # type: ignore
        coverage_block,
        require_full_or_allow,
        write_summary_or_partial,
    )
except ImportError:

    def require_full_or_allow(kind: str, detail: str) -> None:
        if os.environ.get("ALLOW_PARTIAL", "").strip() in {"1", "true", "TRUE", "yes"}:
            print(f"ALLOW_PARTIAL=1 — PARTIAL {kind}: {detail}", flush=True)
            return
        raise SystemExit(
            f"Refusing subset ({kind}: {detail}). Set ALLOW_PARTIAL=1 or run the full test set."
        )

    def coverage_block(**kwargs):
        failed = list(kwargs.get("failed") or [])
        return {
            "actual": kwargs["actual"],
            "expected": kwargs["expected"],
            "unit": kwargs.get("unit", "items"),
            "complete": bool(kwargs.get("complete")) and not failed,
            "failed": failed,
        }

    def write_summary_or_partial(results_dir, summary, *, complete, reason=None):
        results_dir.mkdir(parents=True, exist_ok=True)
        if not complete:
            safe = (reason or "incomplete").replace(" ", "_")[:64]
            path = results_dir / f"PARTIAL.{safe}.json"
            summary = dict(summary)
            summary["complete"] = False
            path.write_text(json.dumps(summary, indent=2))
            print(f"WROTE_PARTIAL {path}", flush=True)
            return path
        path = results_dir / "SUMMARY.json"
        summary = dict(summary)
        summary["complete"] = True
        path.write_text(json.dumps(summary, indent=2))
        print(f"WROTE_SUMMARY {path}", flush=True)
        return path


def sh(cmd: str) -> None:
    print("+", cmd, flush=True)
    subprocess.run(cmd, shell=True, check=True)


def install() -> None:
    if os.environ.get("SKIP_INSTALL", "").strip() in {"1", "true", "TRUE", "yes"}:
        print("SKIP_INSTALL=1", flush=True)
        return
    sh(f"{sys.executable} -m pip install -q -U pip")
    sh(
        f"{sys.executable} -m pip install -q -U "
        "'vllm==0.27.1' transformers accelerate bitsandbytes peft "
        "sentencepiece protobuf pyyaml huggingface_hub"
    )


def find_subseq(hay: list[int], needle: list[int]) -> list[int]:
    hits = []
    n = len(needle)
    if n == 0:
        return hits
    for i in range(len(hay) - n + 1):
        if hay[i : i + n] == needle:
            hits.append(i)
    return hits


def span_positions(token_ids: list[int], l_id: list[int], r_id: list[int]) -> list[int]:
    """Token indices inside <<...>> (exclusive of the bracket tokens), matching
    the Unsloth runner's shift-mask (scores input_ids[start:end])."""
    lefts = find_subseq(token_ids, l_id)
    rights = find_subseq(token_ids, r_id)
    out: list[int] = []
    ri = 0
    for li in lefts:
        start = li + len(l_id)
        while ri < len(rights) and rights[ri] < start:
            ri += 1
        if ri >= len(rights):
            break
        end = rights[ri]
        out.extend(range(start, end))
        ri += 1
    return out


def logprob_of_token(entry, tid: int) -> float | None:
    """Pull logprob for tid from a vLLM prompt_logprobs entry."""
    if entry is None:
        return None
    # entry: Dict[int, Logprob] | list-like
    if isinstance(entry, dict):
        if tid in entry:
            lp = entry[tid]
            return float(lp.logprob if hasattr(lp, "logprob") else lp)
        # fallback: single returned logprob
        if len(entry) == 1:
            lp = next(iter(entry.values()))
            return float(lp.logprob if hasattr(lp, "logprob") else lp)
        return None
    return None


def nll_from_prompt_logprobs(
    token_ids: list[int],
    prompt_logprobs,
    l_id: list[int],
    r_id: list[int],
) -> float | None:
    if prompt_logprobs is None:
        return None
    positions = span_positions(token_ids, l_id, r_id)
    if not positions:
        return None
    total = 0.0
    n = 0
    for pos in positions:
        if pos <= 0 or pos >= len(prompt_logprobs):
            continue
        lp = logprob_of_token(prompt_logprobs[pos], token_ids[pos])
        if lp is None:
            continue
        total += -lp
        n += 1
    if n == 0:
        return None
    return float(total)


def load_done() -> dict[int, float | None]:
    done: dict[int, float | None] = {}
    if not SCORES.exists():
        return done
    for line in SCORES.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        # Ignore pre-vLLM rows so we do not mix engines.
        if rec.get("engine") not in {None, "vllm"} and rec.get("engine") != "vllm":
            continue
        if rec.get("engine") != "vllm":
            # legacy unsloth/transformers rows — skip for Gate 0 vLLM run
            continue
        done[int(rec["row_idx"])] = rec.get("nll")
    return done


def archive_legacy_scores() -> None:
    if not SCORES.exists():
        return
    raw = SCORES.read_text()
    if not raw.strip():
        return
    # If file has any non-vllm rows (or no engine field), archive and start clean.
    has_legacy = False
    has_vllm = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("engine") == "vllm":
            has_vllm = True
        else:
            has_legacy = True
    if has_legacy:
        bak = RESULTS / f"scores.legacy_unsloth.{int(time.time())}.jsonl"
        bak.write_text(raw)
        print(f"archived legacy scores → {bak}", flush=True)
        if has_vllm:
            # keep only vllm lines
            keep = [
                l
                for l in raw.splitlines()
                if l.strip() and json.loads(l).get("engine") == "vllm"
            ]
            SCORES.write_text("\n".join(keep) + ("\n" if keep else ""))
        else:
            SCORES.unlink()


def main() -> None:
    smoke_n = int(os.environ.get("SMOKE_N", "0"))
    if smoke_n > 0:
        require_full_or_allow("SMOKE_N", f"first {smoke_n} rows")

    assert DATA.exists(), f"missing {DATA}"
    install()
    RESULTS.mkdir(parents=True, exist_ok=True)
    archive_legacy_scores()

    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    print(f"Loading vLLM base={BASE} adapter={ADAPTER}", flush=True)
    # vLLM>=0.28 moved bitsandbytes OOT; 0.27.1 keeps it in-tree (pin in install()).
    try:
        import vllm_bnb_plugin  # noqa: F401
    except ImportError:
        pass

    tok = AutoTokenizer.from_pretrained(ADAPTER, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    llm = LLM(
        model=BASE,
        quantization=os.environ.get("QUANT", "bitsandbytes"),
        dtype="half",
        enable_lora=True,
        max_lora_rank=16,
        # +1 so a MAX_SEQ-token prompt still fits with max_tokens=1 for logprobs.
        max_model_len=MAX_SEQ + 1,
        gpu_memory_utilization=GPU_MEM_UTIL,
        max_num_seqs=MAX_NUM_SEQS,
        max_logprobs=5,
        trust_remote_code=True,
        # T4 + py3.10: flashinfer compile path crashes on array.array[int].
        enforce_eager=True,
    )
    lora = LoRARequest("minitaur", 1, ADAPTER)
    sp = SamplingParams(
        max_tokens=1,
        temperature=0.0,
        prompt_logprobs=1,
        detokenize=False,
    )

    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    print(f"loaded {len(rows)} test rows", flush=True)
    use_rows = rows[:smoke_n] if smoke_n > 0 else rows

    l_id = tok(" <<").input_ids[1:]
    r_id = tok(">>").input_ids[1:]

    done = load_done()
    print(f"resuming: {len(done)}/{len(use_rows)} already scored (vllm)", flush=True)
    pending = [i for i in range(len(use_rows)) if i not in done]

    # Pre-tokenize pending → length buckets (short first).
    print(f"tokenizing {len(pending)} pending rows for length buckets…", flush=True)
    work: list[tuple[int, list[int]]] = []  # (row_idx, token_ids)
    no_span: list[int] = []
    for j in pending:
        text = use_rows[j]["text"]
        if "<<" not in text or ">>" not in text:
            no_span.append(j)
            continue
        ids = tok(
            text,
            truncation=True,
            max_length=MAX_SEQ,
            add_special_tokens=True,
        ).input_ids
        work.append((j, ids))

    work.sort(key=lambda x: len(x[1]))
    buckets: list[tuple[int, int, list[tuple[int, list[int]]]]] = []
    for max_len, chunk_sz in BATCH_SCHEDULE:
        bucket = [(j, ids) for j, ids in work if len(ids) <= max_len]
        # remove claimed
        claimed = {j for j, _ in bucket}
        work = [(j, ids) for j, ids in work if j not in claimed]
        if bucket:
            buckets.append((max_len, chunk_sz, bucket))
    if work:
        # anything beyond last schedule ceiling (shouldn't happen with 4096)
        buckets.append((MAX_SEQ, 8, work))

    print(
        "buckets: "
        + ", ".join(f"<={mx}:{len(b)}@{cz}" for mx, cz, b in buckets)
        + f"  no_span={len(no_span)}  max_num_seqs={MAX_NUM_SEQS}",
        flush=True,
    )

    experiments = sorted({r["experiment"].split("/")[0] for r in use_rows})
    t0 = time.time()
    scored_since = 0

    def flush_progress() -> None:
        (RESULTS / "PROGRESS.json").write_text(
            json.dumps(
                {
                    "scored": len(done),
                    "total": len(use_rows),
                    "max_seq": MAX_SEQ,
                    "engine": "vllm",
                    "max_num_seqs": MAX_NUM_SEQS,
                    "batch_schedule": [[mx, cz] for mx, cz, _ in buckets],
                    "bucket_counts": {f"<={mx}": len(b) for mx, _, b in buckets},
                }
            )
        )

    try:
        from vllm.inputs import TokensPrompt
    except Exception:
        TokensPrompt = None  # type: ignore

    with SCORES.open("a") as fout:
        for j in no_span:
            rec = {
                "row_idx": j,
                "experiment": use_rows[j]["experiment"].split("/")[0],
                "nll": None,
                "engine": "vllm",
            }
            fout.write(json.dumps(rec) + "\n")
            done[j] = None
        if no_span:
            fout.flush()

        for max_len, chunk_sz, bucket in buckets:
            print(
                f"bucket <= {max_len}: {len(bucket)} items, chunk={chunk_sz}",
                flush=True,
            )
            for start in range(0, len(bucket), chunk_sz):
                batch = bucket[start : start + chunk_sz]
                if TokensPrompt is not None:
                    reqs = [TokensPrompt(prompt_token_ids=ids) for _, ids in batch]
                else:
                    reqs = [{"prompt_token_ids": ids} for _, ids in batch]

                outs = llm.generate(reqs, sp, lora_request=lora)

                for (j, ids), out in zip(batch, outs):
                    nll = nll_from_prompt_logprobs(
                        list(ids), out.prompt_logprobs, l_id, r_id
                    )
                    rec = {
                        "row_idx": j,
                        "experiment": use_rows[j]["experiment"].split("/")[0],
                        "nll": nll,
                        "n_tok": len(ids),
                        "engine": "vllm",
                        "bucket_max": max_len,
                    }
                    fout.write(json.dumps(rec) + "\n")
                    done[j] = nll

                fout.flush()
                scored_since += len(batch)
                elapsed = max(time.time() - t0, 1e-6)
                if scored_since >= 32 or start + chunk_sz >= len(bucket):
                    print(
                        f"scored {len(done)}/{len(use_rows)}  "
                        f"bucket<={max_len}  "
                        f"~{scored_since / elapsed * 3600:.0f}/hr  engine=vllm",
                        flush=True,
                    )
                    flush_progress()
                    scored_since = 0
                    t0 = time.time()

    # Aggregate
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    skipped = 0
    for line in SCORES.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("engine") != "vllm":
            continue
        if rec.get("nll") is None:
            skipped += 1
            continue
        exp = rec["experiment"]
        sums[exp] += float(rec["nll"])
        counts[exp] += 1

    out = {}
    for exp in experiments:
        if counts[exp]:
            out[exp] = {
                "nll_sum": sums[exp],
                "n_items": counts[exp],
                "nll_mean": sums[exp] / counts[exp],
            }
    (RESULTS / "minitaur_psych101_nll.json").write_text(json.dumps(out, indent=2))
    total_nll = sum(sums.values())
    total_n = sum(counts.values())
    is_partial = smoke_n > 0 or total_n < EXPECTED_ITEMS
    cov = coverage_block(
        actual=total_n,
        expected=EXPECTED_ITEMS,
        unit="items",
        complete=not is_partial and total_n >= EXPECTED_ITEMS,
        failed=[],
        extra={"skipped_no_span": skipped, "engine": "vllm"},
    )
    summary = {
        "model": ADAPTER,
        "base": BASE,
        "total_nll_sum": total_nll,
        "n_items": total_n,
        "n_experiments": len(out),
        "max_seq": MAX_SEQ,
        "coverage": cov,
        "smoke_n": smoke_n,
        "skipped_no_span": skipped,
        "engine": "vllm",
        "max_num_seqs": MAX_NUM_SEQS,
    }
    reason = None
    if is_partial:
        reason = f"smoke_{smoke_n}" if smoke_n > 0 else f"n_items_{total_n}_of_{EXPECTED_ITEMS}"
    write_summary_or_partial(RESULTS, summary, complete=bool(cov["complete"]), reason=reason)
    flush_progress()
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
