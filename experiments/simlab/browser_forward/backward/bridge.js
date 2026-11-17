// Browser bridge for the backward browser test: this container's own Chromium, driven by JSON lines on stdin.
// Safety: producthunt.com is never loaded; no typing; non-GET document navigations (form posts) are aborted; top-level navigation stays on the product's own site.
const { chromium } = require('playwright'); const readline = require('readline');
const reg = h => { const p = (h || '').toLowerCase().replace(/^www\./, '').split('.'); return p.slice(-2).join('.'); };
process.on('uncaughtException', e => process.stderr.write('UNCAUGHT ' + String(e && e.stack || e).slice(0, 400) + '\n'));
process.on('unhandledRejection', e => process.stderr.write('UNHANDLED ' + String(e && e.stack || e).slice(0, 400) + '\n'));
(async () => {
  const browser = await chromium.launch({ proxy: { server: process.env.HTTPS_PROXY || 'http://127.0.0.1:39215' }, args: ['--no-sandbox'] });
  browser.on('disconnected', () => process.exit(1));
  const cells = {}; const out = o => process.stdout.write(JSON.stringify(o) + '\n');
  async function open(id, url) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: false, userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36' });
    const c = { ctx, site: reg(new URL(url).hostname), errors: [], failed: [], notes: [], blocked: 0 }; cells[id] = c;
    await ctx.route('**/*', route => { try {
      const r = route.request(); let h = ''; try { h = new URL(r.url()).hostname.toLowerCase(); } catch (e) {}
      if (h.endsWith('producthunt.com')) { c.blocked++; return route.abort().catch(() => {}); }
      let main = false; if (r.isNavigationRequest()) { try { main = r.frame() === (c.page && c.page.mainFrame()); } catch (e) { main = true; } }
      if (main) {
        if (r.method() !== 'GET') { c.notes.push('a form submission was not sent (test rule)'); return route.abort().catch(() => {}); }
        if (reg(h) !== c.site) { c.notes.push('link leaves the product site to ' + h + ' (not followed)'); return route.abort().catch(() => {}); }
      }
      return route.continue().catch(() => {});
    } catch (e) { return route.continue().catch(() => {}); } });
    const hook = p => { p.on('console', m => { if (m.type() === 'error' && c.errors.length < 30) c.errors.push(m.text().slice(0, 160)); });
      p.on('pageerror', e => { if (c.errors.length < 30) c.errors.push(('JS error: ' + e.message).slice(0, 160)); });
      p.on('response', r => { try { const u = new URL(r.url()); if (r.status() >= 400 && reg(u.hostname) === c.site && c.failed.length < 30) c.failed.push(r.status() + ' ' + u.pathname.slice(0, 80)); } catch (e) {} }); };
    ctx.on('page', async p => { if (c.page && p !== c.page) { let h = ''; try { await p.waitForLoadState('domcontentloaded', { timeout: 8000 }); h = new URL(p.url()).hostname; } catch (e) {}
      if (h && reg(h) === c.site) { hook(p); c.page = p; c.notes.push('opened in a new tab'); } else { c.notes.push('link opens another site in a new tab: ' + (h || 'unknown') + ' (not followed)'); try { await p.close(); } catch (e) {} } } });
    c.page = await ctx.newPage(); hook(c.page);
    let status = null; try { const r = await c.page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }); status = r && r.status(); } catch (e) { c.notes.push('page did not load: ' + String(e.message).slice(0, 120)); }
    await c.page.waitForTimeout(2500); return status;
  }
  async function obs(id) {
    const c = cells[id], p = c.page; let els = [], title = '', text = '';
    try { title = await p.title(); els = await p.evaluate(() => { const o = []; const seen = new Set();
      for (const e of document.querySelectorAll('a,button,[role=button],[role=tab],[role=link],summary,input,select,textarea')) { const r = e.getBoundingClientRect(); if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        const s = getComputedStyle(e); if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
        const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.getAttribute('title') || '').trim().replace(/\s+/g, ' ').slice(0, 60); if (!t) continue;
        const k = t + '|' + Math.round(r.left / 10) + '|' + Math.round(r.top / 10); if (seen.has(k)) continue; seen.add(k);
        o.push({ t, tag: e.tagName.toLowerCase(), x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), href: (e.getAttribute && e.getAttribute('href') || '').slice(0, 90) || undefined }); if (o.length >= 70) break; }
      return o; });
      text = await p.evaluate(() => (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 1500)); } catch (e) { c.notes.push('could not read the page: ' + String(e.message).slice(0, 100)); }
    let shot = null; try { shot = (await p.screenshot({ type: 'jpeg', quality: 55, timeout: 15000 })).toString('base64'); } catch (e) {}
    let sy = 0, sh = 0; try { [sy, sh] = await p.evaluate(() => [Math.round(scrollY), document.documentElement.scrollHeight]); } catch (e) {}
    const o = { url: p.url(), title, scroll_y: sy, page_height: sh, elements: els, visible_text_start: text.slice(0, 600), console_errors: c.errors.splice(0), failed_requests: c.failed.splice(0), notes: c.notes.splice(0), shot }; return o;
  }
  async function act(id, a) {
    const c = cells[id], p = c.page;
    try {
      if (a.type === 'click') await p.mouse.click(+a.x, +a.y);
      else if (a.type === 'scroll') await p.mouse.wheel(0, +a.dy || 600);
      else if (a.type === 'back') await p.goBack({ timeout: 15000 }).catch(() => {});
      else if (a.type === 'wait') await p.waitForTimeout(Math.min(+a.ms || 1500, 4000));
      else if (a.type === 'navigate') { const u = new URL(a.url, p.url()); if (reg(u.hostname) !== c.site || !/^https?:$/.test(u.protocol)) c.notes.push('navigation refused: not the product site'); else await p.goto(u.href, { waitUntil: 'domcontentloaded', timeout: 30000 }); }
      else c.notes.push('action not allowed in this test: ' + a.type);
    } catch (e) { c.notes.push('action failed: ' + String(e.message).slice(0, 120)); }
    await p.waitForTimeout(1800);
  }
  const rl = readline.createInterface({ input: process.stdin });
  rl.on('line', async line => { let m; try { m = JSON.parse(line); } catch (e) { return; }
    try {
      if (m.op === 'open') { const st = await open(m.cell, m.url); out({ id: m.id, status: st, ...(await obs(m.cell)) }); }
      else if (m.op === 'act') { await act(m.cell, m.action); out({ id: m.id, ...(await obs(m.cell)) }); }
      else if (m.op === 'close') { const c = cells[m.cell]; const b = c ? c.blocked : 0; if (c) { try { await c.ctx.close(); } catch (e) {} delete cells[m.cell]; } out({ id: m.id, ok: true, ph_requests_blocked: b }); }
      else if (m.op === 'quit') { await browser.close(); process.exit(0); }
    } catch (e) { out({ id: m.id, error: String(e.message).slice(0, 200) }); } });
  out({ ready: true });
})();
