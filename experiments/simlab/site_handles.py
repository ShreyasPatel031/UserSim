"""Outside audience of the maker/company via handles found on the product's own website (orchestrator 01:45Z Nov 12).
Site captures with links (HTML): raw/ph_predict_data/sites.jsonl (keyed by launch id, live fetch ~Oct 28) and sites_today.jsonl.
raw/sites_ph.jsonl holds visible TEXT only (no hrefs) - used only for "@handle" mentions next to X/Twitter words.
Extracted per launch: X/Twitter handles (share/intent links and site-builder/platform handles excluded), Discord invite,
Telegram, YouTube, LinkedIn company page, GitHub org, Chrome Web Store, App Store, Play Store.
X follower reads joined by handle (case-insensitive) with their dates: tables_v2/profiles.parquet platform x (observed_on),
ph_predict_data/ext_x.jsonl (file written 2026-10-28; read date taken as <= Oct 28), Data Feeder x_fill (x_fetched_at, launch
day ~01:30 PT). A read is HONEST for a launch only if dated before the launch day (00:00 PT); later reads are a leaky upper bound.
Test: residual r = logv - honest LM (lm_breakout preds / honest_preds), within-day Spearman of log1p(max followers) with r on
days with >= 3 launches holding a read, pooled Spearman with day-demeaned r, and ridge(LM + log followers + has_read) vs LM
month-forward where enough rows exist.
    python site_handles.py <aud dir: sites.jsonl sites_today.jsonl sites_ph.jsonl ext_x.jsonl x_fill_*.json profiles.parquet> <launches dir> <honest_preds.parquet> <cf_rows.parquet> <out dir>
"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

A, LDIR, HON, CFR, OUT = sys.argv[1:6]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
BUILDER = {"framer", "framerapp", "webflow", "vercel", "wix", "squarespace", "shopify", "notionhq", "producthunt", "lovable_dev", "boltdotnew",
           "replit", "carrd", "durable", "hostinger", "wordpress", "ghost", "substack", "beehiiv", "mailchimp", "typeform", "tally_so", "calcom",
           "calendly", "stripe", "intercom", "crisp_chat", "hubspot", "x", "twitter", "share", "intent", "home", "i", "search", "hashtag", "explore",
           "login", "signup", "settings", "privacy", "tos", "about", "messages", "notifications", "elonmusk", "github", "google", "youtube", "linkedin",
           "supabase", "openai", "anthropicai", "figma", "canva", "zapier", "makehq", "n8n_io", "bubble", "softr_io", "glideapps", "tiiny_host", "netlify"}
RX = {"x": re.compile(r"(?:https?:)?//(?:www\.|mobile\.)?(?:twitter|x)\.com/(?!intent|share|home|i/|search|hashtag)([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])", re.I),
      "discord": re.compile(r"discord(?:\.gg|(?:app)?\.com/invite)/[A-Za-z0-9-]+", re.I), "telegram": re.compile(r"(?://|\b)t\.me/[A-Za-z0-9_+]+", re.I),
      "youtube": re.compile(r"youtube\.com/(?:@|c/|channel/|user/)[A-Za-z0-9_.-]+", re.I), "linkedin_company": re.compile(r"linkedin\.com/company/[A-Za-z0-9_.-]+", re.I),
      "github_org": re.compile(r"github\.com/(?!features|sponsors|login|about|pricing|topics|marketplace)[A-Za-z0-9-]+(?:/[A-Za-z0-9_.-]+)?", re.I),
      "chrome_store": re.compile(r"chrome(?:webstore)?\.google\.com/(?:webstore/)?detail/", re.I), "app_store": re.compile(r"apps\.apple\.com/", re.I),
      "play_store": re.compile(r"play\.google\.com/store/apps/details", re.I)}
TEXT_X = re.compile(r"(?:twitter|x\.com|follow us|on x)\W{0,20}@([A-Za-z0-9_]{2,15})", re.I)


def extract(html):
    out = {k: False for k in RX if k != "x"}; hs = []
    for m in RX["x"].finditer(html):
        h = m.group(1).lower()
        if h not in BUILDER and not h.isdigit(): hs.append(h)
    for k, rx in RX.items():
        if k != "x": out[k] = bool(rx.search(html))
    return sorted(set(hs)), out


site = {}
for f, key in (("sites.jsonl", "id"), ("sites_today.jsonl", "id")):
    p = os.path.join(A, f)
    if not os.path.exists(p): continue
    for line in open(p):
        x = json.loads(line)
        if x.get("html"): site[str(x[key])] = extract(x["html"])
held_text = {}
for line in open(os.path.join(A, "sites_ph.jsonl")):
    x = json.loads(line)
    if x.get("text"): held_text[str(x["id"])] = sorted({h.lower() for h in TEXT_X.findall(x["text"]) if h.lower() not in BUILDER})
L = pd.concat([pd.read_parquet(f) for f in glob.glob(os.path.join(LDIR, "*.parquet"))]).sort_values("updated_at").drop_duplicates("id", keep="last")
L = L[L.daily_rank.notna()].copy(); L["id"] = L.id.astype(str)
L["has_html"] = L.id.isin(site); L["handles"] = [sorted(set(site.get(i, ([], {}))[0]) | set(held_text.get(i, []))) for i in L.id]
for k in RX:
    if k != "x": L[k] = [site.get(i, ([], {}))[1].get(k, False) for i in L.id]
L["has_x"] = L.handles.str.len() > 0

# X reads with dates
reads = []
pr = pd.read_parquet(os.path.join(A, "profiles.parquet")); px = pr[(pr.platform == "x") & pr.followers.notna()]
reads += [(str(h).lower(), str(d)[:10], float(f), "profiles_x") for h, d, f in zip(px.handle, px.observed_on, px.followers)]
for line in open(os.path.join(A, "ext_x.jsonl")):
    x = json.loads(line)
    if x.get("followers") not in (None, "None"): reads.append((str(x["key"]).lower(), "2026-10-28", float(x["followers"]), "ext_x(<=Oct28)"))
for f in glob.glob(os.path.join(A, "x_fill_*.json")):
    for h, v in json.load(open(f)).items():
        if v.get("exists") and v.get("followers") is not None: reads.append((h.lower(), str(v.get("x_fetched_at", ""))[:10], float(v["followers"]), "x_fill(launch day)"))
R = pd.DataFrame(reads, columns=["h", "date", "followers", "src"]).sort_values("date")
byh = {h: g for h, g in R.groupby("h")}


def follow(handles, day):
    honest, leaky = [], []
    for h in handles:
        g = byh.get(h)
        if g is None: continue
        pre = g[g.date < day]; post = g[g.date >= day]
        if len(pre): honest.append(pre.followers.iloc[-1])
        if len(post): leaky.append(post.followers.iloc[0])
    return (max(honest) if honest else np.nan), (max(leaky) if leaky else np.nan)


ff = [follow(h, d) for h, d in zip(L.handles, L.day)]; L["f_honest"] = [a for a, _ in ff]; L["f_leaky"] = [b for _, b in ff]
days207 = sorted(pd.read_parquet(CFR).query("cut == 4").day.unique())[31:]
S = L[L.day.isin(days207)]
cov = {"launches_207_days": int(len(S)), "with_site_html": round(float(S.has_html.mean()), 3), "x_handle": round(float(S.has_x.mean()), 3),
       **{k: round(float(S[k].mean()), 3) for k in RX if k != "x"}}
top = S[S.daily_rank <= 3]; cov_top = {"top3_launches": int(len(top)), "x_handle": round(float(top.has_x.mean()), 3), **{k: round(float(top[k].mean()), 3) for k in RX if k != "x"}}
res = {"design": __doc__.split("\n    python")[0], "sources": {"sites.jsonl+sites_today (HTML, links)": len(site), "sites_ph.jsonl (text only)": len(held_text)},
       "coverage_207_days": cov, "coverage_top3": cov_top, "x_reads": R.src.value_counts().to_dict(), "x_read_handles": int(R.h.nunique())}
H = pd.read_parquet(HON).rename(columns={"base": "honest"})[["id", "honest", "logv"]]; H["id"] = H.id.astype(str)
M = L.merge(H, on="id", how="inner"); M["r"] = M.logv - M.honest
for lab, col in (("honest (read before launch day)", "f_honest"), ("LEAKY upper bound (read on/after launch day)", "f_leaky")):
    G = M[M[col].notna()].copy(); G["lf"] = np.log1p(G[col]); G["r_dm"] = G.r - G.day.map(M.groupby("day").r.mean())
    wd = [spearmanr(g.lf, g.r).correlation for _, g in G.groupby("day") if len(g) >= 3 and g.lf.nunique() > 1]
    out = {"launches_with_read": int(len(G)), "days": int(G.day.nunique()), "date_range": [G.day.min(), G.day.max()] if len(G) else None}
    if len(G) >= 10:
        bs = [spearmanr(G.lf.values[s], G.r_dm.values[s]).correlation for s in (rng.integers(0, len(G), len(G)) for _ in range(2000))]
        out["pooled_spearman_lf_vs_day_demeaned_r"] = [round(float(spearmanr(G.lf, G.r_dm).correlation), 3), round(float(np.nanpercentile(bs, 2.5)), 3), round(float(np.nanpercentile(bs, 97.5)), 3)]
        out["spearman_lf_vs_logv"] = round(float(spearmanr(G.lf, G.logv).correlation), 3); out["spearman_lf_vs_LM"] = round(float(spearmanr(G.lf, G.honest).correlation), 3)
    if len(wd) >= 3:
        wd = np.array(wd); bs = [wd[rng.integers(0, len(wd), len(wd))].mean() for _ in range(2000)]
        out["within_day_spearman_lf_vs_r"] = [round(float(wd.mean()), 3), round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3), int(len(wd))]
    res[lab] = out
last60 = L[(L.day >= "2026-09-12") & (L.day <= "2026-11-10")]
need = last60[last60.has_x & last60.f_honest.isna() & last60.f_leaky.isna()]
res["last_60_days"] = {"launches": int(len(last60)), "with_site_x_handle": int(last60.has_x.sum()), "with_handle_but_no_x_read": int(len(need)),
                       "unique_handles_to_read": int(len({h for hs in need.handles for h in hs}))}
pilot = sorted({h for hs in need.sort_values("day", ascending=False).handles for h in hs})[:500]
json.dump({"note": "X handles found on product websites (company/product or founder accounts linked from the site); launch ids alongside",
           "launches": [{"launch_id": i, "day": d, "handles": hs} for i, d, hs in zip(need.id, need.day, need.handles)][:800], "handles": pilot},
          open(os.path.join(OUT, "x_pilot_handles.json"), "w"), indent=0)
L[["id", "day", "daily_rank", "has_html", "has_x", "f_honest", "f_leaky"] + [k for k in RX if k != "x"]].to_parquet(os.path.join(OUT, "site_links.parquet"), index=False)
json.dump(res, open(os.path.join(OUT, "site_handles.json"), "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "design"}, indent=1, default=str))
