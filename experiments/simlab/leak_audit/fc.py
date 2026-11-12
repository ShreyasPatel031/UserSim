import os; os.environ["HONEST"]="0"
import pandas as pd, numpy as np
from buildcache import build_cached
df = build_cached(); df = df[~df.known & df.dailyRank.notna() & (df.day >= "2026-03-01")].copy()
df["grp"] = np.where(df.dailyRank == 1, "1", np.where(df.dailyRank <= 3, "2-3", np.where(df.dailyRank <= 10, "4-10", "11+")))
F = [c for c in ["ps_has_first_comment", "pf_first_comment_words", "ps_first_comment", "pf_emoji_in_first_comment", "pf_founder_story", "pf_asks_for_upvotes"] if c in df]
print(df.groupby("grp")[F].mean().round(3).T.to_string())
