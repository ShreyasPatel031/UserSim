import sys, runpy
sys.argv = ["maker_neutral.py"] + sys.argv[1:]
src = open("maker_neutral.py").read().split("# history from rank-neutral")[0]
exec(compile(src, "mn", "exec"))
rows = []
for i in DD.index:
    b, f, s = ident(i, CUTS["0005"]); h = L.hunter.iat[i]
    api_mk = [m for m in (json.loads(L.makers.iat[i]) if isinstance(L.makers.iat[i], str) and L.makers.iat[i].startswith("[") else [])]
    rows.append({"grp": L.grp.iat[i], "first_is_hunter": float(h in f) if f else np.nan, "hunter_badged": float(h in b), "n_nonhunter_badge_first": len((b | f) - {h}),
                 "api_self_hunted_named": float(any(pid(m) == h for m in api_mk if m and not str(m).startswith("[")))})
C = pd.DataFrame(rows); print(C.groupby("grp").mean().round(3).loc[["1", "2-3", "4-10", "11+"]].to_string())
