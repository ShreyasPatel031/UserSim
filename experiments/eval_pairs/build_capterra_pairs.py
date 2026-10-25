"""Same-person A-vs-B eval pairs from Capterra's "Switched from" field.

Each switch is one reviewer who used product A, moved to product B, and reviewed B on Capterra. For every pair of
products in the snapshot, count switches in each direction; a pair is usable when at least MIN_N people switched
and one direction holds at least MIN_SHARE of them. The winner is the product people switched *to*.

Reasons for switching are tagged by keyword (not an LLM), so price-driven switches can be dropped:
`winner_no_price` / `share_no_price` recompute the pair from switches whose reason does not mention price.

Outputs (in this folder):
  capterra_pairs.csv     one row per usable pair
  capterra_switches.csv  one row per switch between two snapshot products, with reason text and tags

    python experiments/eval_pairs/build_capterra_pairs.py
"""

from __future__ import annotations

import re
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"  # raw download (gitignored)
# Same pinned snapshot as experiments/staged_context/experiment.py
DATASET_URL = ("https://huggingface.co/datasets/FreshCrawl/capterra-b2b-software-reviews/resolve/"
               "fc7c316cae049cd9e445241b280209a2a140ed4c/capterra_software_reviews.csv")
MIN_N, MIN_SHARE = 10, 0.7

# Keyword tags on "Reasons for switching"; a switch can carry several.
REASON_TAGS = {
    "price": r"\b(price|pricing|priced|cost|costs|costly|cheap|cheaper|expensive|afford|budget|fee|fees|free|"
             r"subscription|\$|money|value)\b",
    "ease": r"\b(easy|easier|easiest|ease|simple|simpler|intuitive|user[- ]friendly|usability|learning curve|"
            r"complicated|complex|clunky|confusing|cumbersome|hard|difficult|interface|ui|ux)\b",
    "outgrew": r"\b(outgr[eo]w\w*|grow\w*|grew|scal\w*|bigger|larger|enterprise)\b",
    "features": r"\b(feature|features|functionality|functionalities|capabilit\w*|automation\w*|tools?|options?|"
                r"limited|lacked|lacking|missing)\b",
    "integration": r"\b(integrat\w*|api|sync\w*|connect\w*|ecosystem|plugin\w*|zapier)\b",
    "support": r"\b(support|customer service|help ?desk|response time|responsive)\b",
    "performance": r"\b(slow|slower|speed|fast|faster|lag\w*|crash\w*|bug\w*|reliab\w*|stable|stability|"
                   r"downtime|outage\w*|glitch\w*)\b",
    "company_mandate": r"\b(company|management|employer|boss|corporate|it department|organization|organisation)"
                       r" (decided|chose|switched|moved|mandated|required|wanted)\b|\b(acquired|merger|migrated us)\b",
}
REASON_RE = {k: re.compile(v, re.I) for k, v in REASON_TAGS.items()}

# Public homepages: the simulator's input for each product.
URLS = {
    "1Password": "https://1password.com/", "ActiveCampaign": "https://www.activecampaign.com/",
    "Adobe Creative Cloud": "https://www.adobe.com/creativecloud.html", "Asana": "https://asana.com/",
    "BambooHR": "https://www.bamboohr.com/", "Basecamp": "https://basecamp.com/",
    "BigCommerce": "https://www.bigcommerce.com/", "Brevo": "https://www.brevo.com/", "Canva": "https://www.canva.com/",
    "ClickUp": "https://clickup.com/", "Cloudflare": "https://www.cloudflare.com/",
    "Constant Contact": "https://www.constantcontact.com/", "CrowdStrike": "https://www.crowdstrike.com/",
    "Deel": "https://www.deel.com/", "Domo": "https://www.domo.com/", "Figma": "https://www.figma.com/",
    "FreshBooks": "https://www.freshbooks.com/", "Freshdesk": "https://www.freshworks.com/freshdesk/",
    "Freshsales": "https://www.freshworks.com/crm/sales/", "GitHub": "https://github.com/",
    "GitLab": "https://about.gitlab.com/", "GMS Accounting and Financial Management Reporting System": "",
    "Google Analytics 360": "https://marketingplatform.google.com/about/analytics-360/",
    "Google Workspace": "https://workspace.google.com/", "Gusto": "https://gusto.com/",
    "Help Scout": "https://www.helpscout.com/", "HubSpot CRM": "https://www.hubspot.com/products/crm",
    "Insightly": "https://www.insightly.com/", "Intercom": "https://www.intercom.com/", "Jira": "https://www.atlassian.com/software/jira",
    "Klaviyo": "https://www.klaviyo.com/", "LastPass": "https://www.lastpass.com/", "LiveAgent": "https://www.liveagent.com/",
    "Looker": "https://cloud.google.com/looker", "Mailchimp": "https://mailchimp.com/",
    "Marketo Engage": "https://business.adobe.com/products/marketo.html", "Microsoft Power BI": "https://www.microsoft.com/power-platform/products/power-bi",
    "Microsoft Teams": "https://www.microsoft.com/microsoft-teams", "monday.com AI Work Platform": "https://monday.com/",
    "Namely": "https://www.namely.com/", "NetSuite": "https://www.netsuite.com/", "Netskope Active Platform": "https://www.netskope.com/",
    "Notion": "https://www.notion.com/", "Okta": "https://www.okta.com/", "Pipedrive": "https://www.pipedrive.com/",
    "QuickBooks Online": "https://quickbooks.intuit.com/online/", "RingCentral Events": "https://www.ringcentral.com/events.html",
    "Rippling": "https://www.rippling.com/", "Sage Intacct": "https://www.sage.com/en-us/sage-business-cloud/intacct/",
    "Salesforce Sales Cloud": "https://www.salesforce.com/sales/", "Shopify": "https://www.shopify.com/",
    "Slack": "https://slack.com/", "Smartsheet": "https://www.smartsheet.com/", "Squarespace": "https://www.squarespace.com/",
    "Tableau": "https://www.tableau.com/", "Trello": "https://trello.com/", "Webex Suite": "https://www.webex.com/",
    "Wix": "https://www.wix.com/", "WooCommerce": "https://woocommerce.com/", "Workday HCM": "https://www.workday.com/",
    "Wrike": "https://www.wrike.com/", "Xero": "https://www.xero.com/", "Zendesk Suite": "https://www.zendesk.com/",
    "Zoho CRM": "https://www.zoho.com/crm/", "Zoho Desk": "https://www.zoho.com/desk/", "Zoom Workplace": "https://www.zoom.com/",
}


def load() -> pd.DataFrame:
    path = CACHE / "capterra_software_reviews.csv"
    if not path.exists():
        CACHE.mkdir(exist_ok=True)
        urllib.request.urlretrieve(DATASET_URL, path)
    return pd.read_csv(path)


def switches(d: pd.DataFrame) -> pd.DataFrame:
    """One row per (reviewer, product they left) where both products are in the snapshot."""
    by_name = {n.strip().lower(): n for n in d.product_name.unique()}
    rows = []
    for r in d[d.switched_from.notna()].itertuples():
        for left in str(r.switched_from).split("|"):
            src = by_name.get(left.strip().lower())
            if not src or src == r.product_name:
                continue
            reason = r.reasons_for_switching if isinstance(r.reasons_for_switching, str) else ""
            tags = [k for k, rx in REASON_RE.items() if reason and rx.search(reason)]
            rows.append({"review_id": r.review_id, "category": r.product_category_group, "from_product": src,
                         "to_product": r.product_name, "review_date": r.review_date, "overall_rating": r.overall_rating,
                         "reviewer_company_size": r.reviewer_company_size, "reviewer_job_title": r.reviewer_job_title,
                         "has_reason": bool(reason), "reason_tags": "|".join(tags), "reasons_for_switching": reason,
                         "review_url": r.review_url})
    return pd.DataFrame(rows)


def _winner(c: Counter, a: str, b: str) -> tuple[str, float, int]:
    n = c[(a, b)] + c[(b, a)]  # (from, to)
    if not n:
        return "", 0.0, 0
    win = b if c[(a, b)] >= c[(b, a)] else a
    return win, round(max(c[(a, b)], c[(b, a)]) / n, 3), n


def pairs(s: pd.DataFrame, category: dict[str, str]) -> pd.DataFrame:
    is_price = s.reason_tags.str.contains(r"\bprice\b", regex=True)
    all_c = Counter(zip(s.from_product, s.to_product))
    np_c = Counter(zip(s[~is_price].from_product, s[~is_price].to_product))
    tag_c: dict[frozenset, Counter] = {}
    for r in s.itertuples():
        tc = tag_c.setdefault(frozenset((r.from_product, r.to_product)), Counter())
        tc.update(t for t in r.reason_tags.split("|") if t)
    rows = []
    for a, b in sorted({tuple(sorted(k)) for k in all_c}):
        win, share, n = _winner(all_c, a, b)
        if n < MIN_N or share < MIN_SHARE:
            continue
        win_np, share_np, n_np = _winner(np_c, a, b)
        lose = a if win == b else b
        tags = tag_c[frozenset((a, b))]
        rows.append({"category": category[win], "product_a": a, "url_a": URLS.get(a, ""), "product_b": b,
                     "url_b": URLS.get(b, ""), "a_to_b": all_c[(a, b)], "b_to_a": all_c[(b, a)], "n_switches": n,
                     "winner": win, "loser": lose, "winner_share": share,
                     "n_no_price": n_np, "winner_no_price": win_np, "share_no_price": share_np,
                     "winner_holds_without_price": bool(n_np >= MIN_N and win_np == win and share_np >= MIN_SHARE),
                     "same_category": category[a] == category[b],
                     **{f"reason_{k}": tags[k] for k in REASON_TAGS}})
    return pd.DataFrame(rows).sort_values(["category", "n_switches"], ascending=[True, False])


def main() -> None:
    d = load()
    s = switches(d)
    category = d.groupby("product_name").product_category_group.first().to_dict()
    p = pairs(s, category)
    s.to_csv(HERE / "capterra_switches.csv", index=False)
    p.to_csv(HERE / "capterra_pairs.csv", index=False)
    print(f"{len(s)} switches between snapshot products, {s.has_reason.mean():.0%} with a reason")
    print(f"{len(p)} pairs (n>={MIN_N}, share>={MIN_SHARE}); {p.winner_holds_without_price.sum()} hold without "
          f"price-tagged switches; {(~p.same_category).sum()} cross-category")


if __name__ == "__main__":
    main()
