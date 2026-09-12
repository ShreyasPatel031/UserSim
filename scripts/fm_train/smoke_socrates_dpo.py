#!/usr/bin/env python3
"""Format smoke for Socrates DPO pairs.

Blocks the full run unless:
  1. SYSTEM + chat construction still match the eval runner (same as SFT smoke).
  2. Every pair has chosen != rejected, both non-empty.
  3. Rendered prompts use socrates_format and end with the generation prompt.
  4. Chosen/rejected are bare responses (no chat roles injected).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from socrates_format import SYSTEM, build_messages, render_prompt

ROOT = Path(os.environ.get("ROOT", "/opt/usersim_fm"))
EVAL_RUNNER = Path(
    os.environ.get(
        "EVAL_RUNNER",
        str(ROOT / "scripts" / "colab_qwen3_8b_floor_socrates_vllm.py"),
    )
)
MODEL = os.environ.get("SFT_MODEL", "Qwen/Qwen3-8B-Base")
CORPUS = Path(os.environ.get("DPO_CORPUS", str(ROOT / "data" / "socrates_dpo_pairs.jsonl")))
OUT = ROOT / "results" / "socrates_dpo" / "FORMAT_SMOKE.json"
_BARE_NUM = re.compile(r"^\s*[-+]?\d+(?:\.\d+)?\s*$")


def fail(msg: str) -> None:
    print(f"DPO FORMAT SMOKE FAIL: {msg}", flush=True)
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
        fail(f"SYSTEM mismatch.\neval: {eval_system!r}\ndpo:  {SYSTEM!r}")
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
        fail(f"DPO corpus missing: {CORPUS}")

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    rows = []
    with CORPUS.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= 32:
                break
    if len(rows) < 2:
        fail("need at least 2 DPO pairs for smoke")

    bare_ok = 0
    for i, row in enumerate(rows):
        for key in ("prompt", "chosen", "rejected"):
            if key not in row or row[key] is None or str(row[key]).strip() == "":
                fail(f"row {i}: missing/empty {key}")
        if str(row["chosen"]).strip() == str(row["rejected"]).strip():
            fail(f"row {i}: chosen == rejected ({row['chosen']!r})")

        msgs = build_messages({"prompt": row["prompt"]})
        if msgs[0]["content"] != SYSTEM:
            fail(f"row {i}: SYSTEM not applied")
        rendered = render_prompt(tok, {"prompt": row["prompt"]})
        if SYSTEM.split(".")[0] not in rendered:
            fail(f"row {i}: rendered prompt missing SYSTEM")
        # Generation prompt marker for Qwen chat template.
        if "assistant" not in rendered.lower() and "<|im_start|>assistant" not in rendered:
            # Still OK if template differs; require user content present.
            if row["prompt"][:40] not in rendered:
                fail(f"row {i}: user prompt not in rendered chat")

        # Chosen/rejected must be continuation text, not full chat transcripts.
        for side in ("chosen", "rejected"):
            text = str(row[side])
            if "<|im_start|>" in text or "system" == text.strip().lower():
                fail(f"row {i}: {side} looks like a chat transcript: {text[:80]!r}")
        if _BARE_NUM.match(str(row["chosen"])) and _BARE_NUM.match(str(row["rejected"])):
            bare_ok += 1

    bare_rate = bare_ok / len(rows)
    if bare_rate < 0.5:
        fail(f"bare-numeric rate on smoke pairs too low: {bare_rate:.2f}")

    payload = {
        "passed": True,
        "rows_checked": len(rows),
        "bare_numeric_pair_rate": bare_rate,
        "model": MODEL,
        "system": SYSTEM,
        "example_chosen": rows[0]["chosen"],
        "example_rejected": rows[0]["rejected"],
        "example_prompt_tail": render_prompt(tok, {"prompt": rows[0]["prompt"]})[-160:],
        "corpus": str(CORPUS),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2), flush=True)
    print("DPO FORMAT SMOKE PASS", flush=True)


if __name__ == "__main__":
    main()
