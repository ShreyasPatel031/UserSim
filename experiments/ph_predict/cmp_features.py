"""Compare each launch with its competitors (prefix cmp_). Competitors = the 5 nearest earlier Product Hunt launches by
meaning (name, tagline, description; data/emb.npz), launched at least 2 days before (their final votes are known by
launch day). For every Gemini page score (ps_) and watched-video score (vs_): the launch's score minus the competitors'
mean (cmp_gap_<score>), so "4.5 while its competitors are 4.8" is a negative gap. Plus how the competitors did:
  cmp_votes_mean / cmp_votes_max   log votes of the competitors
  cmp_beat_share                   share of competitors this launch beats on Gemini's overall top-5 chance
  cmp_sim_mean                     how close the competitors are (mean cosine)
usage: python cmp_features.py -> data/cmp_features.json"""
import glob, json, os
from datetime import date
import numpy as np

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main():
    day, votes = {}, {}
    for f in glob.glob(f"{D}/days/*.json"):
        for p in json.load(open(f)):
            day[str(p["id"])] = f[-15:-5]; votes[str(p["id"])] = p.get("votesCount") or 0
    ps = json.load(open(f"{D}/ps_features.json")); vs = json.load(open(f"{D}/vs_features.json"))
    keys_ps = sorted({k for v in ps.values() for k, x in v.items() if isinstance(x, (int, float)) and not k.startswith("ps_mix_")})
    keys_vs = sorted({k for v in vs.values() for k, x in v.items() if isinstance(x, (int, float))})
    Z = np.load(f"{D}/emb.npz"); ids = [str(x) for x in Z["launch_ids"]]
    V = Z["launch"] / np.linalg.norm(Z["launch"], axis=1, keepdims=True)
    od = np.array([date.fromisoformat(day[x]).toordinal() if x in day else 10**9 for x in ids])
    out = {}
    for k, x in enumerate(ids):
        if x not in day:
            continue
        s = V @ V[k]; s[od > od[k] - 2] = -9          # competitors launched at least 2 days before
        nb = [j for j in np.argsort(-s)[:5] if s[j] > -9]
        if not nb:
            continue
        c = [ids[j] for j in nb]; r = {"cmp_sim_mean": float(np.mean(s[nb])),
                                       "cmp_votes_mean": float(np.mean([np.log1p(votes.get(i, 0)) for i in c])),
                                       "cmp_votes_max": float(np.max([np.log1p(votes.get(i, 0)) for i in c]))}
        for src, keys in ((ps, keys_ps), (vs, keys_vs)):
            me = src.get(x, {})
            for key in keys:
                vals = [src[i][key] for i in c if i in src and isinstance(src[i].get(key), (int, float))]
                if vals and isinstance(me.get(key), (int, float)):
                    r["cmp_gap_" + key] = float(me[key] - np.mean(vals))
        t = ps.get(x, {}).get("ps_top5_chance")
        tv = [ps[i]["ps_top5_chance"] for i in c if isinstance(ps.get(i, {}).get("ps_top5_chance"), (int, float))]
        if isinstance(t, (int, float)) and tv:
            r["cmp_beat_share"] = float(np.mean([t > v for v in tv]))
        out[x] = r
    json.dump(out, open(f"{D}/cmp_features.json", "w"))
    print("launches", len(out), "inputs", len({k for v in out.values() for k in v}))


if __name__ == "__main__":
    main()
