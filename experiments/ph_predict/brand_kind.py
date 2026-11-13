"""D: split the Gemini brand score (orchestrator 20:24Z Nov 13). Picks with llm_brand >= 2 are right 47% vs 63%; a flat penalty did not
help. One Gemini 2.5 Flash call per day (listwise, blind to votes, same item text as the brand mode) classifies each launch:
  kind 0 = new company / new standalone product, 1 = NEW product from an already known company, 2 = update / new version / feature of an
  already established product. Output: <OUT>/<day>.json {id: kind}; then bk_feats -> parquet id, bk_newfromknown, bk_update for
history_retrain.py JOINT=1 JOINT_COLS=bk_newfromknown,bk_update (2025 rows missing).
usage (VM, from ph_predict): LLM_PROVIDER=gemini python brand_kind.py run [threads] | feats <out.parquet>"""
import json, os, re, sys, glob
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import features as F, llm as LL
OUT = os.path.expanduser(os.environ.get("BK_OUT", "~/w/h25/brand_kind"))
P = """Below are products launched on Product Hunt on {day}. For each, say what kind of launch it is, from what you knew BEFORE this
launch: 0 = a new company or a new standalone product (no established parent product or company you know of),
1 = a NEW product from a company you already knew, 2 = an update, new version, or new feature of a product that was already established.

{items}

Reply with JSON only: {{"<id>": <0|1|2>, ...}}"""


def run_day(day, g):
    fn = f"{OUT}/{day}.json"
    if os.path.exists(fn):
        return
    items = "\n".join(f"[{r.id}] {r['name']} — {r.tagline} (site: {r.domain or 'unknown'})" for _, r in g.iterrows())
    txt = LL.gemini_call(P.format(day=day, items=items), 20 * len(g) + 300)
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        res = {str(k): int(v) for k, v in json.loads(m.group(0)).items()}
    except Exception:  # noqa: BLE001
        print("bad json", day, flush=True); return
    json.dump(res, open(fn, "w")); print(day, len(res), flush=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if sys.argv[1] == "run":
        df = F.build(); days = sorted(df.day.unique(), reverse=True)
        with ThreadPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 4) as ex:
            list(ex.map(lambda d: run_day(d, df[df.day == d]), days))
        print("gemini tokens", LL.USAGE, "usd", round(LL.USAGE["in"] / 1e6 * 0.30 + LL.USAGE["out"] / 1e6 * 2.50, 3), flush=True)
    else:
        R = [(k, v) for fn in glob.glob(f"{OUT}/*.json") for k, v in json.load(open(fn)).items()]
        X = pd.DataFrame(R, columns=["id", "kind"]); X["bk_newfromknown"] = (X.kind == 1).astype(float); X["bk_update"] = (X.kind == 2).astype(float)
        X[["id", "bk_newfromknown", "bk_update"]].to_parquet(sys.argv[2]); print(len(X), X.kind.value_counts().to_dict())
