"""Reproduce Philipp Dubach's HN success predictor (huggingface.co/philippdubach/hn-success-predictor, MIT): fine-tuned
RoBERTa-base on titles, P(>=100 points), trained on 2022-2025 Algolia data (temporal split; test AUC 0.685).
Scores every story title since START with his model (raw probability; his isotonic calibrator is monotone, so ranks
are unchanged). His training data overlaps 2022-2025, so use the score only on later stories.
-> <cache>/dubach.parquet (post_id, dubach)

    python dubach.py 2026-01-01
"""
import os
import sys

import numpy as np
import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

import store as S
import top100 as H

REPO = "philippdubach/hn-success-predictor"


def main(start: str) -> None:
    torch.set_num_threads(os.cpu_count())
    tok = AutoTokenizer.from_pretrained(REPO, subfolder="roberta")
    mdl = AutoModelForSequenceClassification.from_pretrained(REPO, subfolder="roberta").eval()
    p = H.stories()
    p = p[p.day >= start]
    titles, out = p.title.fillna("").tolist(), []
    with torch.inference_mode():
        for i in range(0, len(titles), 256):
            x = tok(titles[i:i + 256], return_tensors="pt", truncation=True, max_length=128, padding=True)
            out.append(torch.softmax(mdl(**x).logits, -1)[:, 1].numpy())
            if i % 25600 == 0:
                print(i, len(titles), flush=True)
    pd.DataFrame({"post_id": p.post_id.to_numpy(), "dubach": np.concatenate(out)}).to_parquet(
        os.path.join(S.LOCAL, "dubach.parquet"), index=False)
    print("scored", len(titles))


if __name__ == "__main__":
    main(sys.argv[1])
