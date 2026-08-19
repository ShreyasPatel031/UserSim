"""Recompute v0.5 metrics with audited endpoint labels. No new Vertex calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RESULTS_DIR
from eval_v05 import bootstrap_delta, pick_examples, summarize, traj_metrics


def pct(x: float) -> float:
    return round(100 * x, 1)


def main() -> None:
    audit = json.loads((RESULTS_DIR / "endpoint_audit.json").read_text())
    quality = {e["annotation_id"]: e["endpoint_quality"] for e in audit["endpoints"]}
    agent = json.loads((RESULTS_DIR / "predictions_v05_agent.json").read_text())
    sim = json.loads((RESULTS_DIR / "predictions_v05_human_sim.json").read_text())

    def subset(rows, allowed):
        return [r for r in rows if quality[r["annotation_id"]] in allowed]

    slices = {
        "naive_last_row_is_stop": (agent, sim),
        "complete_endpoints_only": (
            subset(agent, {"complete"}),
            subset(sim, {"complete"}),
        ),
        "drop_incomplete": (
            subset(agent, {"complete", "ambiguous"}),
            subset(sim, {"complete", "ambiguous"}),
        ),
    }

    out = {
        "judge": "Last logged Mind2Web action is STOP only if the endpoint audit marked the trajectory complete.",
        "audit_counts": audit["counts"],
        "primary": "complete_endpoints_only",
        "slices": {},
    }
    for name, (ar, sr) in slices.items():
        a_sum = summarize("agent", ar, seed=110)
        s_sum = summarize("human_sim", sr, seed=120)
        deltas = {}
        for key in [
            "terminal_continue_rate",
            "premature_stop_rate",
            "f1",
            "length_ratio",
            "mean_p_stop_terminal",
        ]:
            d, lo, hi = bootstrap_delta(
                ar, sr, lambda rs, k=key: traj_metrics(rs)[k], seed=130 + len(key)
            )
            deltas[key] = {"delta": d, "ci95_clustered": [lo, hi]}
        out["slices"][name] = {
            "n_trajectories": a_sum["n_trajectories"],
            "n_steps": a_sum["n_steps"],
            "agent": a_sum,
            "human_sim": s_sum,
            "delta_agent_minus_human_sim": deltas,
            "examples": pick_examples(ar, sr),
        }

    primary = out["slices"]["complete_endpoints_only"]
    out["headline"] = {
        "agent_terminal_continue": primary["agent"]["terminal_continue_rate"],
        "human_sim_terminal_continue": primary["human_sim"]["terminal_continue_rate"],
        "delta": primary["delta_agent_minus_human_sim"]["terminal_continue_rate"],
        "agent_premature_stop": primary["agent"]["premature_stop_rate"],
        "human_sim_premature_stop": primary["human_sim"]["premature_stop_rate"],
        "agent_stop_f1": primary["agent"]["f1"],
        "human_sim_stop_f1": primary["human_sim"]["f1"],
        "agent_length_ratio": primary["agent"]["length_ratio"],
        "human_sim_length_ratio": primary["human_sim"]["length_ratio"],
        "naive_agent_terminal_continue": out["slices"]["naive_last_row_is_stop"]["agent"][
            "terminal_continue_rate"
        ],
        "naive_human_sim_terminal_continue": out["slices"]["naive_last_row_is_stop"][
            "human_sim"
        ]["terminal_continue_rate"],
    }
    (RESULTS_DIR / "summary_v05_judged.json").write_text(json.dumps(out, indent=2))
    h = out["headline"]
    print(json.dumps({
        "audit": out["audit_counts"],
        "naive_40": {
            "agent_term_continue": h["naive_agent_terminal_continue"],
            "sim_term_continue": h["naive_human_sim_terminal_continue"],
        },
        "fixed_27_complete": {
            "n_traj": primary["n_trajectories"],
            "n_steps": primary["n_steps"],
            "agent_term_continue": h["agent_terminal_continue"],
            "agent_ci": primary["agent"]["ci95_clustered"]["terminal_continue_rate"],
            "sim_term_continue": h["human_sim_terminal_continue"],
            "sim_ci": primary["human_sim"]["ci95_clustered"]["terminal_continue_rate"],
            "delta": h["delta"],
            "agent_premature": h["agent_premature_stop"],
            "sim_premature": h["human_sim_premature_stop"],
            "agent_f1": h["agent_stop_f1"],
            "sim_f1": h["human_sim_stop_f1"],
            "agent_len": h["agent_length_ratio"],
            "sim_len": h["human_sim_length_ratio"],
            "agent_continue_examples": primary["examples"]["hyperactivity_agent_only"],
        },
        "drop_incomplete_36": {
            "n_traj": out["slices"]["drop_incomplete"]["n_trajectories"],
            "agent_term_continue": out["slices"]["drop_incomplete"]["agent"]["terminal_continue_rate"],
            "sim_term_continue": out["slices"]["drop_incomplete"]["human_sim"]["terminal_continue_rate"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
