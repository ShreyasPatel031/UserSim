"""Tests for arm3_feats (no network, random embeddings). python test_arm3_feats.py  -> exit 0 = all pass.
1 leak: changing votes / dailyRank of days d-1 and d must not change any B / C feature of day d (only days <= d-2 count).
2 line-up: A on a masked 00:05 line-up uses only the masked rows (a launch outside the line-up does not move A of the others).
3 C: a same-name relaunch 10 days later is found (plain and strong), one 1 day later is not.
4 shapes: every NEW column exists, A has no NaN, B is NaN only when no history."""
import sys
import numpy as np, pandas as pd
import arm3_feats as A3
rng = np.random.default_rng(0); n_days, per = 40, 6; rows = []
for k in range(n_days):
    d = (pd.Timestamp("2026-03-01") + pd.Timedelta(days=k)).strftime("%Y-%m-%d")
    for j in range(per):
        rows.append({"id": f"{k}_{j}", "day": d, "name": f"Prod{k}x{j}", "topics": [["AI", "Dev"], ["SaaS"], ["AI"]][j % 3], "ph_hunter_followers": rng.random(),
                     "hist_hunter_rel": rng.random(), "votes": float(rng.integers(10, 500)), "dailyRank": j + 1, "domain": f"p{k}{j}.com", "tagline": "t", "description": "d"})
rows.append({**rows[5], "id": "re10", "day": "2026-03-11", "name": rows[5]["name"]})            # relaunch 10 days after day 0
rows.append({**rows[11], "id": "re1", "day": "2026-03-03", "name": rows[11]["name"] + " AI"})   # 1 day after day 1 (too recent)
df = pd.DataFrame(rows); E = rng.normal(size=(len(df), 384)).astype(np.float32); E /= np.linalg.norm(E, axis=1, keepdims=True)
ok = {}
X1, NEW = A3.add_feats(df, E); d = "2026-03-20"; df2 = df.copy()
m = df2.day.isin(["2026-03-19", "2026-03-20"]); df2.loc[m, "votes"] = 99999.0; df2.loc[m, "dailyRank"] = 1
X2, _ = A3.add_feats(df2, E); BC = [c for c in NEW if c[0] in "BC"]
ok["1 leak d-1/d labels do not move day d B/C"] = bool(np.allclose(X1[X1.day == d][BC].fillna(-7).values, X2[X2.day == d][BC].fillna(-7).values))
lu = np.zeros(len(df), bool); ix = df.index[df.day == d].values; lu[ix[:-1]] = True
X3, _ = A3.add_feats(df, E, line_up=lu); E4 = E.copy(); E4[ix[-1]] = -E4[ix[-1]]; X4, _ = A3.add_feats(df, E4, line_up=lu)
AC = [c for c in NEW if c.startswith("A_")]
ok["2 A uses only the 00:05 line-up"] = bool(np.allclose(X3.loc[ix[:-1], AC].values, X4.loc[ix[:-1], AC].values)) and bool(X3.loc[ix[-1], AC].isna().all())
for nm in ("plain", "strong"):
    X, _ = A3.add_feats(df, E, norm=nm)
    ok[f"3 C relaunch found ({nm})"] = int(X.loc[X.id == "re10", "C_prev"].iloc[0]) == 1
ok["3 C 1-day relaunch not used (plain)"] = int(X1.loc[X1.id == "re1", "C_prev"].iloc[0]) == 0
ok["4 columns + A complete"] = all(c in X1 for c in NEW) and not X1[AC].isna().any().any() and X1[X1.day == "2026-03-01"].B_nn365.isna().all()
for k, v in ok.items(): print(("PASS " if v else "FAIL ") + k)
sys.exit(0 if all(ok.values()) else 1)
