"""Static preview of the /ph board with the per-product hover card, in the site's own CSS (mvp/static/ph_site.css, Atelier design system).
    python mockup.py <cards json> <today_0005.json> <ph_site.css> <out.html>"""
import html, json, sys
CARDS, LINE, CSS, OUT = sys.argv[1:5]
J = json.load(open(CARDS)); line = {str(r["id"]): r for r in json.load(open(LINE))}; css = open(CSS).read()
e = html.escape
EXTRA = """
/* hover card: who backs it / up against / like vs dislike */
.row { position: relative; }
.hc { position: absolute; left: 100px; top: calc(100% - 6px); z-index: 20; width: min(440px, calc(100vw - 32px)); border: 1px solid var(--ink);
      background: var(--paper); padding: 16px 18px 14px; box-shadow: 6px 6px 0 var(--rule); display: none; }
.row:hover .hc, .row:focus-within .hc { display: block; }
.hc .label { margin-bottom: 8px; }
.hc section + section { border-top: 1px solid var(--rule); margin-top: 12px; padding-top: 12px; }
.grp { display: grid; grid-template-columns: minmax(0, 1fr) 44px; gap: 2px 10px; align-items: baseline; margin-bottom: 7px; }
.grp b { font: 600 14px/1.3 var(--sans); }
.grp span { font-size: 12px; color: var(--soft); text-align: right; }
.grp i { grid-column: 1 / -1; font-style: normal; font-size: 12.5px; color: var(--soft); line-height: 1.35; }
.grp .bar { grid-column: 1 / -1; height: 3px; background: var(--rule); }
.grp .bar > div { height: 3px; background: var(--ink); }
.vs { display: flex; flex-wrap: wrap; gap: 6px; }
.vs a { border: 1px solid var(--ink); padding: 2px 8px; font-size: 13px; text-decoration: none; }
.lines p { margin: 0 0 8px; display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 8px; font: 400 16px/1.35 var(--serif); }
.lines p em { font: 600 10px/1.9 var(--sans); letter-spacing: .08em; text-transform: uppercase; font-style: normal; color: var(--soft); }
.hc .fine { font-size: 11px; color: var(--faint); margin-top: 8px; }
@media (max-width: 720px) { .hc { left: 0; } }
"""
rows = []
for pos, lid in enumerate(J["order"], 1):
    c = J["cards"].get(lid) or {}; p = line.get(lid, {})
    if "groups" not in c: continue
    topics = [x["node"]["name"] for x in ((p.get("topics") or {}).get("edges") or [])][:3]
    groups = "".join(f'<div class="grp"><b>{e(g["name"] or "")}</b><span>{round(g["share"]*100)}%</span><i>{e(g["who"] or "")}</i>'
                     f'<div class="bar"><div style="width:{round(g["share"]*100)}%"></div></div></div>' for g in sorted(c["groups"], key=lambda g: -g["share"]))
    comps = "".join(f"<a>{e(x.strip())}</a>" for x in (c.get("competitors") or [])[:3])
    card = (f'<div class="hc" role="tooltip"><section><div class="label">Who will back it</div>{groups}</section>'
            f'<section><div class="label">Up against</div><div class="vs">{comps}</div></section>'
            f'<section class="lines"><p><em>Like</em>{e(c.get("like") or "")}</p><p><em>Push back</em>{e(c.get("dislike") or "")}</p>'
            f'<div class="fine">Groups of this launch\'s likely backers ({c["people_scored"] - c.get("no_profile_text", 0)} people with a profile). Lines are a model\'s read of similar launches\' comments, not real comments.</div></section></div>')
    rows.append(f'<li class="row" tabindex="0"><div class="pos">{pos}</div><div class="icon"><span>{e((c["name"] or "?")[0])}</span></div>'
                f'<div class="prod"><h3><a>{e(c["name"])}</a></h3><p>{e(p.get("tagline") or c.get("tagline") or "")}</p>'
                f'<div class="chips">{"".join(f"<span class=t>{e(t)}</span>" for t in topics)}</div></div>'
                f'<div class="vote"><div class="tri"></div><b>—</b></div>{card}</li>')
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hover card preview</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Baskervville:ital@0;1&family=Nunito+Sans:opsz,wght@6..12,300;6..12,400;6..12,600&display=swap">
<style>{css}{EXTRA}</style></head><body>
<div class="wrap"><nav class="top"><a class="mark">UserSim</a><div class="menu"><a aria-current="page">Today</a><a>Try a URL</a></div></nav>
<div class="head"><div class="copy"><div class="label">Preview · {e(J["day"])} · 00:05 forecast</div><h1>Today's launches</h1>
<p class="lede">Hover a launch to see who will back it, who it is up against, and what people will like or push back on.</p></div></div>
<ol class="board" style="padding-bottom:420px">{"".join(rows)}</ol></div></body></html>"""
open(OUT, "w").write(page); print(OUT, len(rows))
