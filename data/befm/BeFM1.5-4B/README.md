---
license: apache-2.0
base_model: Qwen/Qwen3-4B-Instruct-2507
language:
  - en
library_name: peft
pipeline_tag: text-generation
tags:
  - PEFT
  - LoRA
  - Behavior
  - BehavioralScience
  - FoundationModel
---

# Be.FM 1.5-4B Model Card

## Overview

**Be.FM 1.5-4B** is an open foundation model for human behavior modeling, built on Qwen3-4B-Instruct-2507 and fine-tuned via LoRA on diverse behavioral datasets. It is designed for predicting human survey responses, personality scores, demographic attributes, and behavior in economic and strategic games.

**Paper**: The Be.FM 1.5 paper link will be added here when it is released.

---

## Usage

Be.FM 1.5-4B is a LoRA adapter on top of `Qwen/Qwen3-4B-Instruct-2507`. You can use the model with Hugging Face Transformers and PEFT on a single 24GB+ GPU.

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

base_model_id = "Qwen/Qwen3-4B-Instruct-2507"
peft_model_id = "befm/BeFM1.5-4B"

tokenizer = AutoTokenizer.from_pretrained(peft_model_id)
model = AutoModelForCausalLM.from_pretrained(
    base_model_id, device_map="auto", torch_dtype="bfloat16"
)
model = PeftModel.from_pretrained(model, peft_model_id)
```

---

## Inference

Be.FM 1.5 uses the standard chat template; format prompts with system + user roles.

```python
messages = [
    {"role": "system", "content": "You are a participant in a behavioral study."},
    {"role": "user", "content": "<your question here>"},
]
prompt = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)
inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
outputs = model.generate(
    **inputs, max_new_tokens=64,
    temperature=0.6, top_p=0.95, top_k=20, do_sample=True,
)
print(tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True))
```

Recommended sampling: `temperature=0.6, top_p=0.95, top_k=20`.

More examples can be found in the appendix of the paper.

---

## Citation, Terms of Use, and Feedback

The Be.FM 1.5 paper will be linked here when it is released.

By using this model, you agree to [Be.FM Terms of Use](https://docs.google.com/document/d/10n7ccfUAf89yQhx5u1lF45o70JgsOEYNu8bDxtRKbHA/edit?usp=sharing).

**License**: apache-2.0, inherited from the Qwen3-4B-Instruct-2507 base model.

We welcome your feedback on model performance as you apply Be.FM 1.5 to your work. Please share your feedback via the [feedback form](https://forms.gle/M4XJn9ervWzE3ujb9).
