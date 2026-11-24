"""LoRA fine-tuning and batch generation for an open chat model. Standalone: needs only torch, transformers and peft,
so it can be copied to a GPU machine as one file.

    python lora.py train    --model Qwen/Qwen2.5-7B-Instruct --train train.jsonl --out adapter [--epochs 1]
    python lora.py generate --model Qwen/Qwen2.5-7B-Instruct [--adapter adapter] --rows eval.jsonl --out gen.jsonl

Rows are {"messages": [...]} in chat format (see export.py). Training takes the loss on the last (assistant) turn only.
Adapters and generations are private: store them outside the repository.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time

import torch

HEAD = 256  # prompt tokens always kept from the start when a prompt has to be shortened (the instructions)


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def prompt_ids(tok, messages: list[dict], budget: int) -> list[int]:
    """Token ids of the chat prompt up to the start of the answer; the middle is cut when it exceeds `budget`."""
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    ids = tok(text, add_special_tokens=False)["input_ids"]
    if len(ids) > budget:
        ids = ids[:HEAD] + ids[-(budget - HEAD):]
    return ids


def answer_ids(tok, messages: list[dict]) -> list[int]:
    """Token ids of the assistant turn as the chat template writes it (answer plus the end-of-turn marker)."""
    prompt = tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(messages, tokenize=False)
    tail = full[len(prompt):] if full.startswith(prompt) else messages[-1]["content"] + (tok.eos_token or "")
    return tok(tail, add_special_tokens=False)["input_ids"]


def load(model_name: str, adapter: str | None = None, train: bool = False):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(adapter or model_name)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    try:
        model = AutoModelForCausalLM.from_pretrained(model_name, dtype=dtype)
    except TypeError:  # older transformers name for the same argument
        model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype)
    model.to("cuda" if torch.cuda.is_available() else "cpu")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter, is_trainable=train)
    return tok, model


def answer_loss(model, ids, att, lab):
    """Cross-entropy on the answer tokens only. The vocabulary projection is applied to those positions alone: full
    logits for a long prompt cost gigabytes of GPU memory per row and are not needed."""
    try:
        decoder, head = model.get_decoder(), model.get_output_embeddings()
    except AttributeError:
        decoder = head = None
    if decoder is None or head is None:
        return model(input_ids=ids, attention_mask=att, labels=lab).loss
    hidden = decoder(input_ids=ids, attention_mask=att).last_hidden_state
    target = lab[:, 1:]  # position t predicts token t + 1
    keep = target != -100
    return torch.nn.functional.cross_entropy(head(hidden[:, :-1][keep]).float(), target[keep])


# ------------------------------------------------------------------------------------------ train
def train(a) -> None:
    from peft import LoraConfig, get_peft_model
    from transformers import get_cosine_schedule_with_warmup
    random.seed(a.seed); torch.manual_seed(a.seed)
    tok, model = load(a.model)
    dev = next(model.parameters()).device
    rows = read_jsonl(a.train)
    if a.limit:
        rows = rows[:a.limit]
    data = []
    for r in rows:
        ans = answer_ids(tok, r["messages"])[:a.max_answer]
        p = prompt_ids(tok, r["messages"][:-1], a.max_prompt)  # same prompt budget as generation
        data.append((p + ans, [-100] * len(p) + ans))
    print(f"rows {len(data)} mean_tokens {sum(len(x) for x, _ in data) / len(data):.0f} "
          f"max_tokens {max(len(x) for x, _ in data)}", flush=True)

    if a.grad_checkpoint:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()  # frozen base + checkpointing: inputs must carry grad to reach the adapters
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(
        r=a.r, lora_alpha=2 * a.r, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    model.print_trainable_parameters()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)

    def batches():
        order = sorted(range(len(data)), key=lambda i: len(data[i][0]))  # similar lengths together: less padding
        bs = [order[i:i + a.batch] for i in range(0, len(order), a.batch)]
        random.shuffle(bs)
        return bs

    steps = math.ceil(len(data) / a.batch / a.accum) * a.epochs
    sched = get_cosine_schedule_with_warmup(opt, max(1, int(0.05 * steps)), steps)
    model.train()
    t0, step, seen, run_loss, run_n = time.time(), 0, 0, 0.0, 0
    for epoch in range(a.epochs):
        for k, b in enumerate(batches()):
            n = max(len(data[i][0]) for i in b)
            ids = torch.full((len(b), n), tok.pad_token_id, dtype=torch.long)
            lab = torch.full((len(b), n), -100, dtype=torch.long)
            att = torch.zeros((len(b), n), dtype=torch.long)
            for j, i in enumerate(b):
                x, y = data[i]
                ids[j, :len(x)] = torch.tensor(x); lab[j, :len(y)] = torch.tensor(y); att[j, :len(x)] = 1
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
                loss = answer_loss(model, ids.to(dev), att.to(dev), lab.to(dev))
            (loss / a.accum).backward()
            run_loss += loss.item(); run_n += 1; seen += len(b)
            if (k + 1) % a.accum == 0:
                if step == 0 and not any(p.grad is not None and float(p.grad.abs().sum()) > 0 for p in params):
                    raise RuntimeError("no gradient reached the adapters: check gradient checkpointing settings")
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
                if step % a.log_every == 0 or step == 1:
                    el = time.time() - t0
                    print(f"epoch {epoch} step {step}/{steps} loss {run_loss / run_n:.4f} rows {seen} "
                          f"{el:.0f}s eta {el / step * (steps - step):.0f}s", flush=True)
                    run_loss, run_n = 0.0, 0
        opt.zero_grad(set_to_none=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    json.dump({"model": a.model, "rows": len(data), "epochs": a.epochs, "steps": step, "r": a.r, "lr": a.lr,
               "seconds": round(time.time() - t0)}, open(f"{a.out}/train_info.json", "w"))
    print("saved", a.out, flush=True)


# ------------------------------------------------------------------------------------------ generate
@torch.no_grad()
def generate(a) -> None:
    torch.manual_seed(a.seed)
    tok, model = load(a.model, a.adapter)
    model.eval()
    dev = next(model.parameters()).device
    rows = read_jsonl(a.rows)
    if a.limit:
        rows = rows[:a.limit]
    enc = [prompt_ids(tok, r["messages"], a.max_prompt) for r in rows]
    order = sorted(range(len(rows)), key=lambda i: -len(enc[i]))
    out, t0 = [None] * len(rows), time.time()
    for s in range(0, len(order), a.batch):
        b = order[s:s + a.batch]
        n = max(len(enc[i]) for i in b)
        ids = torch.full((len(b), n), tok.pad_token_id, dtype=torch.long)
        att = torch.zeros((len(b), n), dtype=torch.long)
        for j, i in enumerate(b):  # left padding: generation continues from the last prompt token
            ids[j, n - len(enc[i]):] = torch.tensor(enc[i]); att[j, n - len(enc[i]):] = 1
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=dev.type == "cuda"):
            gen = model.generate(input_ids=ids.to(dev), attention_mask=att.to(dev), max_new_tokens=a.max_new,
                                 do_sample=a.temperature > 0, temperature=a.temperature or None, top_p=0.9,
                                 pad_token_id=tok.pad_token_id)
        for j, i in enumerate(b):
            out[i] = tok.decode(gen[j, n:], skip_special_tokens=True).strip()
        if (s // a.batch) % 10 == 0:
            print(f"generated {min(s + a.batch, len(rows))}/{len(rows)} {time.time() - t0:.0f}s", flush=True)
    with open(a.out, "w") as f:
        for r, text in zip(rows, out):
            f.write(json.dumps({"meta": r.get("meta", {}), "text": text}) + "\n")
    print("wrote", a.out, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--model", required=True); t.add_argument("--train", required=True); t.add_argument("--out", required=True)
    t.add_argument("--epochs", type=int, default=1); t.add_argument("--lr", type=float, default=2e-4)
    t.add_argument("--r", type=int, default=16); t.add_argument("--batch", type=int, default=2)
    t.add_argument("--accum", type=int, default=8); t.add_argument("--max-prompt", type=int, default=1536)
    t.add_argument("--max-answer", type=int, default=256); t.add_argument("--grad-checkpoint", action="store_true")
    t.add_argument("--log-every", type=int, default=10); t.add_argument("--limit", type=int, default=0)
    t.add_argument("--seed", type=int, default=0)
    g = sub.add_parser("generate")
    g.add_argument("--model", required=True); g.add_argument("--adapter"); g.add_argument("--rows", required=True)
    g.add_argument("--out", required=True); g.add_argument("--batch", type=int, default=8)
    g.add_argument("--max-prompt", type=int, default=1536); g.add_argument("--max-new", type=int, default=200)
    g.add_argument("--temperature", type=float, default=0.7); g.add_argument("--limit", type=int, default=0)
    g.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    (train if a.cmd == "train" else generate)(a)


if __name__ == "__main__":
    main()
