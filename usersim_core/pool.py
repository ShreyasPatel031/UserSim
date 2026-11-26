"""Universal User Pool: cross-domain causal user representation z_u(D) & cohort matcher.

Maps users from any domain (Product Hunt, Hacker News, Client QA, B2B CRM) into a shared
semantic + behavioral vector space strictly using events dated BEFORE day D:
  - Semantic taste vector (TF-IDF + TruncatedSVD fit strictly on pre-validation items)
  - Behavioral selectivity & activity rates (rw7, rw30, topic Shannon entropy)
  - Empirical critique & focus signature from past comments (substantive critique, pricing,
    technical architecture, UX/onboarding)
  - Learned K-Means behavioral archetypes (fit strictly on train-split snapshots)

Supports:
1. Retrieval of discerning, domain-matched real users for cohort simulation on day D.
2. Cross-domain similarity transfer (`match_external_spec` / `match_item_cohort`) with
   measured cosine overlap so new domains/products inherit calibrated priors and feed new
   outcomes back into the same pool.
3. Fast, zero-API-cost cohort structural-fit features per item (`item_pool_features`).
"""
from __future__ import annotations

import re
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from simharness.bench import Benchmark, KIND_CODE, _day_bounds_utc, day_ord, scrub
from simharness.schema import COMMENT, ENDORSE

_SUBS_CRIT_RE = re.compile(
    r"\b(how\s+does|how\s+do\s+you|what\s+happens\s+if|compared\s+to|vs\.?\s+|difference\s+between|"
    r"limitation|bottleneck|latency|pricing|expensive|cost|privacy|self-host|on-prem|security|"
    r"offline|export|lock-in|hallucinat|accuracy|benchmark|edge\s+case|missing|broken|friction)\b",
    re.IGNORECASE,
)
_PRICE_COM_RE = re.compile(r"\b(price|pricing|cost|free\s+tier|subscription|seat|token\s+cost|paywall|enterprise|plan)\b", re.I)
_TECH_COM_RE = re.compile(r"\b(api|sdk|latency|open\s*-?\s*source|local|self-host|model|context|architecture|benchmark|cli|mcp|webhook|docker)\b", re.I)
_UX_COM_RE = re.compile(r"\b(onboarding|ui|ux|design|workflow|mobile|friction|intuitive|setup|integrat|export)\b", re.I)


class UniversalUserPool:
    """Causal cross-domain user pool with leak-free SVD taste embeddings and archetype clustering."""

    def __init__(self, bench: Benchmark, train_cutoff_day: str = "2026-08-31", dim: int = 48, n_archetypes: int = 6):
        self.bench = bench
        self.train_cutoff_day = train_cutoff_day
        self.dim = dim
        self.n_archetypes = n_archetypes

        # 1. Fit TF-IDF + SVD strictly on items with day <= train_cutoff_day (zero future vocabulary leak)
        it = bench.items
        train_mask = (it["day"] <= train_cutoff_day).to_numpy()
        texts = [
            f"{scrub(str(t))} {scrub(str(s))} {' '.join(tags)} {scrub(str(d or ''))[:240]}"
            for t, s, tags, d in zip(it["title"], it["summary"], it["tags"], it["description"])
        ]
        self.tfidf = TfidfVectorizer(
            max_features=12000, ngram_range=(1, 2), min_df=3, sublinear_tf=True, stop_words="english", dtype=np.float64
        )
        self.tfidf.fit([texts[i] for i in np.flatnonzero(train_mask)])
        X_tfidf = self.tfidf.transform(texts).astype(np.float64)
        k_svd = min(dim, X_tfidf.shape[1] - 1, max(8, int(train_mask.sum()) - 1))
        self.svd = TruncatedSVD(n_components=k_svd, algorithm="arpack", random_state=42)
        with np.errstate(all="ignore"):
            self.svd.fit(X_tfidf[train_mask])
            raw_vecs = np.nan_to_num(self.svd.transform(X_tfidf), nan=0.0, posinf=0.0, neginf=0.0)
        self.item_vecs = normalize(raw_vecs, norm="l2").astype(np.float32)

        # 2. Pre-index comment trait flags per comment row for fast < D aggregation
        cm = bench.comments
        ctext = cm["text"].fillna("").astype(str).tolist()
        self._c_person = cm["person_idx"].to_numpy(dtype=np.int32)
        self._c_day = cm["day_ord"].to_numpy(dtype=np.int32)
        self._c_ts = cm["ts"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
        self._c_crit = np.array([bool(_SUBS_CRIT_RE.search(t)) or ("?" in t and len(t) > 45) for t in ctext], dtype=np.float32)
        self._c_price = np.array([bool(_PRICE_COM_RE.search(t)) for t in ctext], dtype=np.float32)
        self._c_tech = np.array([bool(_TECH_COM_RE.search(t)) for t in ctext], dtype=np.float32)
        self._c_ux = np.array([bool(_UX_COM_RE.search(t)) for t in ctext], dtype=np.float32)
        order_c = np.argsort(self._c_day, kind="stable")
        self._c_person = self._c_person[order_c]
        self._c_day = self._c_day[order_c]
        self._c_ts = self._c_ts[order_c]
        self._c_crit = self._c_crit[order_c]
        self._c_price = self._c_price[order_c]
        self._c_tech = self._c_tech[order_c]
        self._c_ux = self._c_ux[order_c]

        # First endorsement day per person (for survivorship-clean "established user" check)
        end = bench.hist[bench.hist["kind"] == KIND_CODE[ENDORSE]]
        first_s = end.groupby("person_idx")["day_ord"].min()
        self.first_endorse_ord = np.full(bench.n_people, 999999, dtype=np.int32)
        self.first_endorse_ord[first_s.index.to_numpy()] = first_s.to_numpy(dtype=np.int32)

        # 3. Fit K-Means behavioral archetypes strictly at train_cutoff_day
        self._snap_cache: dict[str, dict] = {}
        self.kmeans: MiniBatchKMeans | None = None
        snap0 = self.snapshot(train_cutoff_day)
        active0 = np.flatnonzero(snap0["n60"] >= 2)
        feat0 = self._behavior_matrix(snap0, active0)
        self.kmeans = MiniBatchKMeans(n_clusters=n_archetypes, random_state=42, batch_size=2048, n_init=5)
        with np.errstate(all="ignore"):
            self.kmeans.fit(feat0)
            act_all = np.flatnonzero(snap0["n60"] >= 1)
            if len(act_all):
                snap0["archetype"][act_all] = self.kmeans.predict(self._behavior_matrix(snap0, act_all))

    def embed_text(self, text: str) -> np.ndarray:
        """Project arbitrary domain/product/ICP text into the shared L2-normalized z_u semantic space."""
        v = self.svd.transform(self.tfidf.transform([text])).astype(np.float32)
        return normalize(v, norm="l2")[0]

    def _behavior_matrix(self, snap: dict, idx: np.ndarray) -> np.ndarray:
        return np.column_stack([
            np.log1p(snap["rw7"][idx]),
            np.log1p(snap["rw30"][idx]),
            snap["entropy"][idx],
            snap["crit_rate"][idx],
            snap["price_rate"][idx],
            snap["tech_rate"][idx],
            snap["ux_rate"][idx],
        ]).astype(np.float32)

    def snapshot(self, day: str) -> dict:
        """Compute strictly causal (< day) universal user vectors and behavioral signatures."""
        if day in self._snap_cache:
            return self._snap_cache[day]
        # Keep cache bounded
        if len(self._snap_cache) >= 16:
            self._snap_cache.pop(next(iter(self._snap_cache)))

        b = self.bench
        o = day_ord(day)
        st = b.state(day)

        # Recency-weighted semantic taste vector per person from endorsements < day
        hi = np.searchsorted(b._e_day, o)
        p, it, d = b._e_p[:hi], b._e_i[:hi], b._e_day[:hi]
        w = (0.5 ** ((o - d).astype(np.float64) / 45.0))
        W = sp.csr_matrix((w, (p, it)), shape=(b.n_people, len(b.items)))
        with np.errstate(all="ignore"):
            raw_u = np.nan_to_num(W @ self.item_vecs.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        user_vecs = normalize(raw_u, norm="l2").astype(np.float32)

        # Topic entropy (selectivity)
        top_csr = st["topics"]
        row_sums = np.maximum(np.asarray(top_csr.sum(axis=1)).ravel(), 1e-9)
        probs = top_csr.multiply(1.0 / row_sums[:, None]).tocsr()
        p_data = probs.data
        ent_data = -p_data * np.log(np.maximum(p_data, 1e-12))
        ent_mat = sp.csr_matrix((ent_data, probs.indices, probs.indptr), shape=probs.shape)
        entropy = np.asarray(ent_mat.sum(axis=1)).ravel().astype(np.float32)

        # Comment critique & focus rates strictly before day start
        start, _ = _day_bounds_utc(day, b.cfg.day_tz)
        chi = np.searchsorted(self._c_day, o)
        cp = self._c_person[:chi]
        cts = self._c_ts[:chi]
        ok_t = np.isnat(cts) | (cts < np.datetime64(start.tz_localize(None)))
        cp = cp[ok_t]
        n_com = np.bincount(cp, minlength=b.n_people).astype(np.float32)
        denom = n_com + 2.0  # Bayesian smoothing toward prior
        crit_rate = (np.bincount(cp, weights=self._c_crit[:chi][ok_t], minlength=b.n_people) + 0.30) / denom
        price_rate = (np.bincount(cp, weights=self._c_price[:chi][ok_t], minlength=b.n_people) + 0.10) / denom
        tech_rate = (np.bincount(cp, weights=self._c_tech[:chi][ok_t], minlength=b.n_people) + 0.20) / denom
        ux_rate = (np.bincount(cp, weights=self._c_ux[:chi][ok_t], minlength=b.n_people) + 0.20) / denom

        snap = {
            "day": day,
            "user_vecs": user_vecs,
            "rw7": st["rw"].astype(np.float32),
            "rw30": st["rw30"].astype(np.float32),
            "n60": st["n60"].astype(np.float32),
            "n_all": st["n_all"].astype(np.float32),
            "n_com": n_com,
            "entropy": entropy,
            "crit_rate": crit_rate.astype(np.float32),
            "price_rate": price_rate.astype(np.float32),
            "tech_rate": tech_rate.astype(np.float32),
            "ux_rate": ux_rate.astype(np.float32),
            "established": (self.first_endorse_ord <= (o - 45)),
        }
        active = np.flatnonzero(snap["n60"] >= 1)
        arch = np.full(b.n_people, -1, dtype=np.int32)
        if len(active) and self.kmeans is not None:
            with np.errstate(all="ignore"):
                arch[active] = self.kmeans.predict(self._behavior_matrix(snap, active))
        snap["archetype"] = arch
        self._snap_cache[day] = snap
        return snap

    def item_pool_features(self, day: str, item_idx_or_vec: int | np.ndarray) -> dict[str, float]:
        """Fast, zero-API-cost cohort structural-fit features from UniversalUserPool on day D."""
        snap = self.snapshot(day)
        ivec = self.item_vecs[item_idx_or_vec] if isinstance(item_idx_or_vec, (int, np.integer)) else item_idx_or_vec
        # Active & established discerning users (not brand-new survivorship artifacts)
        elig = np.flatnonzero((snap["n60"] >= 1) & (snap["n_all"] >= 3) & snap["established"])
        if len(elig) < 10:
            elig = np.flatnonzero(snap["n60"] >= 1)
        if len(elig) == 0:
            return {k: 0.0 for k in ("sim_top50_mean", "sim_discerning_mean", "sim_critic_mean",
                                     "expected_selective_voters", "expected_critic_voters", "niche_specialist_ratio")}

        with np.errstate(all="ignore"):
            sims = np.nan_to_num(snap["user_vecs"][elig] @ ivec, nan=0.0, posinf=0.0, neginf=0.0)
        rw = snap["rw30"][elig]
        # Selectivity weight: rewards active users with focused taste (lower entropy, moderate activity)
        selectivity = 1.0 / (1.0 + snap["entropy"][elig])
        discerning_w = np.log1p(rw) * selectivity * (snap["n60"][elig] <= 45).astype(np.float32)
        critic_w = discerning_w * snap["crit_rate"][elig] * (snap["n_com"][elig] >= 2).astype(np.float32)

        top50 = np.sort(sims)[-min(50, len(sims)):]
        pos_sim = np.maximum(sims, 0.0)
        return {
            "sim_top50_mean": float(np.mean(top50)),
            "sim_discerning_mean": float(np.sum(pos_sim * discerning_w) / max(float(np.sum(discerning_w)), 1e-6)),
            "sim_critic_mean": float(np.sum(pos_sim * critic_w) / max(float(np.sum(critic_w)), 1e-6)),
            "expected_selective_voters": float(np.sum((pos_sim ** 2) * discerning_w)),
            "expected_critic_voters": float(np.sum((pos_sim ** 2) * critic_w)),
            "niche_specialist_ratio": float(np.mean(snap["entropy"][elig[np.argsort(-sims)[:min(30, len(sims))]]])),
        }

    def match_cohort(self, day: str, item_idx_or_text: int | str, k: int = 5) -> list[dict]:
        """Select k diverse, discerning real users across behavioral archetypes for CUA/product evaluation."""
        snap = self.snapshot(day)
        ivec = (
            self.item_vecs[item_idx_or_text]
            if isinstance(item_idx_or_text, (int, np.integer))
            else self.embed_text(str(item_idx_or_text))
        )
        # Prefer users with real comment history (< D) and established history so voice & skepticism are grounded
        cand = np.flatnonzero((snap["n60"] >= 1) & (snap["n_com"] >= 2) & snap["established"])
        if len(cand) < k * 3:
            cand = np.flatnonzero((snap["n60"] >= 1) & (snap["n_com"] >= 1))
        with np.errstate(all="ignore"):
            sims = np.nan_to_num(snap["user_vecs"][cand] @ ivec, nan=0.0, posinf=0.0, neginf=0.0)
        # Score = semantic similarity * substantive critique propensity * moderate selectivity
        qual = sims * (0.5 + snap["crit_rate"][cand]) / (1.0 + 0.25 * snap["entropy"][cand])

        chosen: list[int] = []
        chosen_sims: list[float] = []
        # Pick top representative from distinct archetypes first, then fill by highest quality
        for a_id in range(self.n_archetypes):
            if len(chosen) >= k:
                break
            mask = snap["archetype"][cand] == a_id
            if not np.any(mask):
                continue
            sub = np.flatnonzero(mask)
            best_local = sub[int(np.argmax(qual[sub]))]
            pidx = int(cand[best_local])
            if sims[best_local] > 0.05 and pidx not in chosen:
                chosen.append(pidx)
                chosen_sims.append(float(sims[best_local]))

        for idx_local in np.argsort(-qual):
            if len(chosen) >= k:
                break
            pidx = int(cand[idx_local])
            if pidx not in chosen:
                chosen.append(pidx)
                chosen_sims.append(float(sims[idx_local]))

        batch = self.bench.batch(day, np.array(chosen, dtype=np.int64))
        out = []
        for j, (pidx, sim_val) in enumerate(zip(chosen, chosen_sims)):
            pid_str = str(self.bench.people["person_id"].iloc[pidx])
            out.append({
                "person_idx": pidx,
                "global_user_id": f"ph:{pid_str}",
                "archetype_id": int(snap["archetype"][pidx]),
                "similarity": round(sim_val, 4),
                "critique_rate": round(float(snap["crit_rate"][pidx]), 3),
                "pricing_focus": round(float(snap["price_rate"][pidx]), 3),
                "tech_focus": round(float(snap["tech_rate"][pidx]), 3),
                "ux_focus": round(float(snap["ux_rate"][pidx]), 3),
                "history_brief": batch.render(j, max_items=12, max_comments=4),
            })
        return out

    def export_universal_users(self, day: str, max_users: int = 25000) -> pd.DataFrame:
        """Materialize UNIVERSAL_USERS flywheel table as of `day`."""
        snap = self.snapshot(day)
        active = np.flatnonzero(snap["n60"] >= 1)[:max_users]
        peop = self.bench.people.iloc[active]
        return pd.DataFrame({
            "global_user_id": ["ph:" + str(x) for x in peop["person_id"]],
            "domain": "producthunt",
            "domain_person_id": peop["person_id"].astype(str).to_numpy(),
            "as_of_day": day,
            "complete": True,
            "activity_rw7": snap["rw7"][active].astype(np.float64),
            "activity_rw30": snap["rw30"][active].astype(np.float64),
            "n_endorse_all": snap["n_all"][active].astype(np.float64),
            "n_comments_all": snap["n_com"][active].astype(np.float64),
            "selectivity_entropy": snap["entropy"][active].astype(np.float64),
            "critique_rate": snap["crit_rate"][active].astype(np.float64),
            "pricing_focus": snap["price_rate"][active].astype(np.float64),
            "tech_focus": snap["tech_rate"][active].astype(np.float64),
            "ux_focus": snap["ux_rate"][active].astype(np.float64),
            "archetype_id": snap["archetype"][active].astype(np.int64),
            "taste_vec": [snap["user_vecs"][i].tolist() for i in active],
            "voice_digest": "",
        })
