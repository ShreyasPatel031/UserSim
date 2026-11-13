"""Non-X outside-audience signals from the held site cache (orchestrator 02:34Z Nov 13; no Product Hunt requests; counts only).
Source: raw/sites_ph.jsonl = each launch's real website (PH redirect target) with the first 4,000 characters of VISIBLE TEXT only
(pipeline/sites.py keeps no links/HTML and no fetch time). Pages were fetched by pipeline.sites from Oct 31 2026 on (git history;
object written Nov 12), i.e. AFTER the launch day for every backtest launch (Apr-Oct) -> page content can include post-launch
additions ("Featured on Product Hunt", grown user counts). Flags are therefore text proxies for link types:
  github     'github' / 'star on github' / 'open source' in text, or the site itself on github.com / github.io
  extension  'chrome web store' / 'add to chrome' / 'chrome extension' / 'firefox add-on' / 'add to firefox'
  mobile     'app store' / 'google play' / 'download on the' / 'get it on' / 'testflight', or apps.apple.com / play.google.com
  discord    'discord'          newsletter  'newsletter' / 'substack' / 'subscribe'
  claims     'trusted by' / 'used by' / 'join N' / 'N+ users|customers|teams|companies|developers' (a number claim)
(1) coverage per type over the 214 backtest days; (2) types >= 10%: LODO ridge, base z(clean_nosite) + z(th_n_pre), + flag,
top 3/5/10, paired day bootstrap. usage: python site_signals.py -> results/site_signals.md"""
import json, os, re, subprocess, sys, tempfile
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
os.environ.setdefault("CF_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/cmt_v2")
import comment_forecast as CF
from early_forecast import B
from sklearn.linear_model import Ridge
NUM = r"\d[\d,.]*\s*(k|m|\+)?\+?"
PAT = {
    "github": re.compile(r"(?i)\bgithub\b|open[- ]source"),
    "extension": re.compile(r"(?i)chrome web store|add to chrome|chrome extension|firefox add-?on|add to firefox|browser extension"),
    "mobile": re.compile(r"(?i)app store|google play|download on the|get it on|testflight"),
    "discord": re.compile(r"(?i)\bdiscord\b"),
    "newsletter": re.compile(r"(?i)newsletter|substack|subscribe"),
    "claims": re.compile(r"(?i)trusted by|used by|loved by|join(ed)? (over )?" + NUM + r"|" + NUM + r"\s*(users|customers|teams|companies|developers|creators|businesses)"),
}
URLF = {"github": re.compile(r"(?i)//([^/]*\.)?(github\.com|github\.io)"), "mobile": re.compile(r"(?i)apps\.apple\.com|play\.google\.com"),
        "extension": re.compile(r"(?i)chromewebstore\.google\.com|chrome\.google\.com/webstore|addons\.mozilla\.org")}


def main():
    from pipeline import warehouse as W
    p = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")) + "/s.jsonl"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/raw/sites_ph.jsonl", p], check=True)
    S = {}
    for l in open(p):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if str(r.get("status")) != "200" or str(r.get("parked")) == "True":
            continue
        t, u = r.get("text") or "", r.get("url") or ""
        S[str(r["id"])] = {k: float(bool(PAT[k].search(t)) or bool(URLF[k].search(u) if k in URLF else False)) for k in PAT}
    L = W.query("SELECT CAST(id AS VARCHAR) id, slug, day, daily_rank, poster FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    L["poster"] = L.poster.fillna("").str.lower()
    T = pd.read_parquet(os.path.join(HERE, "results", "tw_nosite.parquet")); T["id"] = T.id.astype(str)
    X = L.merge(T[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id")
    X = X[(X.day >= "2026-04-01") & (X.day <= "2026-10-31")].copy()
    X["site"] = X.id.isin(S.keys()).astype(float)
    for k in PAT:
        X[k] = X.id.map({i: v[k] for i, v in S.items()}).fillna(0.0)
    K, _ = CF.load_comments(); K = K.merge(L[["slug", "id", "day", "poster"]], on="slug")
    K["t5"] = [pd.Timestamp(d + " 00:05", tz="America/Los_Angeles").tz_convert("UTC") for d in K.day]
    X["npre"] = X.id.map(K[(K.ts <= K.t5) & (K.user != K.poster)].groupby("id").user.nunique()).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ["clean", "npre", "site"] + list(PAT):
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    md = [f"# Site-cache audience signals ({len(days)} days Apr-Oct, {len(X)} ranked launches; text proxies; pages fetched Oct 31+ i.e. AFTER launch)", "",
          f"Site text held (status 200, not parked): {X.site.mean():.1%} of launches", "",
          "| type | coverage (all launches) | coverage (with site) | share in final top 10 | share in 11+ |", "|---|---|---|---|---|"]
    for k in PAT:
        hs = X[X.site == 1]
        md.append(f"| {k} | {X[k].mean():.1%} | {hs[k].mean():.1%} | {X[X.daily_rank <= 10][k].mean():.1%} | {X[X.daily_rank > 10][k].mean():.1%} |")
    def lodo(cols):
        o_ = []
        for d in days:
            te, tr = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(tr[cols], tr.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(o_)
    BASE = ["z_clean", "z_npre"]; base = lodo(BASE)
    md += ["", "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
           f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    keep = [k for k in PAT if X[k].mean() >= 0.10]
    for nm, cols in [(f"+ {k}", ["z_" + k, "z_site"]) for k in keep] + [("+ all >=10% types", ["z_" + k for k in keep] + ["z_site"])]:
        P = lodo(BASE + cols); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    open(os.path.join(HERE, "results", "site_signals.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
