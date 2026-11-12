import os, sys; os.environ["HONEST"]="0"
import pandas as pd, numpy as np
from buildcache import build_cached
df = build_cached(); df = df[~df.known & df.dailyRank.notna() & (df.day >= "2026-03-01")].copy()
df["grp"] = np.where(df.dailyRank == 1, "1 winner", np.where(df.dailyRank <= 3, "2 rank2-3", np.where(df.dailyRank <= 10, "3 rank4-10", "4 rest")))
F = ["ph_n_makers", "ph_n_makers_new", "x_n_makers_with_x", "ph_maker_has_headline", "ph_maker_max_age_d", "ph_maker_min_age_d", "ph_self_hunted", "ph_hunter_age_d"]
print(df.groupby("grp")[F].mean().round(3).T.to_string())
print(df.groupby("grp")[F].apply(lambda g: g.isna().mean()).round(3).T.to_string())
for c in ["ph_n_makers_new", "ph_maker_min_age_d"]:
    print(c, df.groupby("grp")[c].describe()[["mean","25%","50%","75%"]].round(1).to_string())
print("share min maker account age < 2 days:", df.groupby("grp").ph_maker_min_age_d.apply(lambda s: (s < 2).mean()).round(3).to_dict())
