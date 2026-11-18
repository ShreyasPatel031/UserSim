"""it9b features for the share model (pre-registered with E5, Nov 11): product attributes from the frozen Gemini cache
(product_attrs.py, variant a) x each person's attribute preference from upvotes of launches dated <= d-2.

Per launch: 46 binary attributes (category 12, audience 10, market 3, platform 9, ai_native, open_source, agent,
developer_tool, pricing 4, maturity 4) and 5 scores (1-5).
Per person p before d: share of p's upvoted launches with each attribute (launches dated <= d-2), against the base rate =
the mean attribute over the line-ups of the days p was active (<= d-2); lift = shrunk share / base (alpha = 5 votes).
Row features (person x launch):
  at_lift_sum / _max / _mean   over L's binary attributes, log lift
  at_lift_cat, at_lift_aud     log lift on L's category; mean log lift over L's audiences
  at_gap_<score>               |L's score - p's mean score over upvotes| (shrunk to the global mean)
  at_emb_tag, at_emb_desc      cosine of L's cleaned tagline / description embedding vs p's history centroid (if emb file)
Launch-level (the same for everyone): at_<score>, at_price_*, at_mat_*, at_ai, at_os, at_rare_cat, at_rare_aud
  (share of that day's line-up with L's category / audiences; line-up = the day's rows, flagged final list)."""
import json, os
import numpy as np, pandas as pd

CATS = ["developer_tools", "ai_assistant_or_agent", "productivity", "marketing_sales", "design_creative", "finance",
        "health_fitness", "education", "social_communication", "data_analytics", "security_privacy", "other"]
AUD = ["developers", "designers", "marketers", "founders", "sales", "consumers", "students", "creators", "teams", "enterprises"]
PLAT = ["web", "ios", "android", "mac", "windows", "browser_extension", "api_sdk", "cli", "hardware"]
SCORES = ["value_clarity", "novelty", "breadth_of_appeal", "problem_urgency", "specificity"]
PRICE = ["free", "freemium", "paid", "not_stated"]; MAT = ["new_product", "major_update", "feature_update", "relaunch"]
BIN = ([f"cat_{c}" for c in CATS] + [f"aud_{a}" for a in AUD] + [f"mkt_{m}" for m in ("b2b", "b2c", "both")] + [f"plat_{p}" for p in PLAT]
       + ["ai_native", "open_source", "agent", "developer_tool"] + [f"price_{p}" for p in PRICE] + [f"mat_{m}" for m in MAT])
ALPHA = 5.0


class AttrFeats:
    def __init__(self, work):
        rows = {}
        for l in open(os.path.join(work, "product_attrs", "attrs_a.jsonl")):
            r = json.loads(l); a = r["attrs"]; v = dict.fromkeys(BIN, 0.0)
            v[f"cat_{a.get('category')}"] = 1.0
            for x in a.get("audience") or []:
                v[f"aud_{x}"] = 1.0
            v[f"mkt_{a.get('market')}"] = 1.0
            for x in a.get("platform") or []:
                v[f"plat_{x}"] = 1.0
            for b in ("ai_native", "open_source", "agent", "developer_tool"):
                v[b] = float(bool(a.get(b)))
            v[f"price_{a.get('pricing')}"] = 1.0; v[f"mat_{a.get('maturity')}"] = 1.0
            rows[r["id"]] = [v.get(b, 0.0) for b in BIN] + [float(a.get(s) or 3) for s in SCORES]
        self.cols = BIN + SCORES
        self.A = pd.DataFrame.from_dict(rows, orient="index", columns=self.cols)
        I = pd.read_parquet(os.path.join(work, "items.parquet")); I["id"] = I.id.astype(str)
        self.lday = dict(zip(I.id, I.day))
        self.daymean = self.A.join(I.set_index("id").day, how="inner").groupby("day")[self.cols].mean()
        E = pd.read_parquet(os.path.join(work, "events_cp.parquet")); E["item"] = E.item.astype(str)
        E = E[E.item.isin(self.A.index)]
        E["lday"] = E.item.map(self.lday)
        self.up = E[E.kind == "upvote"][["person", "item", "lday"]]
        self.act = E[["person", "date"]].assign(date=E.date.astype(str).str[:10]).drop_duplicates()
        self.emb = None
        ep = os.path.join(work, "product_attrs", "emb_fields.npz")
        if os.path.exists(ep):
            Z = np.load(ep); self.emb = ({str(i): k for k, i in enumerate(Z["ids"])}, Z["tag"], Z["desc"])
        self._cache = {}

    def prefs(self, d):
        if d in self._cache:
            return self._cache[d]
        cut = (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        U = self.up[self.up.lday <= cut]
        M = self.A.loc[U.item.values].set_axis(U.index)
        share = M.groupby(U.person.values).mean(); n = U.groupby("person").size()
        Ac = self.act[self.act.date <= cut]; Ac = Ac[Ac.date.isin(self.daymean.index)]
        base = self.daymean.loc[Ac.date.values].set_axis(Ac.index).groupby(Ac.person.values).mean()
        gbase = self.daymean[self.daymean.index <= cut].mean()
        base = base.reindex(share.index).fillna(gbase)
        nn = n.reindex(share.index).values[:, None]
        sh = (share[BIN].values * nn + ALPHA * base[BIN].values) / (nn + ALPHA)
        lift = pd.DataFrame(np.log((sh + 1e-3) / (base[BIN].values + 1e-3)), index=share.index, columns=BIN)
        gmean = self.A[SCORES].mean()
        sm = (share[SCORES].values * nn + ALPHA * gmean.values) / (nn + ALPHA)
        smean = pd.DataFrame(sm, index=share.index, columns=SCORES)
        cent = None
        if self.emb is not None:
            ix, T, Dv = self.emb; k = U.item.map(ix); ok = k.notna()
            kk = k[ok].astype(int).values; pp = U.person[ok].values
            tc = pd.DataFrame(T[kk], index=pp).groupby(level=0).mean(); dc = pd.DataFrame(Dv[kk], index=pp).groupby(level=0).mean()
            cent = (tc, dc)
        self._cache = {d: (lift, smean, cent)}   # one day at a time (memory)
        return self._cache[d]

    def add(self, X, d):
        """Adds the it9b columns to X (rows person x id for day d). Returns the new column names."""
        lift, smean, cent = self.prefs(d)
        ids = X.id.astype(str).values; La = self.A.reindex(ids)
        Lb = La[BIN].fillna(0).values; Ls = La[SCORES].fillna(3).values
        P = lift.reindex(X.person.values)
        Pl = P.fillna(0).values; has = P.notna().all(axis=1).values
        lb = Lb * Pl; cnt = Lb.sum(1).clip(min=1)
        new = {"at_lift_sum": lb.sum(1), "at_lift_max": np.where(Lb > 0, Pl, -9).max(1), "at_lift_mean": lb.sum(1) / cnt}
        ci = [BIN.index(f"cat_{c}") for c in CATS]; ai = [BIN.index(f"aud_{a}") for a in AUD]
        new["at_lift_cat"] = (Lb[:, ci] * Pl[:, ci]).sum(1)
        new["at_lift_aud"] = (Lb[:, ai] * Pl[:, ai]).sum(1) / Lb[:, ai].sum(1).clip(min=1)
        Sm = smean.reindex(X.person.values).fillna(self.A[SCORES].mean()).values
        for j, s in enumerate(SCORES):
            new[f"at_gap_{s}"] = np.abs(Ls[:, j] - Sm[:, j]); new[f"at_{s}"] = Ls[:, j]
        for p in PRICE:
            new[f"at_price_{p}"] = Lb[:, BIN.index(f"price_{p}")]
        for m in MAT:
            new[f"at_mat_{m}"] = Lb[:, BIN.index(f"mat_{m}")]
        new["at_ai"] = Lb[:, BIN.index("ai_native")]; new["at_os"] = Lb[:, BIN.index("open_source")]
        u = pd.Series(ids).drop_duplicates(); Lu = self.A.reindex(u.values)[BIN].fillna(0)
        share_day = Lu.mean()
        new["at_rare_cat"] = (Lb[:, ci] * share_day.values[ci]).sum(1)
        new["at_rare_aud"] = (Lb[:, ai] * share_day.values[ai]).sum(1) / Lb[:, ai].sum(1).clip(min=1)
        new["at_has_pref"] = has.astype(float)
        if cent is not None:
            ix, T, Dv = self.emb; k = pd.Series(ids).map(ix)
            for nm, M, C in (("tag", T, cent[0]), ("desc", Dv, cent[1])):
                Cm = C.reindex(X.person.values).values; ok = k.notna().values & ~np.isnan(Cm).any(1)
                v = np.full(len(X), np.nan)
                if ok.any():
                    a = M[k[ok].astype(int).values]; b = Cm[ok]
                    v[ok] = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)
                new[f"at_emb_{nm}"] = v
        for c, v in new.items():
            X[c] = v
        return list(new)
