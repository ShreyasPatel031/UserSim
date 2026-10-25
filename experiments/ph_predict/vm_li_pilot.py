"""Runs on the VM, against the signed-in browser (debug port 9222). Pilot only: opens each LinkedIn profile from
pilot_li.json (commenters who link their own LinkedIn on Product Hunt) one at a time, ~20 s apart. Scrolls until the
page stops growing (sections load lazily), then saves the profile text plus its full experience and education pages to pilot_li_out.jsonl.
Approved by the account owner as a small test."""
import asyncio, json, random, sys
from playwright.async_api import async_playwright

SECTIONS_JS = """() => {
  const out = {};
  const top = document.querySelector('main section');
  if (top) out.top_card = top.innerText;
  for (const anchor of document.querySelectorAll('main section div[id]')) {
    const sec = anchor.closest('section');
    if (sec && anchor.id && !out[anchor.id]) out[anchor.id] = sec.innerText;
  }
  return out;
}"""


async def scroll_to_end(page):
    last = 0
    for _ in range(12):
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(1200)
        h = await page.evaluate("document.body.scrollHeight")
        if h == last:
            break
        last = h


async def main(path_in, path_out):
    people = json.load(open(path_in))
    async with async_playwright() as p:
        b = await asyncio.wait_for(p.chromium.connect_over_cdp("http://127.0.0.1:9222"), 60)
        ctx = b.contexts[0]
        with open(path_out, "a") as f:
            for person in people:
                rec = {"ph": person["ph"], "linkedin": person["linkedin"], "status": None, "sections": {}}
                for attempt in range(2):
                    page = await ctx.new_page()
                    try:
                        r = await page.goto(person["linkedin"], wait_until="domcontentloaded", timeout=90000)
                        rec["status"] = r.status if r else None
                        await page.wait_for_timeout(4000)
                        await scroll_to_end(page)
                        rec["final_url"] = page.url
                        rec["sections"] = {"main": await asyncio.wait_for(page.inner_text("main"), 30)}
                        await page.close()
                        base = person["linkedin"].rstrip("/")
                        for sub in ("experience", "education"):  # full lists live on their own pages
                            await asyncio.sleep(8 + random.random() * 6)
                            page = await ctx.new_page()
                            await page.goto(f"{base}/details/{sub}/", wait_until="domcontentloaded", timeout=90000)
                            await page.wait_for_timeout(4000)
                            await scroll_to_end(page)
                            rec["sections"][sub] = await asyncio.wait_for(page.inner_text("main"), 30)
                            await page.close()
                        rec.pop("error", None)
                        break
                    except Exception as e:  # noqa: BLE001
                        rec["error"] = str(e)[:200]
                        await page.close()
                        await asyncio.sleep(10)
                f.write(json.dumps(rec) + "\n"); f.flush()
                print(person["ph"], rec["status"], sorted(rec["sections"]), rec.get("error", ""), flush=True)
                await asyncio.sleep(18 + random.random() * 8)


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "/home/agent/php/pilot_li.json",
                 sys.argv[2] if len(sys.argv) > 2 else "/home/agent/php/pilot_li_out2.jsonl"))
