"""Human mode on top of the shipped agent mode (mvp/agent_mode.py), per person, on real held-out reviewers.

For a product with a live scrape (cache/live) and a signed-in human-mode run (out/human_mode/runs_deep):
  - 40 of its live reviews (with pros and cons) are the held-out people; the remaining reviews are the product's
    "own earlier reviews" agent mode sees; its 3 named rivals' live scrapes are the rivals.
  - agent:        agent mode's words prompt + evidence (exactly mvp/agent_mode.py), 2 seeds
  - human_edit1F: agent's pros/cons, at most 1 pro and 1 con changed by the run's filtered notes (mvp/human_mode.py)
  - human_free:   agent evidence + the run notes appended (free-form, for contrast)
Scored with the side-separated judge (human_mode.judge_list): share of the person's real pros / cons matched.

    python experiments/staged_context/hm_agent_eval.py Basecamp Bitwarden GetResponse
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import experiment as E  # noqa: E402
import human_mode as H  # noqa: E402
import live as L  # noqa: E402
import router_eval as RE  # noqa: E402

from mvp import agent_mode as AM  # noqa: E402
from mvp import human_mode as HM  # noqa: E402
from mvp import review_context as RC  # noqa: E402

FLASH = "gemini-2.5-flash"
N_HELD = 40
SEEDS = 2


def reviews(name: str) -> list[dict]:
    return [RC._all_in_one_item(x) for x in L.scrape(name)]


def run_notes(product: str) -> list[dict]:
    obs = []
    for p in sorted((H.HOUT / "runs_deep").glob(f"{L.slug(product).replace('-', '_')}_deep_*.json")):
        r = json.loads(p.read_text())
        if r.get("signed_in") and r.get("reached_product"):
            obs += r.get("observations") or []
    return obs


def kept_notes(product: str, obs: list[dict]) -> list[str]:
    lines = [f"- [{o['kind'].replace('product_', '')}] {o['what']}" for o in obs
             if o.get("kind") in ("product_friction", "product_benefit")]
    return H.filter_first_session(product, lines)


def evaluate(product: str) -> pd.DataFrame:
    comps = E.read_json(E.OUT / "mixture" / "competitors.json")
    rivals = [c for c in comps.get(product, []) if (L.LIVE / f"{L.slug(c)}.json").is_file()][:3]
    if not rivals:  # Capterra TEST products: names from human_mode.RUN_PRODUCTS context are snapshot-only; name them now
        rivals = [c for c in L.named_competitors(product, E.read_json(H.HOUT / "run_tasks.json")[product]["url"])
                  if (L.LIVE / f"{L.slug(c)}.json").is_file()][:3]
    own_all = reviews(product)
    riv = [x for c in rivals for x in reviews(c)]
    usable = [r for r in own_all if r.get("pros") and r.get("cons") and r.get("role")]
    usable.sort(key=lambda r: E.sha(f"42|hmagent|{product}|{r.get('pros')}|{r.get('cons')}"))
    held = usable[:N_HELD]
    held_ids = {id(r) for r in held}
    own = [r for r in own_all if id(r) not in held_ids]
    obs = run_notes(product)
    kept = kept_notes(product, obs)
    free_notes = "\n".join(f"- [{o['kind'].replace('product_', '')}] {o['what']}" for o in obs
                           if o.get("kind") in ("product_friction", "product_benefit"))
    url = E.read_json(H.HOUT / "run_tasks.json")[product]["url"]
    pool = ThreadPoolExecutor(48)

    def ref(r):
        text = f"Liked: {r['pros']}\nDisliked: {r['cons']}\n{E.clean(r.get('text'))}"
        rec = E.call_model("hm_live_extract", FLASH, "You extract claims from reviews. Return JSON only.",
                           RE.EXTRACT.format(product=product, text=text), temperature=0.0, seed=42, max_tokens=4096,
                           thinking_budget=512)
        j = rec.get("json") if isinstance(rec.get("json"), dict) else {}
        return {"task": j.get("task"), "benefits": [str(x) for x in (j.get("benefits") or [])][:4],
                "frictions": [str(x) for x in (j.get("frictions") or [])][:4]}
    refs = list(pool.map(ref, held))

    def person(r):
        return {k: v for k, v in {"role": r.get("role"), "company_size": r.get("size"), "industry": r.get("industry"),
                                  "time_used": r.get("time_used")}.items() if v}

    def one(job):
        i, seed = job
        r, rf = held[i], refs[i]
        p = person(r)
        ratings = AM.rating_estimates(own, riv)
        AM.personalize(ratings, p)
        ev = AM.evidence_text(product, own, riv, p, ratings)[:14000]
        prompt = AM.words_prompt(product, url, p, rf.get("task") or "", ev)
        agent = E.call_model("hm_agent_words", FLASH, AM.WORDS_SYSTEM, prompt, temperature=0.7, seed=1000 + seed,
                             max_tokens=8192, thinking_budget=AM.WORDS_THINKING).get("json") or {}
        rows = [{"product": product, "i": i, "seed": seed, "cond": "agent", **H.judge_list(agent, rf)}]
        free = E.call_model("hm_agent_words", FLASH, AM.WORDS_SYSTEM,
                            prompt + "\n\n" + H.RUN_RAW.format(product=product, obs=free_notes), temperature=0.7,
                            seed=1000 + seed, max_tokens=8192, thinking_budget=AM.WORDS_THINKING).get("json") or {}
        rows.append({"product": product, "i": i, "seed": seed, "cond": "human_free", **H.judge_list(free, rf)})
        edited = dict(agent)
        if kept and agent.get("pros") and agent.get("cons"):
            lists = "Pros:\n" + "\n".join(f"- {x}" for x in agent["pros"]) + "\nCons:\n" + "\n".join(f"- {x}" for x in agent["cons"])
            j = E.call_model("hm_agent_edit", FLASH, "You revise product predictions conservatively. Return JSON only.",
                             HM.EDIT_PROMPT.format(product=product, lists=lists, obs="\n".join(kept), k=HM.MAX_EDITS),
                             temperature=0.0, seed=42 + seed, max_tokens=4096, thinking_budget=1024).get("json") or {}
            edited = {"pros": HM._bounded(agent["pros"], j.get("pros")), "cons": HM._bounded(agent["cons"], j.get("cons"))}
        rows.append({"product": product, "i": i, "seed": seed, "cond": "human_edit1F", **H.judge_list(edited, rf)})
        return rows
    rows = [x for rs in pool.map(one, [(i, s) for i in range(len(held)) for s in range(SEEDS)]) for x in rs]
    D = pd.DataFrame(rows)
    D["n_obs"], D["n_kept"], D["n_own"], D["rivals"] = len(obs), len(kept), len(own), ",".join(rivals)
    return D


if __name__ == "__main__":
    out = pd.concat([evaluate(p) for p in sys.argv[1:]], ignore_index=True)
    out.to_csv(H.HOUT / "agent_mode_plus_run.csv", index=False)
    cols = ["pros_recall", "cons_recall", "pros_covered", "cons_covered"]
    pd.set_option("display.width", 200)
    print(out.groupby(["product", "cond"])[cols].mean().round(3))
    print(out.groupby("cond")[cols].mean().round(3))
    print(f"spend ${E.spent_usd():.3f}")
