"""Re-run only the rows whose allowed evidence changed after the leak fix, and merge into the saved runs."""

from __future__ import annotations

import json
import pickle
import sys

from human_sim import simbench_ablate as A

MODEL = "claude-haiku-4-5"
SUFFIX = {"eval": "", "dev": f"dev{A.DEV_POP}x{A.DEV_GROUPED}"}


def main(affected_path: str, arms: list[str]):
    affected = pickle.load(open(affected_path, "rb"))
    for which, ids in affected.items():
        sample, _, ctx = A.build_env(25, 100, 7, which)
        sub = sample.loc[sorted(ids)]
        for arm in arms:
            path = A.OUT_DIR / f"{arm}_{MODEL}_p25g100s7{SUFFIX[which]}.json"
            old = json.loads(path.read_text())
            new = A.run_arm(arm, sub, ctx, MODEL, 64)
            keep = [r for r in old["rows"] if r["i"] not in ids]
            old["rows"] = sorted(keep + new["rows"], key=lambda r: r["i"])
            old["ok"] = sum(1 for r in old["rows"] if r.get("ok"))
            old["fail"] = len(old["rows"]) - old["ok"]
            old["estimated_cost_usd"] = round(old["estimated_cost_usd"] + new["estimated_cost_usd"], 4)
            old["leak_fix_rerun_rows"] = sorted(int(i) for i in ids)
            path.write_text(json.dumps(old, indent=2))
            print(f"[{which}] {arm}: re-ran {len(ids)} rows, now ok={old['ok']}, +${new['estimated_cost_usd']:.3f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
