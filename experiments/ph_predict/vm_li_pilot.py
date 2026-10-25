"""Runs on the VM, against the signed-in browser (debug port 9222). Pilot only: opens each LinkedIn profile from
pilot_li.json (commenters who link their own LinkedIn on Product Hunt) one at a time, ~20 s apart, and saves the
profile's visible text to pilot_li_out.jsonl. Approved by the account owner as a small test."""
import asyncio, json, random
from playwright.async_api import async_playwright


async def main():
    people = json.load(open("/home/agent/php/pilot_li.json"))
    async with async_playwright() as p:
        b = await asyncio.wait_for(p.chromium.connect_over_cdp("http://127.0.0.1:9222"), 60)
        ctx = b.contexts[0]
        with open("/home/agent/php/pilot_li_out.jsonl", "a") as f:
            for person in people:
                page = await ctx.new_page()
                rec = {"ph": person["ph"], "linkedin": person["linkedin"], "status": None, "text": ""}
                try:
                    r = await page.goto(person["linkedin"], wait_until="domcontentloaded", timeout=60000)
                    rec["status"] = r.status if r else None
                    await page.wait_for_timeout(5000)
                    await page.mouse.wheel(0, 2500)
                    await page.wait_for_timeout(3000)
                    rec["final_url"] = page.url
                    rec["text"] = (await asyncio.wait_for(page.inner_text("main"), 20))[:8000]
                except Exception as e:  # noqa: BLE001
                    rec["error"] = str(e)[:200]
                await page.close()
                f.write(json.dumps(rec) + "\n"); f.flush()
                print(person["ph"], rec["status"], len(rec["text"]), rec.get("error", ""), flush=True)
                await asyncio.sleep(18 + random.random() * 8)


asyncio.run(main())
