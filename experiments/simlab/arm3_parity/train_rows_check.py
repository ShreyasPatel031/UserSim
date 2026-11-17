import os, sys, numpy as np, pandas as pd
sys.argv = ["x", os.environ["SPX"] + "/par/out_tr"]
src = open("parity_run.py").read().split("summary = {")[0]   # defs + BTD build only
exec(compile(src, "parity_head", "exec"))
d = "2026-11-16"; cut = "2026-11-15"
L = live_frame(d); trL = L[~L.known & (L.day < cut) & ~L.is_today]
B = BTD[BTD.day < cut]
print("live train rows", len(trL), "2025", int((trL.day < "2026").sum()), "| bt train rows", len(B), "2025", int((B.day < "2026").sum()))
print("bt rows that live drops as known:", int(B.id.isin(L[L.known].id).sum()), "| live known total", int(L.known.sum()))
print("ids only in bt", len(set(B.id) - set(trL.id)), "ids only in live", len(set(trL.id) - set(B.id)))
x = set(B.id) - set(trL.id); print("bt-only by year", B[B.id.isin(x)].day.str[:4].value_counts().to_dict())
