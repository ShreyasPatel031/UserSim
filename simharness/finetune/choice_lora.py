"""CHOICE-FT-1: LoRA fine-tune of an open chat model as a yes/no backing scorer, with person-day packing.
Standalone (torch, transformers, peft), so it can be copied to a GPU machine as one file.

    python choice_lora.py train --model Qwen/Qwen2.5-7B-Instruct --train train.jsonl --eval eval.jsonl --out adapter \
        --rows 200000 --eval-at 50000 100000 [--upload gs://.../runs/TAG]
    python choice_lora.py score --model Qwen/Qwen2.5-7B-Instruct [--adapter DIR] --eval eval.jsonl --out scores.jsonl

Input rows are person-days: {"prefix": text, "suffixes": [launch text, ...], "labels": [0/1, ...] (train only),
"meta": {...}}. The prompt for pair (person-day, launch k) is the chat prompt for the user message prefix + suffix_k,
up to the start of the answer. All pairs of a person-day are packed into one sequence: the prefix once, then every
launch's tokens, each launch attending only to the prefix and to itself (4-D attention mask) with positions restarted
after the prefix. That is the same computation as one prompt per pair, at a fraction of the tokens.

Score = P(Yes) = sigmoid(logit("Yes") - logit("No")) at the last prompt token of each launch. Training loss =
cross-entropy of the real answer token ("Yes" / "No") over the full vocabulary at the same position (FT-TASKC recipe:
LoRA r=16 on all projections, lr 2e-4, cosine, one epoch). Adapters and scores are private: keep them out of the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time

import torch

SLOT = "<<LAUNCH_SLOT>>"


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def split_template(tok) -> tuple[str, str]:
    text = tok.apply_chat_template([{"role": "user", "content": SLOT}], tokenize=False, add_generation_prompt=True)
    head, tail = text.split(SLOT)
    return head, tail


def encode(tok, row: dict, head: str, tail: str, max_prefix: int) -> tuple[list[int], list[list[int]]]:
    pre = tok(head + row["prefix"], add_special_tokens=False)["input_ids"]
    if len(pre) > max_prefix:  # keep the start (instructions, counts) and the end (the launch slot header)
        pre = pre[:max_prefix // 2] + pre[-(max_prefix - max_prefix // 2):]
    suf = [tok(s + tail, add_special_tokens=False)["input_ids"] for s in row["suffixes"]]
    return pre, suf


def pack(items: list[tuple[list[int], list[list[int]]]], pad_id: int, dtype, device):
    """items: [(prefix ids, [suffix ids...])]. Returns input_ids, position_ids, 4-D additive mask, answer index
    (batch row, position) per suffix in order."""
    T = max(len(p) + sum(len(s) for s in ss) for p, ss in items)
    B = len(items)
    ids = torch.full((B, T), pad_id, dtype=torch.long)
    pos = torch.zeros((B, T), dtype=torch.long)
    seg = torch.full((B, T), -1, dtype=torch.long)
    ans_b, ans_t = [], []
    for b, (p, ss) in enumerate(items):
        n = len(p)
        ids[b, :n] = torch.tensor(p); pos[b, :n] = torch.arange(n); seg[b, :n] = 0
        t = n
        for k, s in enumerate(ss, start=1):
            L = len(s)
            ids[b, t:t + L] = torch.tensor(s); pos[b, t:t + L] = torch.arange(n, n + L); seg[b, t:t + L] = k
            ans_b.append(b); ans_t.append(t + L - 1)
            t += L
        pos[b, t:] = torch.arange(T - t) + t  # padding: any positions, masked from real tokens
    seg = seg.to(device)
    causal = torch.ones((T, T), dtype=torch.bool, device=device).tril()
    si, sj = seg[:, :, None], seg[:, None, :]
    allowed = causal[None] & ((sj == 0) | (sj == si))
    mask = torch.zeros((B, 1, T, T), dtype=dtype, device=device)
    mask.masked_fill_(~allowed[:, None], torch.finfo(dtype).min)
    return ids.to(device), pos.to(device), mask, torch.tensor(ans_b, device=device), torch.tensor(ans_t, device=device)


def batches_by_tokens(enc: list, budget: int, shuffle: bool, seed: int = 0) -> list[list[int]]:
    lens = [len(p) + sum(len(s) for s in ss) for p, ss in enc]
    order = sorted(range(len(enc)), key=lambda i: lens[i])
    out, cur, cur_max = [], [], 0
    for i in order:
        m = max(cur_max, lens[i])
        if cur and m * (len(cur) + 1) > budget:
            out.append(cur); cur, m = [], lens[i]
        cur.append(i); cur_max = m
    if cur:
        out.append(cur)
    if shuffle:
        random.Random(seed).shuffle(out)
    return out


def load(model_name: str, adapter: str | None = None, attn: str = "sdpa"):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_name)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    try:
        model = AutoModelForCausalLM.from_pretrained(model_name, dtype=dtype, attn_implementation=attn)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype, attn_implementation=attn)
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    return tok, model


def answer_hidden(model, ids, pos, mask, ab, at):
    dec = model.get_decoder()
    h = dec(input_ids=ids, position_ids=pos, attention_mask=mask).last_hidden_state
    return h[ab, at]


def yes_no_ids(tok) -> tuple[int, int]:
    y, n = tok.encode("Yes", add_special_tokens=False), tok.encode("No", add_special_tokens=False)
    assert len(y) == 1 and len(n) == 1, (y, n)
    return y[0], n[0]


@torch.no_grad()
def score_rows(model, tok, rows, enc, budget: int, log=print) -> list[list[float]]:
    was_training = model.training
    model.eval()
    dev = next(model.parameters()).device
    dtype = torch.bfloat16 if dev.type == "cuda" else torch.float32
    head = model.get_output_embeddings()
    yi, ni = yes_no_ids(tok)
    W = head.weight[[yi, ni]]
    out: list[list[float] | None] = [None] * len(rows)
    t0 = time.time()
    bs = batches_by_tokens(enc, budget, shuffle=False)
    for k, b in enumerate(bs):
        ids, pos, mask, ab, at = pack([enc[i] for i in b], tok.pad_token_id, dtype, dev)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
            h = answer_hidden(model, ids, pos, mask, ab, at)
        lg = (h.float() @ W.float().T)
        p = torch.sigmoid(lg[:, 0] - lg[:, 1]).tolist()
        j = 0
        for i in b:
            n = len(enc[i][1])
            out[i] = p[j:j + n]; j += n
        if k % 50 == 0:
            log(f"scored batch {k + 1}/{len(bs)} {time.time() - t0:.0f}s", flush=True)
    if was_training:
        model.train()
    return out


def write_scores(rows, scores, path):
    with open(path, "w") as f:
        for r, s in zip(rows, scores):
            f.write(json.dumps({"meta": r.get("meta", {}), "p": s}) + "\n")


def upload(paths: list[str], dest: str | None):
    if dest:
        subprocess.run(["gsutil", "-q", "-m", "cp", "-r", *paths, dest.rstrip("/") + "/"], check=False)


# ------------------------------------------------------------------------------------------ train
def train(a) -> None:
    from peft import LoraConfig, get_peft_model
    from transformers import get_cosine_schedule_with_warmup
    random.seed(a.seed); torch.manual_seed(a.seed)
    tok, model = load(a.model)
    dev = next(model.parameters()).device
    dtype = torch.bfloat16 if dev.type == "cuda" else torch.float32
    head, tail = split_template(tok)
    yi, ni = yes_no_ids(tok)
    rows = read_jsonl(a.train)
    # keep whole person-days in file order (the export shuffled them) until the row target is reached
    keep, n = [], 0
    for r in rows:
        if a.rows and n >= a.rows:
            break
        keep.append(r); n += len(r["labels"])
    rows = keep
    enc = [encode(tok, r, head, tail, a.max_prefix) for r in rows]
    tgt = [[yi if y else ni for y in r["labels"]] for r in rows]
    n_rows = sum(len(t) for t in tgt)
    ntok = sum(len(p) + sum(len(s) for s in ss) for p, ss in enc)
    print(f"person-days {len(rows)} rows {n_rows} positives {sum(sum(r['labels']) for r in rows)} "
          f"tokens {ntok} ({ntok / n_rows:.0f} per row)", flush=True)
    ev_rows = read_jsonl(a.eval) if a.eval else []
    ev_enc = [encode(tok, r, head, tail, a.max_prefix) for r in ev_rows]
    if ev_rows:
        print(f"eval person-days {len(ev_rows)} pairs {sum(len(e[1]) for e in ev_enc)} tokens "
              f"{sum(len(p) + sum(len(s) for s in ss) for p, ss in ev_enc)}", flush=True)

    if a.grad_checkpoint:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    batches = batches_by_tokens(enc, a.train_tokens, shuffle=True, seed=a.seed)  # one optimizer step each
    steps = len(batches)
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(0.05 * steps)), steps)
    head_mod = model.get_output_embeddings()

    def snapshot(tag: str):
        d = f"{a.out}/ckpt_{tag}"
        model.save_pretrained(d)
        if ev_rows:
            sc = score_rows(model, tok, ev_rows, ev_enc, a.eval_tokens)
            write_scores(ev_rows, sc, f"scores_{tag}.jsonl")
            upload([f"scores_{tag}.jsonl"], a.upload)
        upload([d], a.upload + "/adapters" if a.upload else None)
        print(f"snapshot {tag} done {time.time() - t0:.0f}s", flush=True)

    if a.score_base and ev_rows:
        with model.disable_adapter():
            sc = score_rows(model, tok, ev_rows, ev_enc, a.eval_tokens)
        write_scores(ev_rows, sc, "scores_base.jsonl"); upload(["scores_base.jsonl"], a.upload)

    model.train()
    t0, step, seen, run_loss, run_n = time.time(), 0, 0, 0.0, 0
    eval_at = sorted(a.eval_at)
    for b in batches:
        ids, pos, mask, ab, at = pack([enc[i] for i in b], tok.pad_token_id, dtype, dev)
        y = torch.tensor([t for i in b for t in tgt[i]], device=dev)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
            h = answer_hidden(model, ids, pos, mask, ab, at)
        loss = torch.nn.functional.cross_entropy(head_mod(h).float(), y)  # mean over the micro-batch's rows
        loss.backward()
        if step == 0 and not any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in params):
            raise RuntimeError("no gradient reached the adapters")
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
        run_loss += loss.item() * len(y); run_n += len(y); seen += len(y)
        if step % a.log_every == 0 or step == 1:
            el = time.time() - t0
            print(f"step {step}/{steps} loss {run_loss / run_n:.4f} rows {seen} {el:.0f}s "
                  f"eta {el / seen * (n_rows - seen):.0f}s", flush=True)
            run_loss, run_n = 0.0, 0
        while eval_at and seen >= eval_at[0]:
            snapshot(str(eval_at.pop(0)))
    json.dump({"model": a.model, "rows": seen, "person_days": len(rows), "steps": step, "r": a.r, "lr": a.lr,
               "train_tokens": a.train_tokens, "seconds": round(time.time() - t0)},
              open("train_info.json", "w"))
    upload(["train_info.json"], a.upload)
    snapshot(f"final_{seen}")
    print("done", flush=True)


def score(a) -> None:
    tok, model = load(a.model, a.adapter)
    head, tail = split_template(tok)
    rows = read_jsonl(a.eval)
    enc = [encode(tok, r, head, tail, a.max_prefix) for r in rows]
    write_scores(rows, score_rows(model, tok, rows, enc, a.eval_tokens), a.out)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--model", required=True); t.add_argument("--train", required=True)
    t.add_argument("--eval", default=""); t.add_argument("--out", required=True)
    t.add_argument("--rows", type=int, default=0); t.add_argument("--eval-at", type=int, nargs="*", default=[])
    t.add_argument("--lr", type=float, default=2e-4); t.add_argument("--r", type=int, default=16)
    t.add_argument("--train-tokens", type=int, default=6000)  # tokens per micro-batch = one optimizer step
    t.add_argument("--eval-tokens", type=int, default=24000); t.add_argument("--max-prefix", type=int, default=1024)
    t.add_argument("--grad-checkpoint", action="store_true"); t.add_argument("--log-every", type=int, default=20)
    t.add_argument("--seed", type=int, default=0); t.add_argument("--upload", default="")
    t.add_argument("--score-base", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--model", required=True); s.add_argument("--adapter"); s.add_argument("--eval", required=True)
    s.add_argument("--out", required=True); s.add_argument("--eval-tokens", type=int, default=24000)
    s.add_argument("--max-prefix", type=int, default=1024)
    a = ap.parse_args()
    (train if a.cmd == "train" else score)(a)


if __name__ == "__main__":
    main()
