import os; os.environ["HONEST"]="0"
import pandas as pd, numpy as np
from buildcache import build_cached
df = build_cached(); df = df[~df.known & df.dailyRank.notna() & (df.day >= "2026-03-01")].copy()
df["grp"] = np.where(df.dailyRank == 1, "1", np.where(df.dailyRank <= 3, "2-3", np.where(df.dailyRank <= 10, "4-10", "11+")))
F = [c for c in ["ph_n_media", "ph_has_video", "ph_desc_len", "ph_tagline_len", "ph_n_topics", "ps_n_images", "ps_gallery", "ps_video", "ps_logo", "ps_description", "ps_website", "ps_links", "vs_clarity", "llm_pitch", "llm_site", "llm_brand"] if c in df]
print(df.groupby("grp")[F].mean().round(3).T[["1", "2-3", "4-10", "11+"]].to_string())
print("vs coverage", df.groupby("grp").vs_clarity.apply(lambda s: s.notna().mean()).round(3).to_dict() if "vs_clarity" in df else "")
