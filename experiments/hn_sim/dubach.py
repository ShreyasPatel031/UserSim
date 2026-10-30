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
    path = os.path.join(S.LOCAL, "dubach_partial.parquet")          # resumable: VMs get stopped by others
    done = pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame(columns=["post_id", "dubach"])
    p = p[~p.post_id.isin(done.post_id)]
    titles, ids, out = p.title.fillna("").tolist(), p.post_id.to_numpy(), []
    print(len(done), "already scored;", len(titles), "to go", flush=True)
    with torch.inference_mode():
        for i in range(0, len(titles), 256):
            x = tok(titles[i:i + 256], return_tensors="pt", truncation=True, max_length=128, padding=True)
            out.append(pd.DataFrame({"post_id": ids[i:i + 256],
                                     "dubach": torch.softmax(mdl(**x).logits, -1)[:, 1].numpy()}))
            if (i // 256) % 100 == 99 or i + 256 >= len(titles):
                done = pd.concat([done] + out, ignore_index=True)
                out = []
                done.to_parquet(path, index=False)
                os.system(f"gsutil -q cp {path} gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache/dubach_partial.parquet")
                print(len(done), flush=True)
    done.to_parquet(os.path.join(S.LOCAL, "dubach.parquet"), index=False)
    print("scored", len(done))


if __name__ == "__main__":
    main(sys.argv[1])
