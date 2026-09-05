#!/usr/bin/env python3
"""Re-score the merged CUA checkpoint on held-out samples.

The in-training eval capped generation at 128 new tokens, which truncates before
the pyautogui line whenever the Thought block is long. This uses a real budget and
prints raw completions so parse failures are diagnosable.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import torch
from PIL import Image

import train_ministral3_cua as T


def xy(text: str):
    m = re.search(r"x=([0-9.]+)\s*,\s*y=([0-9.]+)", text)
    return (float(m.group(1)), float(m.group(2))) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(Path.home() / "usersim" / "Ministral3-3B-CUA-web"))
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--max-new-tokens", type=int, default=384)
    ap.add_argument("--show", type=int, default=3)
    ap.add_argument("--out", default=str(Path.home() / "usersim" / "eval_full.json"))
    args = ap.parse_args()

    from transformers import AutoProcessor, Mistral3ForConditionalGeneration

    # Rebuild the identical holdout split (build_records seeds RNG internally).
    records = T.build_records(T.build_index(), False)
    n_hold = min(200, max(8, len(records) // 10))
    holdout = records[:n_hold]
    T.log(f"holdout {len(holdout)}")

    processor = AutoProcessor.from_pretrained(args.model)
    processor.image_processor.size = {"longest_edge": max(T.IMAGE_W, T.IMAGE_H)}
    tok = processor.tokenizer
    model = Mistral3ForConditionalGeneration.from_pretrained(
        args.model, dtype=torch.bfloat16, device_map="cuda:0"
    )
    model.eval()

    hits = tried = parsed = 0
    shown = 0
    rows = []
    for rec in holdout[: args.n]:
        gold = xy(rec["assistant"])
        if not gold:
            continue
        im = Image.open(rec["image"]).convert("RGB").resize((T.IMAGE_W, T.IMAGE_H), Image.BICUBIC)
        enc = processor(text=T.build_prompt(rec), images=[im], return_tensors="pt").to("cuda:0")
        with torch.no_grad():
            o = model.generate(
                **enc, max_new_tokens=args.max_new_tokens, do_sample=False,
                pad_token_id=tok.pad_token_id,
            )
        pred = tok.decode(o[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
        tried += 1
        pr = xy(pred)
        ok = False
        if pr:
            parsed += 1
            ok = abs(pr[0] - gold[0]) < 0.05 and abs(pr[1] - gold[1]) < 0.05
            hits += int(ok)
        if shown < args.show:
            shown += 1
            print("=" * 70)
            print("PRED:", pred[:600])
            print("GOLD:", rec["assistant"][:300])
            print("parsed:", pr, "gold:", gold, "hit:", ok)
        rows.append({"pred_xy": pr, "gold_xy": gold, "hit": ok, "n_chars": len(pred)})

    summary = {
        "n": tried,
        "parsed": parsed,
        "parse_rate": parsed / max(tried, 1),
        "click_within_5pct": hits,
        "accuracy": hits / max(tried, 1),
        "max_new_tokens": args.max_new_tokens,
    }
    print("\nSUMMARY " + json.dumps(summary, indent=2))
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
