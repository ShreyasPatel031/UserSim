"""Read the Quality News 10-minute series files (qn_fine_*.jsonl), skipping a partial last line of a file still being
written; keep stories with a series."""
import json
import os

import pandas as pd

import top100 as H


def load():
    rows = []
    for f in sorted(os.listdir(H.CACHE)):
        if f.startswith("qn_fine_") and f.endswith(".jsonl"):
            for line in open(os.path.join(H.CACHE, f)):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    q = pd.DataFrame(rows)
    return q, q[(q.status == 200) & q.qn_up_10m.map(lambda x: isinstance(x, list))].drop_duplicates("post_id").reset_index(drop=True)
