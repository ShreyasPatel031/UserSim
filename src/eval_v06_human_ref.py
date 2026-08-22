"""Human-referenced comparison for v0.6 free-run trajectories.

The v0.6 first pass reported agent-vs-UserSim head-to-head and scored path
similarity with token Jaccard over raw action strings. That is invalid: the
2022-23 Mind2Web action_reprs ("[div]  Search for events -> CLICK") and the
live extractor's strings ("<input> role=combobox ... -> CLICK") share almost
no tokens by construction, so the score measured serialization format.

Here the recorded human trajectory is the reference. Both conditions are
scored against it on drift-robust behavioral quantities, plus a cross-task
control so the numbers have a floor.
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RESULTS_DIR

STOP_WORDS = {
    "the", "a", "an", "to", "of", "for", "in", "on", "and", "or", "by",
    "click", "type", "select", "hover", "press", "enter", "button", "link",
    "div", "span", "input", "textbox", "combobox", "generic", "label",
    "role", "name", "href", "text", "placeholder", "value", "option",
    "checkbox", "radio", "menuitem", "img", "svg", "path", "li", "ul",
}

HUMAN_RE = re.compile(r"^\s*\[(?P<tag>[^\]]*)\]\s*(?P<label>.*?)\s*->\s*(?P<op>[A-Z_]+)(?::\s*(?P<val>.*))?$")
LIVE_RE = re.compile(r"^(?P<attrs>.*?)\s*->\s*(?P<op>[A-Z_]+)(?::\s*(?P<val>.*))?$")


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1 and t not in STOP_WORDS}


def parse_human(step: str) -> dict | None:
    m = HUMAN_RE.match(step)
    if not m:
        return None
    return {
        "op": m.group("op"),
        "label": (m.group("label") or "").strip(),
        "value": (m.group("val") or "").strip(),
    }


def parse_live(step: str) -> dict | None:
    """Pull the human-visible label out of the live element serialization."""
    if not step or step == "STOP":
        return None
    m = LIVE_RE.match(step)
    if not m:
        return None
    attrs = m.group("attrs")
    # Visible label priority: text= > name= > placeholder=; drop tag/role/href noise.
    label = ""
    for key in ("text=", "name=", "placeholder="):
        idx = attrs.find(key)
        if idx >= 0:
            label = attrs[idx + len(key):]
            # cut at the next attr key
            label = re.split(r"\s+(?:text|name|placeholder|href|role|type|class)=", label)[0]
            break
    return {
        "op": m.group("op"),
        "label": label.strip(),
        "value": (m.group("val") or "").strip(),
    }


def step_sim(a: dict, b: dict) -> float:
    """Token-F1 over label+value, with a small bonus for matching operation."""
    ta = _tokens(f"{a['label']} {a['value']}")
    tb = _tokens(f"{b['label']} {b['value']}")
    if not ta and not tb:
        content = 1.0
    elif not ta or not tb:
        content = 0.0
    else:
        inter = len(ta & tb)
        if inter == 0:
            content = 0.0
        else:
            prec = inter / len(tb)
            rec = inter / len(ta)
            content = 2 * prec * rec / (prec + rec)
    op_match = 1.0 if a["op"] == b["op"] else 0.0
    return 0.8 * content + 0.2 * op_match


MATCH_THRESHOLD = 0.34


def milestone_coverage(human: list[dict], gen: list[dict]) -> dict:
    """Fraction of human steps matched by some generated step (order-free)."""
    if not human:
        return {"coverage": None, "matched": 0, "n_human": 0, "matches": []}
    used: set[int] = set()
    matches = []
    for hi, h in enumerate(human):
        best_j, best_s = None, 0.0
        for gj, g in enumerate(gen):
            if gj in used:
                continue
            s = step_sim(h, g)
            if s > best_s:
                best_s, best_j = s, gj
        if best_j is not None and best_s >= MATCH_THRESHOLD:
            used.add(best_j)
            matches.append({"human_i": hi, "gen_j": best_j, "sim": round(best_s, 3),
                            "human": h["label"] or h["value"], "gen": gen[best_j]["label"] or gen[best_j]["value"]})
        else:
            matches.append({"human_i": hi, "gen_j": None, "sim": round(best_s, 3),
                            "human": h["label"] or h["value"], "gen": None})
    matched = sum(1 for m in matches if m["gen_j"] is not None)
    return {
        "coverage": matched / len(human),
        "matched": matched,
        "n_human": len(human),
        "matches": matches,
    }


def ordered_alignment(human: list[dict], gen: list[dict]) -> float:
    """LCS over thresholded step matches, normalized by human length."""
    if not human or not gen:
        return 0.0
    n, m = len(human), len(gen)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if step_sim(human[i - 1], gen[j - 1]) >= MATCH_THRESHOLD:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m] / n


def typed_value_recall(human: list[dict], gen: list[dict]) -> float | None:
    """Did the run type the same content words the human typed?

    Drift-robust: search queries and form values survive site redesigns even
    when element names and page structure do not.
    """
    ht = set()
    for h in human:
        if h["op"] == "TYPE":
            ht |= _tokens(h["value"])
    if not ht:
        return None
    gt = set()
    for g in gen:
        if g["op"] == "TYPE":
            gt |= _tokens(g["value"])
    return len(ht & gt) / len(ht)


def episode_scores(ep: dict) -> dict:
    human = [p for p in (parse_human(s) for s in ep.get("human_actions") or []) if p]
    gen = [p for p in (parse_live(s.get("action_repr")) for s in ep.get("steps") or []) if p]
    cov = milestone_coverage(human, gen)
    return {
        "annotation_id": ep["annotation_id"],
        "website": ep["website"],
        "condition": ep["condition"],
        "task": ep["task"],
        "n_human": len(human),
        "n_gen": len(gen),
        "length_ratio_vs_human": (len(gen) / len(human)) if human else None,
        "milestone_coverage": cov["coverage"],
        "ordered_alignment": ordered_alignment(human, gen),
        "typed_value_recall": typed_value_recall(human, gen),
        "matches": cov["matches"],
    }


def cross_task_control(episodes: list[dict], seed: int = 0) -> dict:
    """Score each run against a DIFFERENT task's human trace.

    Gives the floor: whatever an unrelated human path scores is the level at
    which a same-task score means nothing.
    """
    rng = random.Random(seed)
    humans = {e["annotation_id"]: e.get("human_actions") or [] for e in episodes}
    ids = sorted(humans)
    covs, aligns = [], []
    for ep in episodes:
        others = [i for i in ids if i != ep["annotation_id"] and humans[i]]
        if not others:
            continue
        other = humans[rng.choice(others)]
        h = [p for p in (parse_human(s) for s in other) if p]
        g = [p for p in (parse_live(s.get("action_repr")) for s in ep.get("steps") or []) if p]
        c = milestone_coverage(h, g)
        if c["coverage"] is not None:
            covs.append(c["coverage"])
        aligns.append(ordered_alignment(h, g))
    return {
        "mean_milestone_coverage": (sum(covs) / len(covs)) if covs else None,
        "mean_ordered_alignment": (sum(aligns) / len(aligns)) if aligns else None,
        "n": len(covs),
    }


def paired_bootstrap(pairs: list[tuple[float, float]], n_boot: int = 5000, seed: int = 7):
    """Bootstrap CI on the mean paired difference (agent - usersim)."""
    if not pairs:
        return None
    rng = random.Random(seed)
    diffs = [a - b for a, b in pairs]
    point = sum(diffs) / len(diffs)
    means = []
    for _ in range(n_boot):
        s = [diffs[rng.randrange(len(diffs))] for _ in diffs]
        means.append(sum(s) / len(s))
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return {"delta": round(point, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def main() -> None:
    episodes = json.loads((RESULTS_DIR / "v06" / "episodes.json").read_text())
    episodes = [e for e in episodes if not e.get("error")]
    scored = [episode_scores(e) for e in episodes]

    by_cond: dict[str, list[dict]] = {}
    for s in scored:
        by_cond.setdefault(s["condition"], []).append(s)

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 4) if xs else None

    per_cond = {
        cond: {
            "n": len(rows),
            "mean_length_ratio_vs_human": mean([r["length_ratio_vs_human"] for r in rows]),
            "mean_milestone_coverage": mean([r["milestone_coverage"] for r in rows]),
            "mean_ordered_alignment": mean([r["ordered_alignment"] for r in rows]),
            "mean_typed_value_recall": mean([r["typed_value_recall"] for r in rows]),
        }
        for cond, rows in by_cond.items()
    }

    a = {r["annotation_id"]: r for r in by_cond.get("agent", [])}
    u = {r["annotation_id"]: r for r in by_cond.get("usersim", [])}
    ids = sorted(set(a) & set(u))
    deltas = {}
    for key in ("milestone_coverage", "ordered_alignment", "length_ratio_vs_human", "typed_value_recall"):
        pairs = [
            (a[i][key], u[i][key]) for i in ids
            if a[i][key] is not None and u[i][key] is not None
        ]
        deltas[key] = paired_bootstrap(pairs)
        if deltas[key]:
            deltas[key]["n_pairs"] = len(pairs)

    out = {
        "reference": "recorded Mind2Web human trajectory (2022-23)",
        "why_rebuilt": (
            "The first v0.6 pass scored token Jaccard over raw action strings. Human "
            "reprs and live-extractor reprs share almost no tokens by construction, so "
            "that number reflected serialization format, not behavior."
        ),
        "metrics": {
            "milestone_coverage": "fraction of human steps matched by any generated step (order-free, token-F1 >= 0.34 on label+value)",
            "ordered_alignment": "LCS of thresholded step matches / human length (order-sensitive)",
            "typed_value_recall": "fraction of human TYPE content words also typed by the run (drift-robust)",
            "length_ratio_vs_human": "generated actions / human actions",
        },
        "per_condition_vs_human": per_cond,
        "paired_delta_agent_minus_usersim": deltas,
        "cross_task_control": cross_task_control(episodes),
        "per_episode": scored,
    }
    (RESULTS_DIR / "summary_v06_human_ref.json").write_text(json.dumps(out, indent=2))

    print(json.dumps({
        "per_condition_vs_human": per_cond,
        "paired_delta_agent_minus_usersim": deltas,
        "cross_task_control": out["cross_task_control"],
    }, indent=2))
    print("\nPer-task vs human trace:")
    print(f"{'site':16s} {'human':>5} {'A_len':>5} {'U_len':>5} {'A_cov':>6} {'U_cov':>6} {'A_ord':>6} {'U_ord':>6}")
    for i in ids:
        ra, ru = a[i], u[i]
        print(f"{ra['website']:16s} {ra['n_human']:5d} {ra['n_gen']:5d} {ru['n_gen']:5d} "
              f"{ra['milestone_coverage']:6.2f} {ru['milestone_coverage']:6.2f} "
              f"{ra['ordered_alignment']:6.2f} {ru['ordered_alignment']:6.2f}")


if __name__ == "__main__":
    main()
