exec(open(__import__("sys").argv[2]).read().split("f = E[(E.kind")[0])
F = E[E.kind == "follows"]; p1 = set(zip(F[F.source == "ph_following_p1"].person_id, F[F.source == "ph_following_p1"].target_id))
CN = pd.read_parquet(f"{SP}/clean_nosite.parquet")[["id", "day"]]; CN["id"] = CN.id.astype(str); CN = CN[(CN.day >= "2026-10-26") & (CN.day <= "2026-11-11")]
fol_by_t = F.groupby("target_id").person_id.agg(set).to_dict(); tot, pre, lw = 0, 0, 0
for i, d in zip(CN.id, CN.day):
    fs = set().union(*[fol_by_t.get(m, set()) for m in team.get(i, ())]) if team.get(i) else set(); tot += len(fs)
    if d >= "2026-11-03":
        lw += len(fs); pre += sum(any((p, m) in p1 for m in team[i]) for p in fs)
print("held followers of launch teams Oct 26 - Nov 11:", tot, "| of those on Nov 3 - Nov 11 launches:", lw, "| provably before launch (in Nov 2 page-1 pull):", pre, f"({pre / max(1, lw):.1%})")
