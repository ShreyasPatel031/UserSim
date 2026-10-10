"""Data Lever Board: which data improves which prediction, measured where we have run it.

Single source of truth. Running this file writes:
  docs/plans/eval/data_sources.json   (the data)
  docs/data_lever_board.html          (interactive board: leaderboard, data x benchmark matrix, experiment log)

Numbers in the experiment log are read from results files (results/humaine/*.json, results/popadapt/cards_twin.json)
or quoted from committed docs with the file named in `src`. Nothing is typed in by hand twice.

Tracks (never mixed in one number)
  zero_data   only data from outside the benchmark being scored
  pilot       a small random sample of the target population (simulated from the benchmark, removed from scoring)
  in_dataset  uses the benchmark's own rows (tuning or yardstick); shown for scale only
Stage usefulness (0-3): how much this data can improve UserSim's predictions for that stage.
  0 none, 1 small or indirect, 2 moderate, 3 large. Measured rows are scored from our runs; others from the literature
  (evidence = "literature") or our expectation (evidence = "hypothesis").
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RES = ROOT / "results"

STAGES = {
    "P1": "Population answer distributions",
    "P2": "First impression and preference before use",
    "P3": "Task outcomes and preference after use",
    "P4": "Overall choice between products",
}
LEVERS = {
    "evidence": "Real answers from other people to the same or related questions",
    "prior": "Base rates the model cannot know: tie and neutral shares, scale use, outcome rates",
    "context": "Facts about the products given to the model (ratings, listings, reviews)",
    "calibration": "Labels used to fit spread, tie share or bias corrections",
    "training": "Corpus for fine-tuning a judge, reader or behaviour model",
    "profiles": "Person-level histories used to build reasons and segments",
    "outcomes": "Ground truth to score forecasts on (ledgers, live launches)",
}
TIERS = {
    "FREE": "Public data or our own compute (GCP and model calls not counted)",
    "EXPERIMENTAL": "About $200 a month: small paid pilots to find which direction pays",
    "INCREMENTAL": "About $2,000 a month: scale the directions that proved out",
}
EVIDENCE = {"measured": "Measured by us", "literature": "Published result", "hypothesis": "Our expectation, untested"}
BENCHES = [
    ("simbench", "SimBench", "P1"), ("twin", "Twin-2K-500", "P1"), ("h_overall", "HUMAINE overall", "P4"),
    ("h_reasons", "HUMAINE reasons", "P4"), ("h_p3", "HUMAINE goal score", "P3"), ("prism", "PRISM", "P2"),
    ("upworthy", "Upworthy", "P2"), ("p2bench", "P2-Bench (to build)", "P2"), ("opera", "OPeRA", "P3"),
    ("live", "Show HN / PH live", "P4"),
]


def _j(path):
    p = RES / path
    return json.loads(p.read_text()) if p.exists() else None


def _mean_reasons(row):
    ks = ["core_task_performance_and_reasoning", "interaction_fluidity_and_adaptiveness",
          "communication_style_and_presentation", "trust_ethics_and_safety"]
    return round(sum(row[k]["S"] for k in ks) / 4, 1)


# ------------------------------------------------------------------ experiment log (built from results files)
def experiments():
    E = []
    sc, tr, tw = _j("humaine/scores.json"), _j("humaine/transfer.json"), _j("popadapt/cards_twin.json")
    add = lambda **k: E.append(k)
    # SimBench, quoted from docs/plans/usersim_direction_2026-10.md (three-tier headline) and this run's SimBench fit
    add(id="S1", bench="simbench", stage="P1", data="Same question answered by other populations, plus base rates", lever="evidence",
        track="zero_data", base=41.46, value=55.80, ci=[55.08, 56.50], metric="S",
        note="Leave-one-dataset-out; no labels from the target dataset. Base 41.46 = Haiku 4.5 with retrieved solved examples (zero-shot is about 33). About 69% of the full lift comes from other populations' answers.",
        src="docs/plans/usersim_direction_2026-10.md")
    add(id="S2", bench="simbench", stage="P1", data="Small cognitive models trained on each instrument's labels", lever="training",
        track="zero_data", base=55.80, value=59.68, ci=[59.10, 60.25], metric="S",
        note="Choices13k, NumberGame, MoralMachine, cross-fitted on each dataset.", src="docs/plans/usersim_direction_2026-10.md")
    add(id="S3", bench="simbench", stage="P1", data="Target-domain labels for tuning (8 cross-validated rounds)", lever="calibration",
        track="in_dataset", base=59.89, value=62.49, ci=None, metric="S",
        note="Developed on the benchmark itself, so optimistic. Shown for scale only.", src="docs/plans/usersim_direction_2026-10.md")
    add(id="S4", bench="simbench", stage="P1", data="Target-population calibration labels", lever="calibration",
        track="pilot", base=0.0, value=2.0, ci=None, metric="dS",
        note="Breaks even at about 25 labels (+0.6 [0.2, 1.1]); levels off near +2 at 100-200 labels.",
        src="docs/plans/usersim_direction_2026-10.md")
    if tr:
        sb = tr["simbench_calibration"]
        add(id="S5", bench="simbench", stage="P1", data="Gemini 2.5 Flash spread calibration (temperature)", lever="calibration",
            track="in_dataset", base=sb["S_raw"], value=sb["S_T"], ci=None, metric="S",
            note=f"Fitted on {sb['questions']} SimBench questions (T = {sb['T']}); this is the fit itself, then carried to HUMAINE (H7). "
                 f"Gemini's 'neither / neutral' share on SimBench is already close to humans ({sb['indiff_gemini_mean']:.3f} vs {sb['indiff_human_mean']:.3f}).",
            src="results/humaine/simbench_calibration.json")
    # Twin-2K popadapt
    if tw:
        t = tw["twin_pricing"]["test_tvd"]["0.1"]
        add(id="T1", bench="twin", stage="P1", data="A person's answers to other question blocks (reasons axes)", lever="profiles",
            track="zero_data", base=t["anchor_mean"], value=t["axes"], ci=None, metric="TVD (lower is better)",
            note=f"40 pricing items held out as a block, 10% anchors. Demographics alone: {t['attribute']}. Gap between groups: correlation {t['group_gap_correlation']['axes']} with axes vs {t['group_gap_correlation']['attribute']} with the best attribute. Segments unstable (ARI {tw['twin_pricing']['stability']['segment_ARI_mean']}).",
            src="results/popadapt/cards_twin.json")
        add(id="T2", bench="twin", stage="P1", data="Demographics alone (best single attribute)", lever="profiles",
            track="zero_data", base=t["anchor_mean"], value=t["attribute"], ci=t["attribute_gain_ci"], metric="TVD (lower is better)",
            note="Same split as T1. Gain over the anchor is a tenth of what the reasons axes give.", src="results/popadapt/cards_twin.json")
    if sc:
        p4, p3 = sc["p4"], sc["p3"]
        r = lambda a: (p4[a]["overall_winner"]["S"], _mean_reasons(p4[a]))
        ex = lambda a: p4[a]["extras"]
        add(id="H0", bench="h_overall", stage="P4", data="None: Gemini 2.5 Flash with product names only", lever="context", track="zero_data",
            base=0.0, value=r("gemini_plain")[0], ci=p4["gemini_plain"]["overall_winner"]["ci"], metric="S",
            reasons=r("gemini_plain")[1], note=f"Ceiling {p4['gemini_plain']['overall_winner']['ceiling']} (sampling noise). Clear winner called right on {ex('gemini_plain')['winner_accuracy_clear_pairs']:.1%} of {ex('gemini_plain')['n_clear_pairs']} pairs. Reasons mean S {r('gemini_plain')[1]}.",
            src="results/humaine/scores.json")
        add(id="H1", bench="h_overall", stage="P4", data="LMArena leaderboard ratings given to the model", lever="context", track="zero_data",
            base=r("gemini_plain")[0], value=r("gemini_arena")[0], ci=p4["gemini_arena"]["overall_winner"]["ci"], metric="S",
            reasons=r("gemini_arena")[1], note=f"Clear winner called right {ex('gemini_plain')['winner_accuracy_clear_pairs']:.1%} -> {ex('gemini_arena')['winner_accuracy_clear_pairs']:.1%}; Spearman {ex('gemini_plain')['spearman_net_preference']} -> {ex('gemini_arena')['spearman_net_preference']}.",
            src="results/humaine/scores.json")
        add(id="H1r", bench="h_reasons", stage="P4", data="LMArena leaderboard ratings given to the model", lever="context", track="zero_data",
            base=r("gemini_plain")[1], value=r("gemini_arena")[1], ci=None, metric="S (mean of 4 reasons)",
            note="More confident, so worse where people mostly say 'tie' (core task 38%, trust 66% ties).", src="results/humaine/scores.json")
        add(id="H2", bench="h_overall", stage="P4", data="LMArena ratings as a direct Elo predictor (no LLM)", lever="context", track="zero_data",
            base=r("gemini_plain")[0], value=r("arena_direct")[0], ci=p4["arena_direct"]["overall_winner"]["ci"], metric="S",
            note=f"Tie share 27.5% from arena votes (tie + both bad). Clear winner right {ex('arena_direct')['winner_accuracy_clear_pairs']:.1%}.",
            src="results/humaine/scores.json")
        add(id="H3", bench="h_overall", stage="P4", data="OpenRouter listing (description, release date, price)", lever="context", track="zero_data",
            base=r("gemini_plain")[0], value=r("gemini_meta")[0], ci=p4["gemini_meta"]["overall_winner"]["ci"], metric="S",
            note=f"No help: clear winner right {ex('gemini_meta')['winner_accuracy_clear_pairs']:.1%}. Reasons {r('gemini_plain')[1]} -> {r('gemini_meta')[1]}.",
            src="results/humaine/scores.json")
        add(id="H3p", bench="h_p3", stage="P3", data="OpenRouter listing (description, release date, price)", lever="context", track="zero_data",
            base=p3["gemini_plain"]["S"], value=p3["gemini_meta"]["S"], ci=p3["gemini_meta"]["ci"], metric="S",
            note="Goal-achievement labels come from a GPT-4.1 judge, not from users (HUMAINE paper).", src="results/humaine/scores.json")
        add(id="H1p", bench="h_p3", stage="P3", data="LMArena leaderboard ratings given to the model", lever="context", track="zero_data",
            base=p3["gemini_plain"]["S"], value=p3["gemini_arena"]["S"], ci=p3["gemini_arena"]["ci"], metric="S",
            note=f"Gemini is too pessimistic (mean predicted score 3.4-3.6 vs 4.3 real); the ratings make it worse. Pooled in-dataset yardstick {p3['ref_pooled_humaine']['S']}, ceiling {p3['gemini_plain']['ceiling']}.",
            src="results/humaine/scores.json")
        add(id="Y1", bench="h_overall", stage="P4", data="Yardstick: Bradley-Terry fitted on all other HUMAINE pairs", lever="evidence", track="in_dataset",
            base=r("gemini_plain")[0], value=r("ref_bt_leave_pair_out")[0], ci=p4["ref_bt_leave_pair_out"]["overall_winner"]["ci"], metric="S",
            reasons=r("ref_bt_leave_pair_out")[1], note="What in-population pairwise evidence at HUMAINE scale (tens of thousands of votes) is worth. Not an allowed method.",
            src="results/humaine/scores.json")
        add(id="Y2", bench="h_overall", stage="P4", data="Yardstick: HUMAINE's own tie rate, 50/50 split", lever="prior", track="in_dataset",
            base=0.0, value=r("ref_tie_prior")[0], ci=p4["ref_tie_prior"]["overall_winner"]["ci"], metric="S",
            note=f"Knowing only how often people say 'tie' scores {r('ref_tie_prior')[0]} overall and {r('ref_tie_prior')[1]} on reasons.",
            src="results/humaine/scores.json")
    if tr:
        z, dg = tr["zero_data"], tr["diagnostic"]
        o = lambda k: z[k]["overall_winner"]["S"]
        add(id="H4", bench="h_overall", stage="P4", data="LMArena vote tie share, 'tie' only (15.9%)", lever="prior", track="zero_data",
            base=o("gemini_arena"), value=o("gemini_arena+arena_tie_tie"), ci=z["gemini_arena+arena_tie_tie"]["overall_winner"]["ci"], metric="S",
            note=f"Post hoc: chosen after the pre-registered variant (H5) was scored. Reasons {_mean_reasons(z['gemini_arena'])} -> {_mean_reasons(z['gemini_arena+arena_tie_tie'])}.",
            src="results/humaine/transfer.json")
        add(id="H5", bench="h_overall", stage="P4", data="LMArena vote tie share, tie + both bad (27.5%, pre-registered)", lever="prior", track="zero_data",
            base=o("gemini_arena"), value=o("gemini_arena+arena_tie_tie_bothbad"), ci=z["gemini_arena+arena_tie_tie_bothbad"]["overall_winner"]["ci"], metric="S",
            note=f"Hurts overall, helps reasons ({_mean_reasons(z['gemini_arena'])} -> {_mean_reasons(z['gemini_arena+arena_tie_tie_bothbad'])}). One external tie share cannot serve dimensions whose true tie rates run from 11% to 66%.",
            src="results/humaine/transfer.json")
        add(id="H5r", bench="h_reasons", stage="P4", data="LMArena vote tie share, tie + both bad (27.5%, pre-registered)", lever="prior", track="zero_data",
            base=_mean_reasons(z["gemini_arena"]), value=_mean_reasons(z["gemini_arena+arena_tie_tie_bothbad"]), ci=None, metric="S (mean of 4 reasons)",
            note="Same transfer, scored on the four reasons.", src="results/humaine/transfer.json")
        add(id="H6", bench="h_overall", stage="P4", data="SimBench-fitted temperature (other benchmark)", lever="calibration", track="zero_data",
            base=o("gemini_arena"), value=o("gemini_arena+simbench_T"), ci=z["gemini_arena+simbench_T"]["overall_winner"]["ci"], metric="S",
            note=f"Survey calibration does not carry over to who-wins. Reasons {_mean_reasons(z['gemini_arena'])} -> {_mean_reasons(z['gemini_arena+simbench_T'])} (flatter is better there).",
            src="results/humaine/transfer.json")
        add(id="H6r", bench="h_reasons", stage="P4", data="SimBench-fitted temperature (other benchmark)", lever="calibration", track="zero_data",
            base=_mean_reasons(z["gemini_arena"]), value=_mean_reasons(z["gemini_arena+simbench_T"]), ci=None, metric="S (mean of 4 reasons)",
            note="Same transfer, scored on the four reasons.", src="results/humaine/transfer.json")
        add(id="H7", bench="h_overall", stage="P4", data="SimBench 'neutral option' bias, applied to ties", lever="calibration", track="zero_data",
            base=o("gemini_arena"), value=o("gemini_arena+simbench_ind"), ci=z["gemini_arena+simbench_ind"]["overall_winner"]["ci"], metric="S",
            note="On surveys Gemini predicts neutral options about right, so the shift is tiny (+0.12 logit) and does not explain HUMAINE ties.",
            src="results/humaine/transfer.json")
        add(id="H8", bench="h_overall", stage="P4", data="Best zero-data stack: arena ratings + arena 'tie' share + SimBench temperature", lever="context", track="zero_data",
            base=o("gemini_plain"), value=o("gemini_arena+arena_tie_tie+simbench_T"), ci=z["gemini_arena+arena_tie_tie+simbench_T"]["overall_winner"]["ci"], metric="S",
            reasons=_mean_reasons(z["gemini_arena+arena_tie_tie+simbench_T"]), note="Includes the post hoc tie variant (H4); treat as an upper estimate for zero-data until re-run pre-registered on a fresh benchmark.",
            src="results/humaine/transfer.json")
        add(id="D1", bench="h_overall", stage="P4", data="Diagnostic: true tie share per dimension", lever="prior", track="in_dataset",
            base=o("gemini_arena"), value=dg["gemini_arena+known_tie_share"]["overall_winner"]["S"], ci=None, metric="S",
            note=f"Reasons {_mean_reasons(z['gemini_arena'])} -> {_mean_reasons(dg['gemini_arena+known_tie_share'])}. Tie share is most of the reasons gap and about 6 points of the overall gap.",
            src="results/humaine/transfer.json")
        add(id="D2", bench="h_overall", stage="P4", data="Diagnostic: true who-wins split per cell", lever="evidence", track="in_dataset",
            base=o("gemini_arena"), value=dg["gemini_arena+known_split"]["overall_winner"]["S"], ci=None, metric="S",
            note="Who wins is the largest remaining lever on overall (about +33).", src="results/humaine/transfer.json")
        for arm, lab in (("gemini_plain", "no context"), ("gemini_arena", "with arena ratings")):
            pl = tr.get("pilot", {}).get(arm, {})
            for n in ("25", "50", "100", "200", "400"):
                if n not in pl:
                    continue
                add(id=f"P{'a' if arm == 'gemini_arena' else 'p'}{n}", bench="h_overall", stage="P4",
                    data=f"Pilot of {n} target conversations: tie share + confidence (Gemini {lab})", lever="calibration", track="pilot",
                    base=o(arm), value=pl[n]["overall_S"], ci=None, metric="S", n=int(n),
                    note=f"Mean of 8 random pilots (sd {pl[n]['overall_sd']}); pilot conversations removed from scoring. Reasons {_mean_reasons(z[arm])} -> {pl[n]['reasons_mean_S']}.",
                    reasons=pl[n]["reasons_mean_S"], reasons_base=_mean_reasons(z[arm]), src="results/humaine/transfer.json")
        pe = tr.get("pilot_evidence", {}).get("results", {})
        for n, v in pe.items():
            add(id=f"PE{n}", bench="h_overall", stage="P4", data=f"Pilot of {n} conversations as evidence: arena prior updated with pilot votes",
                lever="evidence", track="pilot", base=o("gemini_arena"), value=v["evidence"], ci=None, metric="S", n=int(n),
                note=f"Same draws: calibration only {v['calib_only']}, arena prior + pilot tie only {v['prior_only']}. Reasons {v['evidence_reasons']}. Prior SD fixed at {tr['pilot_evidence']['prior_sd']} before running.",
                reasons=v["evidence_reasons"], reasons_base=_mean_reasons(z["gemini_arena"]), src="results/humaine/transfer.json")
    return E


# ------------------------------------------------------------------ data sources
# P scores: (0-3, why). exp: expected effect on a benchmark column where not measured: (sign, note); sign in "+", "++", "0", "-", "?".
SOURCES = [
    # ---- measured
    dict(id="pilot", name="Pilot labels from the target population", org="Prolific panel or the customer's own users", tier="EXPERIMENTAL",
         status="to_collect", evidence="measured", levers=["calibration", "evidence"], license="ours", commercial="yes",
         P={"P1": (3, "SimBench: break-even at about 25 labels, about +2 S at 100-200"),
            "P2": (3, "Sets the tie and neutral shares and the scale use that no public data gives"),
            "P3": (2, "Success base rates per difficulty band; simulators misjudge hard vs moderate tasks (Lost in Simulation)"),
            "P4": (3, "HUMAINE: 50 conversations move Gemini + arena from 39.5 to 45.2 overall and reasons from -29.6 to +23.5")},
         exp={"prism": ("+", "Calibrates first-turn ratings"), "upworthy": ("+", "Spotify: nonlinear calibration recovers the full effect"),
              "p2bench": ("++", "Required to train the P2 head"), "live": ("+", "Calibrates forecast spread")},
         measured=["S4", "Pa25", "Pa50", "Pa100", "Pa200", "Pa400", "Pp25", "Pp50", "Pp100", "Pp200", "Pp400", "PE25", "PE50", "PE100", "PE200", "PE400"],
         matrix={"h_overall": "PE50", "h_reasons": "PE50", "simbench": "S4"},
         cost="$200 a month buys about 70 ten-minute Prolific sessions (about $2.86 each with the 42.8% fee)",
         next="Run 60-80 blind side-by-side sessions on our own protocol and check the HUMAINE pilot curve replicates",
         note="The strongest measured lever. Most of its value arrives by 50-100 people because it mainly fixes tie share and spread."),
    dict(id="other_pop", name="Same question answered by other populations", org="Survey archives, other segments, earlier waves", tier="FREE",
         status="in_hand", evidence="measured", levers=["evidence"], license="per source (SimBench is CC BY-NC-SA)", commercial="ask",
         P={"P1": (3, "SimBench: 41.5 -> 55.8 with no target labels; about 69% of our lift"),
            "P2": (2, "For products: the same page or concept rated by 50-100 people elsewhere"),
            "P3": (1, "Task outcomes from other user groups"),
            "P4": (2, "Choices of a neighbouring population (HUMAINE yardstick 66.9 shows how much in-population pairwise evidence is worth)")},
         exp={"h_overall": ("+", "Neighbouring-segment votes"), "prism": ("+", "Other countries' ratings of the same models")},
         measured=["S1", "Y1"], cost="Free for public archives; licences vary", next="Retrieval sweep: K 1-40, same vs other segment, minimum support",
         note="Evi-DA (ACL 2026): removing retrieved survey evidence nearly doubles error on new domains."),
    dict(id="lmarena_lb", name="LMArena leaderboard ratings", org="lmarena-ai/leaderboard-dataset", tier="FREE", status="in_hand",
         evidence="measured", levers=["context"], license="CC BY 4.0", commercial="yes",
         P={"P1": (0, ""), "P2": (1, "Ratings come from blind first-turn votes"),
            "P3": (1, "Category ratings (coding, multi-turn) track task fit"),
            "P4": (3, "HUMAINE: +16.3 S overall, clear winner right 52.7% -> 84.3%; Spearman with HUMAINE ranks 0.735 raw")},
         exp={"prism": ("+", "Rank prior for 2023 models (time-matched history needed)"), "live": ("0", "Only covers AI models")},
         measured=["H1", "H1r", "H2", "H1p"], cost="Free", next="Raw + category blend fixed in advance; reasoning-model latency penalty from SEAL/Arena, not from HUMAINE",
         note="Analogue for startups: public ratings of the same products by a different population (Product Hunt, app stores, G2). Hurts the reasons dims unless ties are calibrated."),
    dict(id="arena_votes", name="LMArena vote-level data (tie share, prompts, style)", org="lmarena-ai/arena-human-preference-140k", tier="FREE",
         status="in_hand", evidence="measured", levers=["prior", "training"], license="CC BY 4.0 (model outputs under provider terms)", commercial="ask",
         P={"P1": (0, ""), "P2": (1, "Style effects on first-turn votes (length, markdown)"),
            "P3": (1, "Prompt-conditional strengths for task types"),
            "P4": (2, "Tie share: +3.1 or -18.7 S depending on how 'both bad' maps; prompt-level strengths untested")},
         exp={"h_reasons": ("?", "No per-dimension ties in the arena")},
         measured=["H4", "H5", "H5r"], cost="Free", next="Fit style weights on arena votes and remove the length reward HUMAINE does not have",
         note="Ties are a property of the protocol, so a single outside tie rate helps one dimension and hurts another."),
    dict(id="simbench_cal", name="Calibration from another benchmark (SimBench)", org="Our SimBench runs", tier="FREE", status="in_hand",
         evidence="measured", levers=["calibration"], license="CC BY-NC-SA (research)", commercial="no",
         P={"P1": (1, "On SimBench itself: 33.2 -> 34.7 with temperature 1.25"),
            "P2": (0, ""), "P3": (0, ""),
            "P4": (1, "HUMAINE: -1.8 overall, +10.8 on reasons; survey calibration does not carry to who-wins")},
         exp={}, measured=["S5", "H6", "H6r", "H7"], cost="Free",
         next="Per-protocol calibration bank: one temperature and tie share per answer format, learned across many public datasets",
         note="Cross-benchmark calibration only transfers between similar answer formats."),
    dict(id="profiles", name="A person's earlier answers (profiles)", org="Twin-2K-500 and any panel with repeat respondents", tier="FREE",
         status="in_hand", evidence="measured", levers=["profiles"], license="Twin-2K-500: CC BY 4.0", commercial="yes",
         P={"P1": (2, "Twin-2K: reasons axes beat demographics for individuals and for group gaps"),
            "P2": (2, "Park et al.: interview or survey agents reach 82-86% of test-retest vs 74% from demographics"),
            "P3": (1, ""), "P4": (2, "LoRe on PRISM: 62.5% -> 71.0% with about 4 examples per user")},
         exp={"prism": ("+", "PRISM profiles"), "h_overall": ("0", "HUMAINE has no repeat history per person")},
         measured=["T1"], cost="Free (public); repeat panels later", next="Rectifier bake-off on Twin-2K (PPI++, AIPW, shrinkage) at n = 25-200",
         note="Effect on population numbers is small; the value is in explaining who differs and why."),
    dict(id="metadata", name="Product listings and metadata", org="OpenRouter API (for AI products); app stores and pricing pages generally", tier="FREE",
         status="in_hand", evidence="measured", levers=["context"], license="public API terms", commercial="ask",
         P={"P1": (0, ""), "P2": (1, "Descriptions shape first impressions"), "P3": (0, ""), "P4": (0, "HUMAINE: -0.6 S overall, no help")},
         exp={"live": ("?", "Launch pages may matter more for unknown startups")}, measured=["H3", "H3p"], cost="Free",
         next="Retest on Show HN launches, where the listing is all people see",
         note="For known products the model already knows more than the listing says."),
    dict(id="demographics", name="Demographics alone", org="Any panel", tier="FREE", status="in_hand", evidence="literature",
         levers=["profiles"], license="-", commercial="yes",
         P={"P1": (1, "Twin-2K: barely better than the anchor; persona variables explain under 10% of variance (Hu & Collier)"),
            "P2": (1, "Reinecke & Gajos: demographics move the preference peak but explain little variance"),
            "P3": (0, ""), "P4": (1, "HUMAINE in-dataset check: age-specific model 0.6416 vs pooled 0.6405 accuracy")},
         exp={}, measured=["T2"], cost="Free", next="Use only for segment offsets that pass a stability test",
         note="Aggregate simulation works; individual-level does not (PRISM-X: aggregate r 0.98-0.99, individual tau 0.11-0.22)."),
    # ---- available, not yet tested
    dict(id="prism", name="PRISM alignment dataset", org="Kirk et al., NeurIPS 2024", tier="FREE", status="available", evidence="literature",
         levers=["evidence", "prior", "profiles"], license="CC BY 4.0 human text; CC BY-NC 4.0 model responses", commercial="ask",
         P={"P1": (2, "Stated preferences about AI by segment"), "P2": (3, "First-turn ratings of up to 4 models, then a choice"),
            "P3": (1, ""), "P4": (2, "Segment offsets by model family; near-tie behaviour")},
         exp={"h_overall": ("+", "Age offsets for HUMAINE segment gaps"), "h_reasons": ("+", "Near-tie rates as tie priors"), "prism": ("++", "Next benchmark")},
         measured=[], cost="Free", next="Segment offsets for HUMAINE age gaps; does first impression predict choice (P2 -> P4)?",
         note="The only public set linking profiles, first impressions and choice."),
    dict(id="community_align", name="Community Alignment dataset", org="Meta, 2025", tier="FREE", status="available", evidence="literature",
         levers=["evidence", "profiles"], license="CC BY 4.0", commercial="yes",
         P={"P1": (2, "15k nationally representative survey respondents in 5 countries"), "P2": (2, "Style and value preferences by segment"),
            "P3": (0, ""), "P4": (1, "Not product choice: all candidates from one model")},
         exp={"h_overall": ("+", "Age x style offsets")}, measured=[], cost="Free", next="Age x style offsets, tested on HUMAINE age gaps",
         note="Over 200k comparisons from 3,500 annotators with age, gender, education, politics, ethnicity."),
    dict(id="helpsteer", name="HelpSteer2/3 attribute ratings", org="NVIDIA", tier="FREE", status="available", evidence="hypothesis",
         levers=["prior"], license="CC BY 4.0", commercial="yes",
         P={"P1": (0, ""), "P2": (1, "Attribute ratings of response pairs"), "P3": (0, ""), "P4": (2, "Equal-rating share per attribute as a per-dimension tie prior")},
         exp={"h_reasons": ("+", "Correctness and coherence ties as priors for core task and style")}, measured=[], cost="Free",
         next="Tie prior per dimension from equal ratings, fixed before scoring HUMAINE", note="Fills the gap the arena tie share could not."),
    dict(id="mtbench", name="MT-Bench human judgments", org="LMSYS, 2023", tier="FREE", status="available", evidence="hypothesis",
         levers=["prior"], license="CC BY 4.0", commercial="yes",
         P={"P1": (0, ""), "P2": (0, ""), "P3": (1, "Multi-turn expert judgments"), "P4": (1, "Tie share for an A / B / tie format with no 'both bad'")},
         exp={"h_overall": ("?", "Expert judges, not the public")}, measured=[], cost="Free", next="Protocol tie prior for A / B / tie formats",
         note="3k expert votes."),
    dict(id="upworthy", name="Upworthy Research Archive", org="Matias et al.", tier="FREE", status="available", evidence="literature",
         levers=["calibration", "training"], license="CC BY 4.0", commercial="yes",
         P={"P1": (0, ""), "P2": (3, "32k headline A/B tests; raw LLM recovers 39% of the effect, tree calibration closes it (Spotify)"),
            "P3": (0, ""), "P4": (1, "A click is a micro-choice")},
         exp={"upworthy": ("++", "Calibration stack replication")}, measured=[], cost="Free",
         next="Spotify-style falsification + random-forest calibration + GPPI intervals", note="Fine-tuned 8B beats GPT-4 by 7-9 points on held-out tests (LOLA)."),
    dict(id="ui_ratings", name="Rated web and app screenshots", org="Miniukovich & Figl 2023, UICrit, UIClip/BetterApp, WiserUI", tier="FREE",
         status="available", evidence="literature", levers=["training", "evidence"], license="mixed: CC BY 4.0, MIT, unstated, NC", commercial="ask",
         P={"P1": (1, "Rating distributions by segment"), "P2": (3, "Fine-tuned heads beat frontier models on held-out sites: +13 to +24 points"),
            "P3": (0, "Static pages do not predict ease of use"), "P4": (1, "")},
         exp={"p2bench": ("++", "Builds P2-Bench v0")}, measured=[], cost="Free",
         next="P2-Bench v0 split by site; frozen-embedding head vs frontier", note="About 3,150 homepages rated by 2,822 people with demographics (Miniukovich & Figl)."),
    dict(id="opera", name="OPeRA shopping sessions", org="NEU-HAI", tier="FREE", status="available", evidence="literature",
         levers=["training", "outcomes"], license="CC BY 4.0", commercial="yes",
         P={"P1": (1, "Persona surveys"), "P2": (1, ""), "P3": (3, "Behaviour prior: next action 9.5% -> 44.6% after training on human traces"), "P4": (1, "")},
         exp={"opera": ("++", "Cooperativeness audit, then behaviour prior")}, measured=[], cost="Free",
         next="Audit our agents' action mix against OPeRA, then train a small critic", note="Prompted agents over-convert: add to cart 80% vs 16% for people."),
    dict(id="mind2web", name="Online-Mind2Web task paths", org="OSU, 2025", tier="FREE", status="available", evidence="hypothesis",
         levers=["outcomes"], license="research", commercial="no",
         P={"P1": (0, ""), "P2": (0, ""), "P3": (2, "Human completion paths on live sites"), "P4": (0, "")},
         exp={}, measured=[], cost="Free", next="Success base rates by task difficulty", note="Branch 3 territory."),
    dict(id="polls", name="New public polls after the model cutoff", org="Pew, Gallup, YouGov, AP-NORC toplines", tier="FREE", status="available",
         evidence="literature", levers=["outcomes", "calibration"], license="toplines public; microdata terms vary", commercial="ask",
         P={"P1": (3, "Fresh questions no model has seen; builds the past-task bank for zero-data intervals"),
            "P2": (0, ""), "P3": (0, ""), "P4": (0, "")},
         exp={"simbench": ("+", "Leakage check and interval coverage")}, measured=[], cost="Free",
         next="Monthly pre-registered predictions; task-exchangeability intervals (Tan & Zrnic: 97% coverage vs 3% naive)",
         note="Turns every month into a clean test and a calibration point."),
    dict(id="ledger", name="Our prediction ledger", org="UserSim", tier="FREE", status="to_collect", evidence="hypothesis",
         levers=["outcomes", "calibration"], license="ours", commercial="yes",
         P={"P1": (2, "Every forecast with its outcome becomes a calibration point"), "P2": (2, ""), "P3": (2, ""), "P4": (2, "")},
         exp={"live": ("++", "Scored forecasts")}, measured=[], cost="Free", next="Pre-register every benchmark and live forecast with a timestamp",
         note="Compounds: the bank of past tasks is what makes zero-data intervals honest."),
    dict(id="showhn", name="Show HN launches (live)", org="Hacker News API", tier="FREE", status="available", evidence="hypothesis",
         levers=["outcomes"], license="public API", commercial="yes",
         P={"P1": (0, ""), "P2": (3, "Landing page first impression of real startups"), "P3": (1, "Some comments from people who tried it"), "P4": (1, "Upvotes measure interest, not adoption")},
         exp={"live": ("++", "Weekly forecasting round")}, measured=[], cost="Free", next="Weekly forecast round with outcomes logged after 48 hours",
         note="Nothing to memorize: products are new."),
    dict(id="producthunt", name="Product Hunt launches (live)", org="Product Hunt API", tier="FREE", status="restricted", evidence="hypothesis",
         levers=["outcomes"], license="non-commercial by default", commercial="no",
         P={"P1": (0, ""), "P2": (2, "Launch page"), "P3": (1, "Reviews"), "P4": (2, "Daily ranking among the day's launches")},
         exp={"live": ("+", "Open benchmark only")}, measured=[], cost="Free", next="Open benchmark only; never in proprietary data",
         note="Campaign noise in rankings."),
    dict(id="userlm", name="UserLM-8b user simulator", org="Microsoft, ICLR 2026", tier="FREE", status="available", evidence="literature",
         levers=["training"], license="MIT", commercial="yes",
         P={"P1": (0, ""), "P2": (0, ""), "P3": (2, "Naturalness 80 vs 3 for GPT-4o; ends conversations like people"), "P4": (0, "")},
         exp={}, measured=[], cost="Free", next="Use as the user side when testing chat products", note="Trained from a base model on 344k WildChat conversations."),
    dict(id="surveys_restricted", name="Survey microdata (WVS, ESS, GSS, ANES, Pew ATP)", org="Survey archives", tier="FREE", status="restricted",
         evidence="literature", levers=["evidence"], license="non-profit or research use; no redistribution", commercial="no",
         P={"P1": (3, "Person-level answers with demographics"), "P2": (0, ""), "P3": (0, ""), "P4": (1, "Product adoption items in some waves")},
         exp={"simbench": ("+", "Research track only")}, measured=[], cost="Free for research", next="Ask archives about commercial terms before any product use",
         note="Research and open-benchmark use only until terms are confirmed."),
    dict(id="personas_synth", name="Synthetic persona sets", org="Nemotron-Personas (CC BY 4.0), PersonaHub (NC)", tier="FREE", status="available",
         evidence="literature", levers=["profiles"], license="mixed", commercial="ask",
         P={"P1": (0, "No accuracy evidence"), "P2": (0, "Generic personas match detailed ones (Kuric et al., 5,504 people)"), "P3": (0, ""), "P4": (0, "")},
         exp={}, measured=[], cost="Free", next="Scaffolding only", note="Listed so we stop reaching for it."),
    # ---- to collect (paid)
    dict(id="p2_panel", name="First-impression panel on post-cutoff startup pages", org="Prolific, 500 ms and 5 s exposure", tier="EXPERIMENTAL",
         status="to_collect", evidence="literature", levers=["outcomes", "training", "calibration"], license="ours", commercial="yes",
         P={"P1": (1, ""), "P2": (3, "The only clean test of first impressions for new, unbranded products"), "P3": (0, ""), "P4": (1, "")},
         exp={"p2bench": ("++", "Ground truth + training data")}, measured=[], cost="About 1,750 ratings a month for $200 (about 50 pages x 35 raters)",
         next="3 months, then check rho >= 0.6 on appeal and trust", note="Quality control: duplicates, recognition test, authenticity checks."),
    dict(id="p3_pairs", name="Within-subject task studies: startup vs competitor", org="Prolific or Userbrain", tier="INCREMENTAL",
         status="to_collect", evidence="literature", levers=["outcomes", "calibration"], license="ours", commercial="yes",
         P={"P1": (1, ""), "P2": (2, "First impression recorded before use"), "P3": (3, "Verified task success, time, ease, then preference"), "P4": (3, "Choice after use")},
         exp={}, measured=[], cost="About 46 fifteen-minute sessions for $200; about 233 for $1,000",
         next="Experimental: one pair every third month; Incremental: 5 pairs a month", note="Success verified by answers or telemetry, never self-report."),
    dict(id="own_panel", name="UserSim linked panel (P1 to P4, same people)", org="Prolific panel + live products", tier="INCREMENTAL",
         status="to_collect", evidence="hypothesis", levers=["profiles", "outcomes", "calibration", "evidence"], license="ours", commercial="yes",
         P={"P1": (3, "Profile survey"), "P2": (3, "First impressions"), "P3": (3, "Task attempts"), "P4": (3, "Then choice")},
         exp={"live": ("+", "")}, measured=[], cost="About $3-4k for 1,000 profiles, then each study", next="Start once two directions show gains per dollar",
         note="The proprietary flywheel: the only design that links all four stages for the same people."),
    dict(id="customer", name="Customer outcomes with consent", org="A/B logs, analytics, NPS", tier="INCREMENTAL", status="to_collect",
         evidence="literature", levers=["calibration", "outcomes"], license="customer agreement", commercial="yes",
         P={"P1": (2, ""), "P2": (3, "Real A/B outcomes"), "P3": (2, "Funnel completion"), "P4": (3, "Conversion and retention")},
         exp={}, measured=[], cost="Free per customer; needs agreements", next="Per-customer calibration ladder switched on after 25 outcomes and a half-split check",
         note="Brand et al.: fine-tuning on prior results transfers within a product category, not across."),
]


def build():
    E = experiments()
    eid = {e["id"]: e for e in E}
    srcs = []
    for s in SOURCES:
        s = dict(s, P={k: {"score": v[0], "why": v[1]} for k, v in s["P"].items()})
        s["measured"] = [m for m in s.get("measured", []) if m in eid]
        cells = {}
        pick = s.get("matrix", {})
        for m in s["measured"]:
            e = eid[m]
            if e["track"] == "in_dataset":
                continue
            if "TVD" in e["metric"]:
                d = round((e["base"] - e["value"]) * 100, 2)  # lower is better: improvement in TVD points
            else:
                d = e["value"] if e["metric"] == "dS" else round(e["value"] - e["base"], 1)
            vals = [(e["bench"], d)]
            if e.get("reasons") is not None and "reasons_base" in e:
                vals.append(("h_reasons", round(e["reasons"] - e["reasons_base"], 1)))
            for key, dv in vals:
                chosen = pick.get(key)
                if chosen and chosen != m:
                    continue
                if chosen or key not in cells or abs(dv) > abs(cells[key]["d"]):
                    cells[key] = {"d": dv, "exp": m, "track": e["track"]}
        s["cells"] = cells
        srcs.append(s)
    data = {"stages": STAGES, "levers": LEVERS, "tiers": TIERS, "evidence": EVIDENCE,
            "benches": [{"id": a, "name": b, "stage": c} for a, b, c in BENCHES], "sources": srcs, "experiments": E}
    (HERE / "data_sources.json").write_text(json.dumps(data, indent=1))
    tpl = (HERE / "data_board.template.html").read_text()
    (ROOT / "docs" / "data_lever_board.html").write_text(tpl.replace("__DATA__", json.dumps(data)))
    print("wrote", len(srcs), "sources,", len(E), "experiments")


if __name__ == "__main__":
    build()
