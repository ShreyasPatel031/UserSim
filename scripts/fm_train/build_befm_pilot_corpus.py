#!/usr/bin/env python3
"""Assemble 20–50k BehaviorBench-format SFT JSONL for the 8B-Base kill-test.

Sources:
  - Big Five: OpenPsychometrics BIG5 / Mei bigfive_data.csv (~19.7k subjects)
  - Games: Mei et al. ChatGPT-Behavioral processed MobLab CSVs (no Beauty Contest)

Drops anything that hits results/fm_baselines/leakage_registry.jsonl.
Beauty Contest / guessing is intentionally OUT (no public individual rows);
lift on that task is a transfer result.

Outputs:
  data/fm_train/pilot_corpus.jsonl
  results/fm_train/pilot_filter_log.json
  results/fm_train/pilot_corpus_card.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "fm_train" / "raw"
BB = ROOT / "data" / "fm_baselines" / "BehaviorBench"
REGISTRY = ROOT / "results" / "fm_baselines" / "leakage_registry.jsonl"
OUT_JSONL = ROOT / "data" / "fm_train" / "pilot_corpus.jsonl"
OUT_FILTER = ROOT / "results" / "fm_train" / "pilot_filter_log.json"
OUT_CARD = ROOT / "results" / "fm_train" / "pilot_corpus_card.json"

# IPIP-50 item texts (OpenPsychometrics BIG5 codebook order).
ITEMS: dict[str, str] = {
    "E1": "I am the life of the party.",
    "E2": "I don't talk a lot.",
    "E3": "I feel comfortable around people.",
    "E4": "I keep in the background.",
    "E5": "I start conversations.",
    "E6": "I have little to say.",
    "E7": "I talk to a lot of different people at parties.",
    "E8": "I don't like to draw attention to myself.",
    "E9": "I don't mind being the center of attention.",
    "E10": "I am quiet around strangers.",
    "N1": "I get stressed out easily.",
    "N2": "I am relaxed most of the time.",
    "N3": "I worry about things.",
    "N4": "I seldom feel blue.",
    "N5": "I am easily disturbed.",
    "N6": "I get upset easily.",
    "N7": "I change my mood a lot.",
    "N8": "I have frequent mood swings.",
    "N9": "I get irritated easily.",
    "N10": "I often feel blue.",
    "A1": "I feel little concern for others.",
    "A2": "I am interested in people.",
    "A3": "I insult people.",
    "A4": "I sympathize with others' feelings.",
    "A5": "I am not interested in other people's problems.",
    "A6": "I have a soft heart.",
    "A7": "I am not really interested in others.",
    "A8": "I take time out for others.",
    "A9": "I feel others' emotions.",
    "A10": "I make people feel at ease.",
    "C1": "I am always prepared.",
    "C2": "I leave my belongings around.",
    "C3": "I pay attention to details.",
    "C4": "I make a mess of things.",
    "C5": "I get chores done right away.",
    "C6": "I often forget to put things back in their proper place.",
    "C7": "I like order.",
    "C8": "I shirk my duties.",
    "C9": "I follow a schedule.",
    "C10": "I am exacting in my work.",
    "O1": "I have a rich vocabulary.",
    "O2": "I have difficulty understanding abstract ideas.",
    "O3": "I have a vivid imagination.",
    "O4": "I am not interested in abstract ideas.",
    "O5": "I have excellent ideas.",
    "O6": "I do not have a good imagination.",
    "O7": "I am quick to understand things.",
    "O8": "I use difficult words.",
    "O9": "I spend time reflecting on things.",
    "O10": "I am full of ideas.",
}

RACE_MAP = {
    1: "Mixed Race",
    2: "Arctic (Siberian, Eskimo)",
    3: "Caucasian (European)",
    4: "Caucasian (Indian)",
    5: "Caucasian (Middle East)",
    6: "Caucasian (North African, Other)",
    7: "Indigenous Australian",
    8: "Native American",
    9: "North East Asian (Mongol, Tibetan, Korean Japanese, etc)",
    10: "Pacific (Polynesian, Micronesian, etc)",
    11: "South East Asian (Chinese, Thai, Malay, Filipino, etc)",
    12: "West African, Bushmen, Ethiopian",
    13: "Other",
}
GENDER_MAP = {1: "male", 2: "female", 3: "other"}
HAND_MAP = {1: "Right", 2: "Left", 3: "Both"}
DIM_NAME = {
    "E": "Extraversion",
    "N": "Neuroticism",
    "A": "Agreeableness",
    "C": "Conscientiousness",
    "O": "Openness",
}
# Standard IPIP keyed scoring: reverse-scored items.
REVERSE = {
    "E2", "E4", "E6", "E8", "E10",
    "N2", "N4",
    "A1", "A3", "A5", "A7",
    "C2", "C4", "C6", "C8",
    "O2", "O4", "O6",
}

GAME_SYS = "You are a player who is playing an economics game."

GAME_PROMPTS = {
    "dictator": (
        "You are paired with another player. Your role is to decide how to "
        "divide $100 and the other player simply receives your choice. How "
        "would you like to divide the money? Please give only one concrete "
        "choice and highlight the amount you give to the other player in [] "
        "(such as [$x])."
    ),
    "bomb": (
        "There are 100 boxes, and one bomb has been randomly placed in 1 of "
        "100 boxes. You can choose to open 0-100 boxes at the same time. If "
        "none of the boxes you open has the bomb, you earn points that are "
        "equal to the number of boxes you open. If one of the boxes you open "
        "has the bomb, you earn zero points. How many boxes would you like to "
        "open? Please give a concrete number and highlight it with [] (e.g., [x])."
    ),
    "public_goods": (
        "In this public good game, you and 3 others will choose how much to "
        "contribute towards a water cleaning project. Each of you gets $20 per "
        "round to contribute between $0 and $20. The project has a 50% return "
        "rate. Your payoff relies on both your and others' contributions. "
        "Everyone benefits from the group account equally. How much would you "
        "like to contribute? Please give a concrete number and highlight it "
        "with [] (e.g., [x])."
    ),
    "push_pull": (
        "You're paired with another player, each having a $400 'Push' card and "
        "a $300 'Pull' card. Your payoff depends on both players' card choices. "
        "Here are the scenarios:\n"
        "* Both play 'Push': Each earns $400\n"
        "* You play 'Push', the other player plays 'Pull': You earn $0, the "
        "other player earns $700\n"
        "* You play 'Pull', the other player plays 'Push': You earn $700, the "
        "other player earns $0\n"
        "* Both play 'Pull': Each earns $300\n"
        "Which card would you like to play? Please highlight your choice in "
        "[] (such as [Push] or [Pull])."
    ),
    "trust_investor": (
        "This is a two-player game. You are an Investor and the other player "
        "is a Banker. You have $100 to invest and you choose how much of your "
        "money to invest with the Banker. The amount you choose to invest will "
        "grow by 3x with the Banker. For example, if you invest $10, it will "
        "grow to $30 with the Banker. Then the Banker decides how much of the "
        "grown amount to return to you. How much would you like to invest? "
        "Please give a concrete number and highlight it with [] (e.g., [x])."
    ),
    "trust_banker": (
        "This is a two-player game. You are a Banker and the other player is "
        "an Investor, and the goal for each player is to earn more. The "
        "Investor chooses how much of the money (up to $100) to invest with "
        "you. The amount the Investor invests will generate a 2x return with "
        "you (the current value of investment). Then you decide how much of "
        "the grown amount to return to the Investor. Suppose the Investor "
        "invested $50 (grown to $100 with you). How much would you like to "
        "return? Please give a concrete number and highlight it with [] "
        "(e.g., [x])."
    ),
    "ultimatum_proposer": (
        "This is a two-player game. You are the Proposer, and the other player "
        "is the Responder. As the proposer, you propose how to divide $100 and "
        "the Responder chooses either Accept or Reject. If accepted, the two "
        "of you will earn as described by the accepted proposal accordingly. "
        "If rejected, then both of you earn nothing. How much would you like "
        "to offer to the Responder? Please give a concrete number and "
        "highlight it with [] (e.g., [x])."
    ),
    "ultimatum_responder": (
        "This is a two-player game. You are the Responder, and the other "
        "player is the Proposer. The proposer proposes how to divide $100 and "
        "you, as the Responder, choose either Accept or Reject. If accepted, "
        "the two of you will earn as described by the accepted proposal "
        "accordingly. If rejected, then both of you earn nothing. What is the "
        "minimum offer you would accept? Please give a concrete number and "
        "highlight it with [] (e.g., [x])."
    ),
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def exact_hash(system: str, user: str, assistant: str) -> str:
    return sha256(f"{system}\n\n{user}\n\n{assistant}")


def prompt_hash(system: str, user: str) -> str:
    return sha256(f"{system}\n\n{user}")


def load_registry(path: Path) -> dict:
    exact: set[str] = set()
    subjects: set[int] = set()
    demos: set[str] = set()
    source_index: dict[str, set[int]] = defaultdict(set)
    if not path.exists():
        raise SystemExit(f"missing leakage registry: {path} (run build_leakage_registry.py first)")
    with path.open() as f:
        for line in f:
            rec = json.loads(line)
            kind = rec.get("kind")
            if kind == "eval_example":
                exact.add(rec["exact_hash"])
                if "subject_idx" in rec:
                    subjects.add(int(rec["subject_idx"]))
                if "demo_fingerprint" in rec:
                    demos.add(rec["demo_fingerprint"])
            elif kind == "subject_idx":
                subjects.add(int(rec["subject_idx"]))
            elif kind == "demo_fingerprint":
                demos.add(rec["demo_fingerprint"])
            elif kind == "source_index":
                source_index[rec["task"]].add(int(rec["source_index"]))
    return {
        "exact": exact,
        "subjects": subjects,
        "demos": demos,
        "source_index": source_index,
    }


def demo_fingerprint_from_row(row: pd.Series) -> str | None:
    try:
        age = int(row["age"])
        sex = GENDER_MAP.get(int(row["gender"]))
        country = str(row["country"]).strip().upper()
        if sex is None or age < 13 or country in ("", "NONE", "NAN"):
            return None
        hand = HAND_MAP.get(int(row["hand"]), "unknown").lower()
        race = RACE_MAP.get(int(row["race"]), "other").lower()
        eng_raw = int(row["engnat"])
        eng = "yes" if eng_raw == 1 else ("no" if eng_raw == 2 else "unknown")
        return f"age={age}|sex={sex}|country={country}|hand={hand}|race={race}|eng={eng}"
    except Exception:
        return None


def persona_system(row: pd.Series) -> str | None:
    try:
        age = int(row["age"])
        sex = GENDER_MAP.get(int(row["gender"]))
        country = str(row["country"]).strip().upper()
        if sex is None or age < 13 or len(country) != 2:
            return None
        hand = HAND_MAP.get(int(row["hand"]), "Right")
        race = RACE_MAP.get(int(row["race"]), "Other")
        eng_raw = int(row["engnat"])
        eng = "English" if eng_raw == 1 else "not English"
        return (
            f"You are a {age}-year-old {sex} from {country}. "
            f"You are {hand}-handed. Your race is {race}. "
            f"Your native language is {eng}."
        )
    except Exception:
        return None


def dim_score(row: pd.Series, letter: str) -> int | None:
    total = 0
    for i in range(1, 11):
        key = f"{letter}{i}"
        val = int(row[key])
        if val < 1 or val > 5:
            return None
        total += (6 - val) if key in REVERSE else val
    return total  # 10–50


def make_record(system: str, user: str, assistant: str, source: str, meta: dict) -> dict:
    return {
        "system": system,
        "user": user,
        "assistant": assistant,
        "text": f"{system}\n{user}\n{assistant}",
        "source": source,
        "metadata": meta,
    }


def build_bigfive(df: pd.DataFrame, registry: dict, rng: random.Random, target_n: int) -> tuple[list[dict], Counter]:
    drops: Counter = Counter()
    kept: list[dict] = []
    subjects_used: list[int] = []

    for idx, row in df.iterrows():
        sid = int(idx)
        if sid in registry["subjects"]:
            drops["bigfive_subject_idx"] += 1
            continue
        fp = demo_fingerprint_from_row(row)
        if fp and fp in registry["demos"]:
            drops["bigfive_demo_fingerprint"] += 1
            continue
        system = persona_system(row)
        if system is None:
            drops["bigfive_bad_demo"] += 1
            continue
        # Validate all 50 items present.
        answers = {}
        ok = True
        for key in ITEMS:
            try:
                v = int(row[key])
            except Exception:
                ok = False
                break
            if v < 1 or v > 5:
                ok = False
                break
            answers[key] = v
        if not ok:
            drops["bigfive_bad_items"] += 1
            continue
        subjects_used.append(sid)

        # Task A: demo → item response (sample 2 items / subject)
        item_keys = list(ITEMS.keys())
        rng.shuffle(item_keys)
        for key in item_keys[:2]:
            user = (
                "The following item was rated on a five-point scale where "
                "1=Disagree, 2=Partially Disagree, 3=Neutral, 4=Partially Agree, "
                "5=Agree. Please select how this statement describes you and "
                f"highlight your answer in [](such as [1],[2],[3],[4],or [5]): "
                f"{ITEMS[key]} Only output your answer in brackets."
            )
            asst = f"[{answers[key]}]"
            eh = exact_hash(system, user, asst)
            if eh in registry["exact"]:
                drops["bigfive_exact_surv"] += 1
                continue
            kept.append(
                make_record(
                    system,
                    user,
                    asst,
                    "bigfive_surv_resp",
                    {"subject_idx": sid, "item": key},
                )
            )

        # Task B: demo → personality score (one random dimension)
        letter = rng.choice(list(DIM_NAME))
        score = dim_score(row, letter)
        if score is not None:
            psy_sys = (
                "You are an expert in psychology. Given a person's demographics, "
                "your task is to predict this person's BigFive dimensionality scores."
            )
            user = (
                f"## Demographics\nA {int(row['age'])}-year-old "
                f"{GENDER_MAP.get(int(row['gender']), 'person')} from "
                f"{str(row['country']).strip().upper()}. "
                f"{HAND_MAP.get(int(row['hand']), 'Right')}-handed. "
                f"The race is {RACE_MAP.get(int(row['race']), 'Other')}. "
                f"The native language is "
                f"{'English' if int(row['engnat']) == 1 else 'not English'}.\n\n"
                "## BigFive Dimensionality Scores\n"
                "Each dimensionality score ranges from 10 to 50, with 10 "
                "indicating the lowest score in that dimension and 50 "
                "indicating the highest score.\n\n"
                "## Output Format\n"
                "Based on this person's demographics, please estimate this "
                f"person's personality score in the *{DIM_NAME[letter]}* "
                "dimension. Please output a single number in the range from "
                "10 to 50, highlighted in [] (e.g., [x])."
            )
            asst = f"[{score}]"
            eh = exact_hash(psy_sys, user, asst)
            if eh in registry["exact"]:
                drops["bigfive_exact_pers"] += 1
            else:
                kept.append(
                    make_record(
                        psy_sys,
                        user,
                        asst,
                        "bigfive_pers_score",
                        {"subject_idx": sid, "dimension": letter, "score": score},
                    )
                )

        # Task C: masked item (leave-one-out) for ~40% of subjects
        if rng.random() < 0.4:
            target = rng.choice(list(ITEMS.keys()))
            letter = target[0]
            lines = [
                "## Subject's Answers (Five Personality Dimensions)",
                "The following items were rated on a five point scale where 1=Disagree,",
                "2=Slightly Disagree, 3=Neutral, 4=Slightly Agree, 5=Agree.",
                "",
            ]
            n = 0
            for dim, title in DIM_NAME.items():
                lines.append(f"### {title}")
                for i in range(1, 11):
                    k = f"{dim}{i}"
                    if k == target:
                        continue
                    n += 1
                    lines.append(f"{n}. {ITEMS[k]}")
                    lines.append(f"Answer: [{answers[k]}]")
                lines.append("")
            lines.append(f"## The Target Question (*{DIM_NAME[letter]}* Dimension)")
            lines.append(ITEMS[target])
            lines.append("")
            lines.append("## Output Format")
            lines.append(
                "Please predict the subject's answer to the target question and highlight"
            )
            lines.append(
                "your prediction in [](such as [1],[2],[3],[4],or [5])."
            )
            lines.append("Only output your answer in brackets.")
            user = "\n".join(lines)
            asst = f"[{answers[target]}]"
            mask_sys = (
                "You are an expert in psychology. Given a subject's answers to "
                "49 questions from the Big Five personality test, your task is "
                "to predict this subject's answer to the remaining question."
            )
            eh = exact_hash(mask_sys, user, asst)
            if eh in registry["exact"]:
                drops["bigfive_exact_mask"] += 1
            else:
                kept.append(
                    make_record(
                        mask_sys,
                        user,
                        asst,
                        "bigfive_masked",
                        {"subject_idx": sid, "target_item": target},
                    )
                )

        if len(kept) >= target_n:
            break

    drops["bigfive_subjects_used"] = len(subjects_used)
    return kept, drops


def _first_round(df: pd.DataFrame) -> pd.DataFrame:
    if "Round" in df.columns:
        return df[df["Round"] == 1].copy()
    return df.copy()


def build_games(raw_dir: Path, registry: dict, rng: random.Random, target_n: int) -> tuple[list[dict], Counter]:
    drops: Counter = Counter()
    kept: list[dict] = []

    # Dictator: amount given to other = move if Role implies allocator; CSV has NaNs.
    # Mei dictator: Role second often empty; use rows with numeric move in 0–100.
    paths = {
        "dictator": raw_dir / "dictator.csv",
        "bomb": raw_dir / "bomb_risk.csv",
        "public_goods": raw_dir / "public_goods_linear_water.csv",
        "push_pull": raw_dir / "push_pull.csv",
        "trust": raw_dir / "trust_investment.csv",
        "ultimatum": raw_dir / "ultimatum_strategy.csv",
    }

    # First-round game prompts are shared across subjects (identical user
    # text). Exact (system,user,assistant) hashing would delete every
    # common human action that also appears in the 200-row eval slice.
    # Leakage control for games is therefore: never copy eval JSONL rows,
    # omit guessing, and rely on BehaviorBench's held-out-subject design
    # (Mei CSVs are the public upstream, not the eval JSONL itself).
    def add(game: str, user: str, assistant: str, meta: dict) -> None:
        kept.append(
            make_record(GAME_SYS, user, assistant, f"game_{game}", meta)
        )

    # Dictator — treat non-null move as amount given.
    df = _first_round(pd.read_csv(paths["dictator"]))
    df = df[df["move"].notna()]
    sample = df.sample(n=min(4000, len(df)), random_state=0)
    for _, row in sample.iterrows():
        try:
            amt = int(round(float(row["move"])))
        except Exception:
            drops["dictator_bad"] += 1
            continue
        if amt < 0 or amt > 100:
            drops["dictator_oob"] += 1
            continue
        add("dictator", GAME_PROMPTS["dictator"], f"[{amt}]", {"userid": str(row["UserID"]), "amt": amt})
        if len([k for k in kept if k["source"] == "game_dictator"]) >= target_n // 8:
            break

    # Bomb
    df = _first_round(pd.read_csv(paths["bomb"]))
    df = df[df["move"].notna()]
    sample = df.sample(n=min(4000, len(df)), random_state=1)
    n_bomb = 0
    for _, row in sample.iterrows():
        try:
            amt = int(round(float(row["move"])))
        except Exception:
            continue
        if amt < 0 or amt > 100:
            continue
        add("bomb", GAME_PROMPTS["bomb"], f"[{amt}]", {"userid": str(row["UserID"]), "boxes": amt})
        n_bomb += 1
        if n_bomb >= target_n // 8:
            break

    # Public goods — contribute 0–20
    df = _first_round(pd.read_csv(paths["public_goods"]))
    df = df[df["move"].notna()]
    sample = df.sample(n=min(4000, len(df)), random_state=2)
    n_pg = 0
    for _, row in sample.iterrows():
        try:
            amt = int(round(float(row["move"])))
        except Exception:
            continue
        if amt < 0 or amt > 20:
            continue
        add("public_goods", GAME_PROMPTS["public_goods"], f"[{amt}]", {"userid": str(row["UserID"]), "contrib": amt})
        n_pg += 1
        if n_pg >= target_n // 8:
            break

    # Push/Pull — move 1=Push, 0=Pull (from Mei data)
    df = _first_round(pd.read_csv(paths["push_pull"]))
    df = df[df["move"].notna()]
    sample = df.sample(n=min(4000, len(df)), random_state=3)
    n_pp = 0
    for _, row in sample.iterrows():
        try:
            mv = int(round(float(row["move"])))
        except Exception:
            continue
        choice = "Push" if mv == 1 else ("Pull" if mv == 0 else None)
        if choice is None:
            continue
        add("push_pull", GAME_PROMPTS["push_pull"], f"[{choice}]", {"userid": str(row["UserID"]), "choice": choice})
        n_pp += 1
        if n_pp >= target_n // 8:
            break

    # Trust investor (Role first) / banker (Role second)
    df = _first_round(pd.read_csv(paths["trust"]))
    df = df[df["move"].notna()]
    inv = df[df["Role"].astype(str).str.lower().isin(["first", "investor"])]
    bank = df[df["Role"].astype(str).str.lower().isin(["second", "banker"])]
    n_inv = n_bank = 0
    for _, row in inv.sample(n=min(3000, len(inv)), random_state=4).iterrows():
        try:
            amt = int(round(float(row["move"])))
        except Exception:
            continue
        if amt < 0 or amt > 100:
            continue
        add("trust_investor", GAME_PROMPTS["trust_investor"], f"[{amt}]", {"userid": str(row["UserID"]), "invest": amt})
        n_inv += 1
        if n_inv >= target_n // 10:
            break
    for _, row in bank.sample(n=min(3000, len(bank)), random_state=5).iterrows():
        try:
            amt = int(round(float(row["move"])))
        except Exception:
            continue
        if amt < 0 or amt > 200:
            continue
        add("trust_banker", GAME_PROMPTS["trust_banker"], f"[{amt}]", {"userid": str(row["UserID"]), "return": amt})
        n_bank += 1
        if n_bank >= target_n // 10:
            break

    # Ultimatum proposer/responder thresholds
    df = _first_round(pd.read_csv(paths["ultimatum"]))
    n_up = n_ur = 0
    if "propose" in df.columns:
        for _, row in df[df["propose"].notna()].sample(n=min(3000, len(df)), random_state=6).iterrows():
            try:
                amt = int(round(float(row["propose"])))
            except Exception:
                continue
            if amt < 0 or amt > 100:
                continue
            add("ultimatum_proposer", GAME_PROMPTS["ultimatum_proposer"], f"[{amt}]", {"userid": str(row["UserID"]), "offer": amt})
            n_up += 1
            if n_up >= target_n // 10:
                break
    if "accept" in df.columns:
        for _, row in df[df["accept"].notna()].sample(n=min(3000, len(df)), random_state=7).iterrows():
            try:
                amt = int(round(float(row["accept"])))
            except Exception:
                continue
            if amt < 0 or amt > 100:
                continue
            add("ultimatum_responder", GAME_PROMPTS["ultimatum_responder"], f"[{amt}]", {"userid": str(row["UserID"]), "min_accept": amt})
            n_ur += 1
            if n_ur >= target_n // 10:
                break

    drops["game_note"] = (
        "Beauty Contest / guessing omitted: no public individual MobLab "
        "guessing rows in yutxie/ChatGPT-Behavioral. Kill-test Beauty Contest "
        "win rate is a transfer metric."
    )
    return kept, drops


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT_JSONL)
    ap.add_argument("--filter-log", type=Path, default=OUT_FILTER)
    ap.add_argument("--card", type=Path, default=OUT_CARD)
    ap.add_argument("--target", type=int, default=40000, help="target total examples")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--bigfive-frac", type=float, default=0.75)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    registry = load_registry(args.registry)

    bigfive_path = args.raw / "BIG5" / "data.csv"
    if not bigfive_path.exists():
        bigfive_path = args.raw / "bigfive_data.csv"
    df = pd.read_csv(bigfive_path, sep="\t")
    # Ensure 0-based subject_idx matches OpenPsychometrics row order.
    df = df.reset_index(drop=True)

    bf_target = int(args.target * args.bigfive_frac)
    game_target = args.target - bf_target

    bf_rows, bf_drops = build_bigfive(df, registry, rng, bf_target)
    game_rows, game_drops = build_games(args.raw, registry, rng, max(game_target, 5000))

    all_rows = bf_rows + game_rows
    rng.shuffle(all_rows)

    # Cap at target while keeping mix.
    if len(all_rows) > args.target:
        all_rows = all_rows[: args.target]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_source = Counter(r["source"] for r in all_rows)
    filter_log = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "registry": str(args.registry),
        "n_registry_exact": len(registry["exact"]),
        "n_registry_subjects": len(registry["subjects"]),
        "n_registry_demos": len(registry["demos"]),
        "bigfive_drops": dict(bf_drops),
        "game_drops": {k: (v if not isinstance(v, str) else v) for k, v in game_drops.items()},
        "n_written": len(all_rows),
        "by_source": dict(by_source),
    }
    args.filter_log.parent.mkdir(parents=True, exist_ok=True)
    args.filter_log.write_text(json.dumps(filter_log, indent=2) + "\n")

    card = {
        "name": "qwen3_8b_base_befm_pilot",
        "created_at": filter_log["created_at"],
        "n_examples": len(all_rows),
        "schema": ["system", "user", "assistant", "text", "source", "metadata"],
        "sources": dict(by_source),
        "exclusions": [
            "BehaviorBench eval exact (system,user,assistant) triples",
            "Big Five subject_idx present in eval metadata",
            "Big Five demographic fingerprints matching eval personas",
            "IEO / workflows / Psych-101 / SocSci210",
            "Beauty Contest / guessing (no public individual source)",
        ],
        "path": str(args.out),
        "filter_log": str(args.filter_log),
    }
    args.card.write_text(json.dumps(card, indent=2) + "\n")
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
