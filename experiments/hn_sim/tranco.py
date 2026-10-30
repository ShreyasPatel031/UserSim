"""Domain popularity from the free Tranco top-1M list (tranco-list.eu, today's list; domain popularity is slow-moving,
but it is a current value, so treat it as mildly leaky for domains that got big from HN). Block: f_tranco.parquet.

    python tranco.py
"""
import io
import os
import zipfile
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

import store as S


def main():
    r = requests.get("https://tranco-list.eu/top-1m.csv.zip", timeout=120, allow_redirects=True)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    T = pd.read_csv(z.open(z.namelist()[0]), header=None, names=["rank", "domain"]).set_index("domain")["rank"]
    import top100 as H
    p = H.stories()
    host = p.url.fillna("").map(lambda u: urlparse(u).netloc.lower().removeprefix("www."))

    def rank(h):
        parts = h.split(".")
        for i in range(len(parts) - 1):          # longest registered suffix first: blog.google, then google
            d = ".".join(parts[i:])
            if d in T.index:
                return T[d], i == 0
        return np.nan, False
    rr = host.map(rank)
    f = pd.DataFrame({"post_id": p.post_id, "tranco_log_rank": np.log10(rr.map(lambda x: x[0]).astype(float)).to_numpy(),
                      "tranco_exact_host": rr.map(lambda x: int(x[1])).to_numpy()})
    f["tranco_listed"] = f.tranco_log_rank.notna().astype(int)
    f.to_parquet(os.path.join(S.LOCAL, "f_tranco.parquet"), index=False)
    print("tranco block", f.shape, "listed share", round(f.tranco_listed.mean(), 3))


if __name__ == "__main__":
    main()
