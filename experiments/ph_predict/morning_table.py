"""Morning table for one finished day: every forward line's top 3 / 5 / 10 against the official dailyRank (all featured launches, no
'known' exclusions; truth top k = launches with daily_rank <= k). Reads the day's files from the bucket: early_forecast/<d>_*.json,
velocity_shadow/<d>_*.json, shadow_makerfix / shadow_h25 / shadow_readable/<d>.json. Every column named pred_rank* / rank_* is scored.
usage: python morning_table.py <YYYY-MM-DD> -> results/morning/<d>.md"""
import json, os, subprocess, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [os.path.dirname(HERE), HERE]
B = "gs://usersim-bakeoff-347838016394/usersim_sim/results"
from pipeline import warehouse as W


def main(d):
    L = W.query(f"SELECT CAST(id AS VARCHAR) id, daily_rank FROM launches WHERE day='{d}' AND daily_rank IS NOT NULL", do_sync=False)
    r = L.daily_rank.astype(int).tolist(); ok = sorted(r)[:10] == list(range(1, 11)) and len(r) == len(set(r))
    tr = {k: set(L[L.daily_rank <= k].id) for k in (3, 5, 10)}
    ls = subprocess.run(["gsutil", "ls", f"{B}/early_forecast/{d}_*.json", f"{B}/velocity_shadow/{d}_*.json", f"{B}/shadow_makerfix/{d}.json",
                         f"{B}/shadow_h25/{d}.json", f"{B}/shadow_readable/{d}.json"], capture_output=True, text=True).stdout.split()
    rows = []
    for p in ls:
        j = json.loads(subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout)
        F = pd.DataFrame(j.get("forecast") or j.get("launches") or [])
        if F.empty or "id" not in F:
            continue
        F["id"] = F.id.astype(str); src = p.split("/results/")[1]
        for c in [c for c in F.columns if c.startswith(("pred_rank", "rank_"))]:
            s = F.dropna(subset=[c]).sort_values([c, "id"])
            if len(s) < 10:
                continue
            o = s.id.tolist()
            rows.append({"file": src, "line": c, "n": len(s)} | {f"t{k}": round(len(set(o[:k]) & tr[k]) / k * 100, 1) for k in (3, 5, 10)})
    T = pd.DataFrame(rows)
    md = [f"# Morning table {d}", "", f"Scoring: official dailyRank top k over all featured launches ({len(r)} ranked), no 'known' exclusions. "
          f"Ranks 1-10 present, contiguous, no duplicates: {'yes' if ok else 'NO'}.", "",
          "| file | line | launches | top 3 | top 5 | top 10 |", "|---|---|---|---|---|---|"]
    md += [f"| {x.file} | {x.line} | {x.n} | {x.t3} | {x.t5} | {x.t10} |" for x in T.itertuples()]
    os.makedirs(f"{HERE}/results/morning", exist_ok=True); open(f"{HERE}/results/morning/{d}.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md[:4])); print(len(T), "lines scored")


if __name__ == "__main__":
    main(sys.argv[1])
