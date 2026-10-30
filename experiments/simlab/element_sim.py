"""One launch, every simulated person, and how each part of the launch page moved that person's chance of upvoting.
The taste person model (popscore TASTE=1, trained on the month before) scores everyone in the day's 30-day pool; its
per-input contributions (LightGBM pred_contrib, log-odds) are summed by page element:
  name, tagline, description, first comment, website, video, images (logo, gallery), overall (clarity, novelty, ...),
  page facts (free plan, open source, ...), and "not the page" (team ties, history, category, meaning)
Each person's taste match on a page trait (tx_<trait>) counts towards that trait's element. A contribution is shown as
the change in that person's pick chance if the element's push were removed. Also prints Gemini's raw page output for
the launch and the Gemini persona ratings of these people for it, where they exist.
usage: TASTE=1 python -m simlab.element_sim <launch_id> [n_people] -> reports/element_sim_<id>.json"""
import json, os, pickle, sys
import numpy as np, pandas as pd
from . import choice, popscore as PS
from .page_taste import traits

HERE = os.path.dirname(os.path.abspath(__file__)); PH = os.path.join(os.path.dirname(HERE), "ph_predict")
ELEMENTS = {"name": ["name", "name_len"], "tagline": ["tagline", "tagline_style", "number_in_tagline", "ai_in_tagline", "tagline_words", "tagline_len"],
            "description": ["description", "desc_len", "features_listed", "how_it_works", "problem_stated", "who_its_for"],
            "first comment": ["first_comment", "founder_story", "asks_for", "emoji_in_first"],
            "website": ["website", "web_", "dom_"], "video": ["video", "vs_", "has_video"], "images": ["logo", "gallery", "n_images", "n_media", "visual_polish"],
            "overall": ["clarity", "novelty", "usefulness", "audience_breadth", "credibility", "problem_urgency", "wow", "top5_chance", "category_fit", "mix_"],
            "page facts": ["free_plan", "free_trial", "paid_only", "open_source", "mac_app", "mobile_app", "browser_extension", "no_signup", "b2b", "consumer",
                           "developer_tool", "api_or_sdk", "agent", "hardware", "games", "price_point", "social_proof", "integrations", "claims_",
                           "launch_discount", "relaunch", "waitlist", "audience_", "mentions_competitor"]}


def element(col, page_cols):
    if col in ("taste_dot", "taste_cos", "taste_n"):
        return "overall"
    base = col[3:] if col.startswith("tx_") else col
    if base not in page_cols and not col.startswith("tx_"):
        return "not the page"
    b = base.split("_", 1)[1] if base[:3] in ("ps_", "pf_", "vs_") else base
    for e, keys in ELEMENTS.items():
        if any(k in base if k.endswith("_") else k in b for k in keys):
            return e
    return "overall"


def main(x, n_people):
    PS.load(); traits()
    g = PS.load(); I = g["I"].set_index("id"); E = g["E"]
    d = I.loc[x, "day"]; art = pickle.load(open(f"{PS.WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    D = PS.featurize(D, art["cf"], art["prior_cut"]); D, pc = PS.page_cols(D)
    cols = PS.FEATS + pc
    D = D[D.id == x].reset_index(drop=True)
    X = D[cols]
    D["p"] = art["model"].predict_proba(X)[:, 1]
    C = art["model"].booster_.predict(X, pred_contrib=True)   # last column = bias
    page_cols = set(c for c in pc if not c.startswith(("tx_", "taste_")))
    groups = {}
    for k, c in enumerate(cols):
        groups.setdefault(element(c, page_cols), []).append(k)
    logit = np.log(D.p / (1 - D.p))
    for e, ks in groups.items():
        push = C[:, ks].sum(1)
        D["d_" + e] = D.p - 1 / (1 + np.exp(-(logit - push)))   # change in pick chance from this element
    D = D.sort_values("p", ascending=False).reset_index(drop=True)
    voted = set(E[(E.item.astype(str) == x) & (E.kind == "upvote")].person)
    ps = {json.loads(l)["id"]: json.loads(l) for l in open(f"{PH}/data/page_scores.jsonl")}.get(x, {})
    pr = {}
    try:
        from pipeline import warehouse as W
        R = W.connect(do_sync=False).execute(f"SELECT person, design, rating FROM persona_ratings WHERE launch_id = '{x}'").df()
        pr = {u: dict(zip(gg.design, gg.rating)) for u, gg in R.groupby("person")}
    except Exception as e:  # noqa: BLE001
        pr = {"_error": str(e)[:100]}
    els = ["name", "tagline", "description", "first comment", "website", "video", "images", "overall", "page facts", "not the page"]
    people = []
    for r in D.head(n_people).itertuples():
        people.append({"person": r.person, "pick_chance": round(float(r.p), 3), "really_voted": r.person in voted,
                       "element_push": {e: round(float(D.loc[r.Index, "d_" + e]), 4) for e in els if "d_" + e in D},
                       "gemini_persona": pr.get(r.person)})
    avg = {e: round(float(D["d_" + e].mean()), 4) for e in els if "d_" + e in D}
    out = {"launch": x, "name": I.loc[x, "name"], "tagline": I.loc[x, "tagline"], "day": d, "pool": len(D), "real_voters_in_pool": int(D.person.isin(voted).sum()),
           "expected_votes_from_pool": round(float((D.w * D.p).sum()), 1), "gemini_page_output": ps.get("result"), "average_element_push": avg,
           "element_push_total_expected_votes": {e: round(float((D.w * D["d_" + e]).sum()), 2) for e in els if "d_" + e in D}, "people": people,
           "persona_ratings_for_launch": len(pr) if "_error" not in pr else pr["_error"]}
    json.dump(out, open(f"{HERE}/reports/element_sim_{x}.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "people"}, indent=1, default=str))
    for p in people:
        print(json.dumps(p, default=str))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15)
