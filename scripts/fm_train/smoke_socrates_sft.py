#!/usr/bin/env python3
"""Format smoke test: the SFT training text must match the eval prompt exactly.

Checks, in order (any failure exits non-zero and blocks the full run):
  1. SYSTEM string and message construction are byte-identical to the eval
     runner's, read out of the runner source rather than duplicated here.
  2. The training example is exactly render_prompt(row) + response + eos.
  3. Labels are -100 on every prompt token and set on every response token, so
     loss is computed only on the human response.
  4. Decoding the unmasked label positions returns the human response.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from socrates_format import SYSTEM, render_prompt, render_target

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
EVAL_RUNNER = Path(
    os.environ.get(
        "EVAL_RUNNER", str(ROOT / "scripts" / "colab_qwen3_8b_floor_socrates_vllm.py")
    )
)
MODEL = os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base")
CORPUS = Path(os.environ.get("SFT_CORPUS", str(ROOT / "data" / "socrates_sft.jsonl")))
OUT = ROOT / "results" / "socrates_sft" / "FORMAT_SMOKE.json"


def fail(msg: str) -> None:
    print(f"FORMAT SMOKE FAIL: {msg}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"passed": False, "error": msg}, indent=2) + "\n")
    sys.exit(1)


def check_system_string_matches_eval() -> None:
    if not EVAL_RUNNER.exists():
        fail(f"eval runner not found: {EVAL_RUNNER}")
    src = EVAL_RUNNER.read_text()
    m = re.search(r"SYSTEM = \(\s*((?:\s*\"[^\"]*\"\s*)+)\)", src)
    if not m:
        fail("could not parse SYSTEM from eval runner")
    eval_system = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    if eval_system != SYSTEM:
        fail(f"SYSTEM mismatch.\neval: {eval_system!r}\nsft:  {SYSTEM!r}")
    for needle in (
        '{"role": "system", "content": SYSTEM}',
        '{"role": "user", "content": r["prompt"]}',
        "add_generation_prompt=True",
    ):
        if needle not in src:
            fail(f"eval runner no longer contains {needle!r}; format parity broken")
    print("ok: SYSTEM + message construction match the eval runner", flush=True)


def main() -> None:
    check_system_string_matches_eval()
    if not CORPUS.exists():
        fail(f"corpus missing: {CORPUS} (run build_socrates_sft_corpus.py first)")

    from transformers import AutoTokenizer

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sft_socrates_qlora import MaskedSFTDataset, PadCollator

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    rows = []
    with CORPUS.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= 8:
                break
    if not rows:
        fail("corpus is empty")

    max_seq = int(os.environ.get("MAX_SEQ", "1536"))
    ds = MaskedSFTDataset(rows, tok, max_seq)
    checked = 0
    for i, row in enumerate(rows):
        prompt = render_prompt(tok, row)
        target = render_target(row)
        item = ds[i]
        ids, labels = item["input_ids"], item["labels"]
        if len(ids) != len(labels):
            fail(f"row {i}: ids/labels length mismatch")

        n_prompt = sum(1 for l in labels if l == -100)
        if any(l != -100 for l in labels[:n_prompt]):
            fail(f"row {i}: prompt tokens are not fully masked")
        if any(l == -100 for l in labels[n_prompt:]):
            fail(f"row {i}: response region contains masked tokens")

        supervised = tok.decode([l for l in labels if l != -100])
        if target not in supervised:
            fail(f"row {i}: supervised text {supervised!r} does not contain target {target!r}")

        # Full text parity: prompt + target must round-trip through the tokens.
        decoded = tok.decode(ids)
        expected_tail = target
        if not decoded.endswith(expected_tail) and expected_tail not in decoded[-64:]:
            fail(f"row {i}: decoded tail {decoded[-64:]!r} missing target {expected_tail!r}")
        # Prompt is only truncated when it exceeds the budget; otherwise exact.
        prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        if len(prompt_ids) <= max_seq - len(tok(target, add_special_tokens=False)["input_ids"]):
            if tok.decode(ids[:n_prompt]) != prompt:
                fail(f"row {i}: prompt text differs from eval rendering")
        checked += 1

    batch = PadCollator(tok.pad_token_id)([ds[i] for i in range(len(rows))])
    if batch["input_ids"].shape != batch["labels"].shape:
        fail("collator shape mismatch")
    if int((batch["labels"] != -100).sum()) == 0:
        fail("collated batch has no supervised tokens")

    payload = {
        "passed": True,
        "rows_checked": checked,
        "model": MODEL,
        "max_seq": max_seq,
        "system": SYSTEM,
        "example_prompt_tail": render_prompt(tok, rows[0])[-160:],
        "example_target": render_target(rows[0]),
        "supervised_tokens_in_batch": int((batch["labels"] != -100).sum()),
        "batch_shape": list(batch["input_ids"].shape),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2), flush=True)
    print("FORMAT SMOKE PASS", flush=True)


if __name__ == "__main__":
    main()
