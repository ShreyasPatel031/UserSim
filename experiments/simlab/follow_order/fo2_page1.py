rng = __import__("numpy").random.default_rng(0)
exec(open(__import__("sys").argv[2]).read().split("f = E[(E.kind")[0])
F = E[E.kind == "follows"]; p1 = F[F.source == "ph_following_p1"]; P1 = set(zip(p1.person_id, p1.target_id)); ppl = set(p1.person_id)
full = F[F.person_id.isin(ppl)].drop_duplicates(["person_id", "target_id"]).copy(); full["in_p1"] = [(p, t) in P1 for p, t in zip(full.person_id, full.target_id)]
full["anc"] = [anc.get((p, t)) for p, t in zip(full.person_id, full.target_id)]; a = full[full.anc.notna()].copy()
print("people with a page-1 pull", len(ppl), "| their follow edges", len(full), "share on page 1", round(full.in_p1.mean(), 3), "| anchored edges", len(a), "on page 1", int(a.in_p1.sum()))
a["ad"] = pd.to_datetime(a.anc)
print("median anchor date page-1 vs rest:", a[a.in_p1].ad.median().date(), a[~a.in_p1].ad.median().date())
d = []
for p, g in a.groupby("person_id"):
    if g.in_p1.any() and (~g.in_p1).any(): d.append((g[g.in_p1].ad.mean() - g[~g.in_p1].ad.mean()).days)
d = np.array(d); bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)] if len(d) else [np.nan]
print("within-person (page-1 minus rest) mean anchor days", round(float(d.mean()), 1) if len(d) else None, np.percentile(bs, [2.5, 97.5]).round(1), "people", len(d))
print("page-1 anchored edges by month", a[a.in_p1].anc.str[:7].value_counts().sort_index().to_dict())
