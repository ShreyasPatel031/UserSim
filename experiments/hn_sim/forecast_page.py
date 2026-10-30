"""Render the published forecast page from forecast_live.py's latest.json (public story titles and aggregates only).

    python forecast_page.py <latest.json> <out.html>
"""
import html as H
import json
import sys

CSS = """
<title>HN Top 10 Forecast</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* layout: a ranked ledger. Odds bars carry the forecast; the backtest sits underneath as the receipt. */
:root{--bg:#f3f5f4;--panel:#ffffff;--ink:#16202a;--mute:#5f6b72;--rule:#d9dfdd;--accent:#0f7a6c;--bar:#cfe6e1;
--display:"Archivo",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11171b;--panel:#172027;--ink:#e6ecea;--mute:#93a1a6;--rule:#2a363d;--accent:#4cc3b0;--bar:#1f4a44;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11171b;--panel:#172027;--ink:#e6ecea;--mute:#93a1a6;--rule:#2a363d;--accent:#4cc3b0;--bar:#1f4a44;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:15px/1.5 var(--display);padding-block:28px 48px;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.wrap{max-width:1080px;margin:0 auto;display:grid;gap:28px}
h1{font-weight:800;font-size:clamp(26px,4vw,38px);letter-spacing:-.02em;margin:0;text-wrap:balance}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);margin:0 0 10px}
.lede{color:var(--mute);max-width:68ch;margin:6px 0 0}
.cols{display:grid;grid-template-columns:3fr 2fr;gap:28px}
@media (max-width:820px){.cols{grid-template-columns:1fr}}
.cols>section{min-width:0}
ol.ledger{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}
ol.ledger li{display:grid;grid-template-columns:2.2em 1fr 5.2em;gap:10px;padding:9px 0;border-bottom:1px solid var(--rule);align-items:start}
.rk{font:600 13px var(--mono);color:var(--mute);padding-top:2px;font-variant-numeric:tabular-nums}
.t a{color:var(--ink);text-decoration:none;font-weight:600}.t a:hover,.t a:focus-visible{color:var(--accent);text-decoration:underline}
.meta{font:12px var(--mono);color:var(--mute)}
.odds{text-align:right;font:600 14px var(--mono);font-variant-numeric:tabular-nums}
.bar{height:5px;background:var(--bar);border-radius:3px;margin-top:5px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent)}
.chip{display:inline-block;font:11px var(--mono);border:1px solid var(--rule);border-radius:3px;padding:0 4px;margin-left:6px;color:var(--mute)}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--rule)}th{font-size:12px;color:var(--mute);font-weight:600}
td.n{font-family:var(--mono);text-align:right}th.n{text-align:right}
.note{color:var(--mute);font-size:13px;max-width:75ch}
details summary{cursor:pointer;color:var(--accent);font-weight:600}
</style>
"""


def li(x):
    url = x["url"] or f"https://news.ycombinator.com/item?id={x['post_id']}"
    age = f"{x['age_min'] // 60}h {x['age_min'] % 60:02d}m old"
    pts = f" · {x['points_at_60']} pts at 60 min" if x.get("points_at_60") is not None else ""
    w = int(x["model"][1:]) if x["model"] != "post" else 0
    model = "post only" if not w else (f"first {w} min" if w < 120 else f"first {w // 60} h")
    return (f"<li><span class=rk>{x['rank']}</span><div class=t><a href='{H.escape(url)}' target=_blank rel=noopener>"
            f"{H.escape(x['title'])}</a><div class=meta>{H.escape(x['host'] or 'news.ycombinator.com')} · {age}{pts}"
            f"<span class=chip>{model}</span></div></div><div class=odds>{x['p_top10']:.0%}"
            f"<div class=bar><i style='width:{min(100, x['p_top10'] * 100):.0f}%'></i></div></div></li>")


def render(o: dict) -> str:
    days = sorted(o["days"])
    today, yday = o["days"][days[-1]], o["days"][days[0]]
    B = {(b["variant"], b["k"]): b for b in o["board"]}
    rows = "".join(f"<tr><td>{name}</td>" + "".join(f"<td class=n>{B[(v, k)]['recall']:.1%}</td>" for k in (100, 30, 10)) + "</tr>"
                   for v, name in [("post", "Post only (title, site, author, time)")] +
                   [(f"v{w}", f"+ first {w if w < 120 else w // 60} {'min' if w < 120 else 'h'} of comments, and who wrote them")
                    for w in (30, 60, 120, 240, 480)] if (v, 100) in B)
    rnd = o["model"]["random"]
    rows += "<tr><td>Random pick</td>" + "".join(f"<td class=n>{rnd[str(k)] if str(k) in rnd else rnd[k]:.1%}</td>" for k in (100, 30, 10)) + "</tr>"
    days_n = B[("v60", 100)]["days"]
    return CSS + f"""<div class=wrap>
<header><h1>Today's Hacker News top 10, forecast</h1>
<p class=lede>Which of today's {today['n_stories']} stories so far will finish in the day's top 10 by points (UTC day).
Updated {o['made_on'][:16].replace('T', ' ')} UTC, hourly. Odds are calibrated on {days_n} held-out days. An independent research forecast, not affiliated with Hacker News.</p></header>
<div class=cols>
<section><h2>Today, {days[-1]} · chance of top 10</h2><ol class=ledger>{''.join(li(x) for x in today['top'][:10])}</ol>
<details><summary>Ranks 11 to 30</summary><ol class=ledger>{''.join(li(x) for x in today['top'][10:30])}</ol></details></section>
<section><h2>Yesterday, {days[0]} · final forecast</h2><ol class=ledger>{''.join(li(x) for x in yday['top'][:10])}</ol></section>
</div>
<section><h2>How often it is right</h2><div class=tbl><table><tr><th>Forecast uses</th><th class=n>top 100 found</th>
<th class=n>top 30 found</th><th class=n>top 10 found</th></tr>{rows}</table></div>
<p class=note>Share of each day's real top 100 / 30 / 10 stories that the forecast's own top 100 / 30 / 10 contains,
averaged over {days_n} days ({o['model']['cal']}), with the model trained only on earlier days. A story is scored with
the richest model its age allows: post-only until it is 35 minutes old, then its first 30 minutes of comments, then its
first 60 minutes, 2, 4 and 8 hours (late bloomers). Votes are never an input. Points at 60 minutes are recorded live and shown for reference; they become a
model input once a few weeks of them exist.</p></section>
</div>"""


if __name__ == "__main__":
    open(sys.argv[2], "w").write(render(json.load(open(sys.argv[1]))))
