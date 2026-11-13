"""Outside-audience pilot 2: website domains (orchestrator 02:02Z Nov 13). No Product Hunt requests; free public sources only.
Inputs: tmp/orchestrator/x_audience/launches_20261113.jsonl (launch_id, day, website_domain; 278 of 526 held, from the site cache).
  Tranco top-1M list 262W9 (daily list ending 2026-10-20, i.e. dated before Oct 26) -> in-list flag, log rank of the registrable domain.
  RDAP registration date (rdap.org bootstrap, 1 request per second, stop after 5 consecutive non-404 errors; cached) ->
  domain age in days at launch, registered < 90 days before launch.
Registrable domain: last two labels, or three for a built-in list of two-part public suffixes (co.uk, com.au, ...). Shared
hosts (vercel.app, github.io, notion.site, ...) are kept as their own group: no Tranco/RDAP meaning, reported separately.
Missing values: in_tranco 0, log rank = log(1e6 + 1), age -> day median with a has_age flag.
Leave-one-day-out ridge on Oct 26 - Nov 12: z(clean_nosite) + z(th_n_pre) vs + each; top 3/5/10, paired day bootstrap;
climber check (hidden rank 11-19 at 03:00 PT that end top 10).
usage: python domain_audience.py rdap   (fetch, background)   |   python domain_audience.py   -> results/domain_audience.md"""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from early_forecast import B
W_ = os.environ.get("DOM_WORK", "/tmp/claude-0/-home-user-UserSim/94f4f0ff-5cdc-5cbe-bb94-5c0d76cd2a8c/scratchpad/dom")
TWO = {"co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au", "co.nz", "co.in", "co.jp", "co.kr", "com.br", "com.mx", "com.ar",
       "com.cn", "com.tw", "com.hk", "com.sg", "com.tr", "co.za", "com.ng", "co.il", "com.my", "com.ph", "com.vn", "com.pk", "co.id",
       "com.ua", "com.co", "com.pe", "com.eg", "com.sa", "in.net", "eu.org", "us.com"}
SHARED = {"vercel.app", "github.io", "notion.site", "netlify.app", "pages.dev", "web.app", "firebaseapp.com", "herokuapp.com",
          "framer.website", "framer.ai", "framer.app", "webflow.io", "carrd.co", "super.site", "notion.so", "replit.app", "onrender.com",
          "streamlit.app", "gitbook.io", "substack.com", "medium.com", "bubbleapps.io", "softr.app", "glide.page", "wixsite.com",
          "lovable.app", "bolt.new", "typedream.app", "durable.co", "mystrikingly.com", "apps.apple.com", "apple.com", "chromewebstore.google.com",
          "google.com", "play.google.com", "github.com", "chrome.google.com", "huggingface.co", "x.com", "twitter.com", "linkedin.com",
          "youtube.com", "producthunt.com", "fly.dev", "up.railway.app", "railway.app", "netlify.com", "pages.github.com", "ghost.io",
          "beehiiv.com", "gumroad.com", "lemonsqueezy.com", "itch.io", "discord.com", "discord.gg", "t.me", "figma.com", "canva.site"}


def reg(host):
    h = host.lower().split(":")[0].strip(".")
    if h.startswith("www."):
        h = h[4:]
    for s in sorted(SHARED, key=len, reverse=True):
        if h == s or h.endswith("." + s):
            return h, s
    p = h.split(".")
    n = 3 if len(p) >= 3 and ".".join(p[-2:]) in TWO else 2
    return ".".join(p[-n:]), None


def launches():
    os.makedirs(W_, exist_ok=True); p = f"{W_}/launches.jsonl"
    subprocess.run(["gsutil", "-q", "cp", f"{B}/tmp/orchestrator/x_audience/launches_20261113.jsonl", p], check=True)
    L = pd.read_json(p, lines=True, dtype={"launch_id": str}); L["launch_id"] = L.launch_id.astype(str)
    r = [reg(d) if isinstance(d, str) and d else (None, None) for d in L.website_domain]
    L["rd"] = pd.Series([a for a, _ in r], dtype=object); L["shared"] = pd.Series([b for _, b in r], dtype=object)
    L["rd"] = L.rd.where(L.rd.notna(), None); L["shared"] = L.shared.where(L.shared.notna(), None)
    return L


def rdap():
    L = launches(); cp = f"{W_}/rdap.jsonl"
    done = {json.loads(l)["d"] for l in open(cp)} if os.path.exists(cp) else set()
    todo = sorted({d for d, s in zip(L.rd, L.shared) if d and not s} - done); err = 0
    print(json.dumps({"todo": len(todo), "cached": len(done)}), flush=True)
    for d in todo:
        rec = {"d": d, "status": None, "registered": None}
        try:
            req = urllib.request.Request(f"https://rdap.org/domain/{d}", headers={"Accept": "application/rdap+json", "User-Agent": "research-pilot"})
            j = json.load(urllib.request.urlopen(req, timeout=30)); rec["status"] = 200
            for e in j.get("events") or []:
                if e.get("eventAction") == "registration":
                    rec["registered"] = e.get("eventDate")
            err = 0
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            err = 0 if e.code == 404 else err + 1
        except Exception as e:
            rec["status"] = type(e).__name__; err += 1
        open(cp, "a").write(json.dumps(rec) + "\n")
        if err >= 5:
            print(json.dumps({"stopped": "5 consecutive errors", "last": rec}), flush=True); return
        time.sleep(1.0)
    print(json.dumps({"done": len(todo)}), flush=True)


def main():
    from sklearn.linear_model import Ridge
    from pipeline import warehouse as W
    import prior_blend as PB
    L = launches()
    tr = {}
    for l in open(f"{W_}/tranco.zip"):
        a, b = l.strip().split(",", 1); tr[b.lower()] = int(a)
    cp = f"{W_}/rdap.jsonl"; R = {}
    if os.path.exists(cp):
        for l in open(cp):
            r = json.loads(l)
            if r.get("registered"):
                R[r["d"]] = pd.Timestamp(r["registered"]).tz_convert(None) if pd.Timestamp(r["registered"]).tzinfo else pd.Timestamp(r["registered"])
    L["in_tr"] = [float(bool(d) and not s and d in tr) for d, s in zip(L.rd, L.shared)]
    L["lrank"] = [np.log(tr[d]) if (d and not s and d in tr) else np.log(1e6 + 1) for d, s in zip(L.rd, L.shared)]
    L["age"] = [(pd.Timestamp(dy) - R[d]).days if (d and not s and d in R) else np.nan for d, s, dy in zip(L.rd, L.shared, L.day.astype(str))]
    L["has_age"] = L.age.notna().astype(float); L["new90"] = ((L.age >= -1) & (L.age < 90)).astype(float)
    L["lage"] = np.log1p(L.age.clip(lower=0))
    L["has_dom"] = L.rd.notna().astype(float); L["is_shared"] = L.shared.notna().astype(float)
    Q = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL AND day >= '2026-10-26' AND day <= '2026-11-12'", do_sync=False)
    CL = pd.read_parquet(os.path.join(HERE, "results", "clean_live_rows_nosite.parquet")); CL["id"] = CL.id.astype(str)
    X = Q.merge(CL[["id", "clean_v3_nosite"]].rename(columns={"clean_v3_nosite": "clean"}), on="id").merge(
        L.rename(columns={"launch_id": "id"}).drop(columns=["day"]), on="id", how="left")
    X["lage"] = X.groupby("day").lage.transform(lambda s: s.fillna(s.median() if s.notna().any() else 0.0))
    for c in ("in_tr", "has_age", "new90", "has_dom", "is_shared"):
        X[c] = X[c].fillna(0.0)
    X["lrank"] = X.lrank.fillna(np.log(1e6 + 1))
    npre = {}
    for d in X.day.unique():
        E, _, _ = PB.thread(d, X[X.day == d].id.tolist()); npre.update(E.th_n_pre.to_dict())
    X["npre"] = X.id.map(npre).fillna(0)
    zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
    for c in ("clean", "npre", "in_tr", "lrank", "lage", "new90", "has_age", "has_dom", "is_shared"):
        X["z_" + c] = X.groupby("day")[c].transform(zf)
    X["y"] = X.groupby("day").daily_rank.transform(lambda s: zf(-np.log(s)))
    days = sorted(X.day.unique()); rng = np.random.default_rng(0)
    def lodo(cols):
        o_ = []
        for d in days:
            te, trn = X[X.day == d], X[X.day != d]; t = te.sort_values("daily_rank").id.tolist()
            o = te.assign(s=Ridge(alpha=3.0).fit(trn[cols], trn.y).predict(te[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist()
            o_.append([len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)])
        return np.array(o_)
    base = lodo(["z_clean", "z_npre"])
    held = X[X.has_dom == 1]; own = held[held.is_shared == 0]
    md = [f"# Domain audience pilot ({len(days)} days Oct 26 - Nov 12, {len(X)} ranked launches; Tranco list 262W9 ending 2026-10-20; RDAP read now)", "",
          f"Coverage: domain held {X.has_dom.mean():.1%}; shared hosts {int(held.is_shared.sum())} of {len(held)}; own domains {len(own)}: "
          f"in Tranco {own.in_tr.mean():.1%}, RDAP registration date {own.has_age.mean():.1%}, registered < 90 days before launch {own.new90.mean():.1%}", "",
          "| variant | top 3 | top 5 | top 10 | diff top 3 | diff top 5 | diff top 10 |", "|---|---|---|---|---|---|---|",
          f"| clean_nosite + th_n_pre | {base[:,0].mean():.1f} | {base[:,1].mean():.1f} | {base[:,2].mean():.1f} | - | - | - |"]
    for nm, cols in (("+ in Tranco", ["z_in_tr"]), ("+ log Tranco rank", ["z_lrank"]), ("+ domain age (log days)", ["z_lage", "z_has_age"]),
                     ("+ registered < 90 days", ["z_new90", "z_has_age"]), ("+ shared host / has domain", ["z_is_shared", "z_has_dom"]),
                     ("+ all domain features", ["z_in_tr", "z_lrank", "z_lage", "z_new90", "z_has_age", "z_is_shared", "z_has_dom"])):
        P = lodo(["z_clean", "z_npre"] + cols); dP = P - base; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(3000)])
        md.append(f"| {nm} | {P[:,0].mean():.1f} | {P[:,1].mean():.1f} | {P[:,2].mean():.1f} | " +
                  " | ".join(f"{dP[:,k].mean():+.1f} [{np.percentile(b[:,k],2.5):+.1f}, {np.percentile(b[:,k],97.5):+.1f}]" for k in range(3)) + " |")
    g = X.groupby("is_shared").daily_rank.agg(["size", "median"]); md += ["", "Final rank by host type (ranked launches with a held domain only): " +
          "; ".join(f"{'shared' if k else 'own'} n {int(r['size'])}, median rank {r['median']:.0f}" for k, r in g.iterrows() if k in (0, 1) and len(held))]
    V = W.query('SELECT "day" d, "at" a, CAST(launch_id AS VARCHAR) id, rank_now FROM vote_snapshots WHERE rank_now IS NOT NULL', do_sync=False)
    V["a"] = pd.to_datetime(V.a, utc=True); cl = []; XI = X.set_index("id")
    for d, gg in V.groupby("d"):
        t3 = pd.Timestamp(d + " 03:00", tz="America/Los_Angeles").tz_convert("UTC")
        for i, r in gg[gg.a <= t3].sort_values("a").groupby("id").rank_now.last().items():
            if 11 <= r <= 19 and i in XI.index:
                cl.append({"c": int(XI.daily_rank[i] <= 10), "in_tr": XI.in_tr[i], "new90": XI.new90[i], "has_age": XI.has_age[i], "shared": XI.is_shared[i]})
    C = pd.DataFrame(cl)
    if len(C):
        f = lambda s: f"{s.mean():.2f}" if len(s) else "-"
        md += ["", f"Climber check (hidden rank 11-19 at 03:00 PT, {len(C)} launches; ended top 10 n {int(C.c.sum())} vs not n {int((C.c == 0).sum())}): "
               f"in Tranco {f(C[C.c == 1].in_tr)} vs {f(C[C.c == 0].in_tr)}; registered < 90 days {f(C[C.c == 1].new90)} vs {f(C[C.c == 0].new90)}; "
               f"shared host {f(C[C.c == 1].shared)} vs {f(C[C.c == 0].shared)}"]
    open(os.path.join(HERE, "results", "domain_audience.md"), "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    rdap() if sys.argv[1:] == ["rdap"] else main()
