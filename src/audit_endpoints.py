"""Manual audit of 40 Mind2Web endpoints. Last logged action ≠ human decided to stop."""

from __future__ import annotations

import json
from pathlib import Path

from config import RESULTS_DIR

# Rubric:
# complete: last action reasonably fulfills the stated task (search/submit/add-to-cart/
#           open requested object / apply the final stated filter).
# ambiguous: results or a partial constraint; a normal user might still inspect or book.
# incomplete: hover instead of click, explicit Continue/next, or task clearly unfinished.

AUDIT = [
    ("us.megabus", "Find tickets", "complete", "Search submitted for the requested trip."),
    ("kohls", "$25 to $50 wall art", "complete", "Browse task: queried wall art and applied the stated price filter."),
    ("kayak", "Fitness checkbox", "complete", "Route/dates set and all requested amenity filters checked."),
    ("underarmour", "Add to Bag", "complete", "Add-to-cart matches the task."),
    ("booking", "I'll reserve", "complete", "Reserve control is the booking action."),
    ("parking", "Submit", "complete", "Booking form submitted."),
    ("exploretock", "10:00 AM", "ambiguous", "Time slot selected; no Book/Reserve."),
    ("jetblue", "Search Jobs", "complete", "Job search submitted."),
    ("newegg", "Logitech combo", "complete", "Opened the matching product."),
    ("uniqlo", "VIEW CART", "complete", "Task asked to add items and view cart."),
    ("parking", "SEARCH", "complete", "Parking search submitted."),
    ("tesla", "Submit and Continue HOVER", "incomplete", "Form filled but last event is HOVER, not click. Submit never fired."),
    ("ticketcenter", "All NFL Tickets", "complete", "Opened the requested ticket list."),
    ("imdb", "Sci-Fi", "ambiguous", "Genre clicked; unclear that Top 50 is shown."),
    ("new.mta.info", "bridge heading", "ambiguous", "Clicked a grouped crossings heading, not clearly Queens Midtown motorcycle toll."),
    ("enterprise", "Submit", "complete", "Email-offers form submitted."),
    ("redbox", "sortBy Newest", "ambiguous", "Sorted newest; no title chosen / kiosk confirmed as done."),
    ("nyc", "Done", "ambiguous", "Done on a picker, not a purchase."),
    ("seatgeek", "Concerts img", "ambiguous", "LA + dates applied, then Concerts icon; may still be browsing."),
    ("uniqlo", "$0-$10", "complete", "Applied the stated under-$10 filter."),
    ("amazon", "Metformin product", "complete", "Opened the requested product details."),
    ("budget", "Continue", "incomplete", "Wizard Continue after add-ons; page says there is another step."),
    ("us.megabus", "Alanson, MI", "complete", "Selected the requested stop city."),
    ("kayak", "View Deal HOVER", "incomplete", "Found a $75 SUV then HOVER View Deal; click never recorded."),
    ("tesla", "Best Sellers heading", "incomplete", "Three steps, ended on a heading, no accessory opened."),
    ("underarmour", "High Support", "complete", "Women → bras → S → purple → high support: all stated filters."),
    ("rottentomatoes", "Top Critics", "complete", "Opened the requested critic set."),
    ("delta", "Search", "complete", "Requirements search submitted."),
    ("redbox", "rent on demand", "complete", "Rent action for the requested title."),
    ("viator", "Hollywood Sign tour", "ambiguous", "Opened a tour listing; task was to book."),
    ("jetblue", "Checkout", "complete", "Reached checkout for the flight+cruise task."),
    ("new.mta.info", "Plan my Trip submit", "complete", "Trip planner submitted."),
    ("ign", "Open Guide", "complete", "Opened the requested guide."),
    ("espn", "FOLLOW", "complete", "Follow matches the task."),
    ("eventbrite", "Follow", "complete", "Follow organizer matches the task."),
    ("kohls", "Active (6)", "complete", "Plus swim + black + price sort + active: stated constraints applied."),
    ("ticketcenter", "$50/ea", "ambiguous", "Picked a $50 ticket after filtering; not a completed booking."),
    ("nyc", "View full menu", "complete", "Opened the requested menu."),
    ("instacart", "Add", "complete", "Three Add actions; task asked for two fruits and one sauce."),
    ("parking", "View Details ROCKEFELLER", "ambiguous", "Opened a listing near Radio City; no booking."),
]


def main() -> None:
    from collections import Counter

    tasks = json.loads(Path(__file__).resolve().parents[1].joinpath("data/mind2web_v0.json").read_text())[:40]
    agent = json.loads((RESULTS_DIR / "predictions_v05_agent.json").read_text())
    sim = json.loads((RESULTS_DIR / "predictions_v05_human_sim.json").read_text())
    agent_term = {r["annotation_id"]: r for r in agent if r["is_terminal"]}
    sim_term = {r["annotation_id"]: r for r in sim if r["is_terminal"]}

    if len(AUDIT) != 40:
        raise SystemExit(f"audit length {len(AUDIT)}")

    rows = []
    for task, spec in zip(tasks, AUDIT):
        website, last_short, label, why = spec
        if task["website"] != website:
            raise SystemExit(f"order mismatch: {task['website']} vs {website}")
        a = agent_term[task["annotation_id"]]
        s = sim_term[task["annotation_id"]]
        rows.append(
            {
                "annotation_id": task["annotation_id"],
                "website": task["website"],
                "task": task["confirmed_task"],
                "n_steps": len(task["actions"]),
                "last_repr": task["action_reprs"][-1],
                "original_op": (task["actions"][-1].get("operation") or {}).get("original_op"),
                "op": (task["actions"][-1].get("operation") or {}).get("op"),
                "endpoint_quality": label,
                "rationale": why,
                "agent_pred": a["pred"],
                "human_sim_pred": s["pred"],
            }
        )

    counts = Counter(r["endpoint_quality"] for r in rows)

    def term_continue(subset):
        n = len(subset)
        if not n:
            return {"n": 0, "agent": None, "human_sim": None}
        return {
            "n": n,
            "agent": sum(r["agent_pred"] == "CONTINUE" for r in subset) / n,
            "human_sim": sum(r["human_sim_pred"] == "CONTINUE" for r in subset) / n,
            "agent_continue_ids": [
                r["website"] + ": " + r["last_repr"][:50]
                for r in subset
                if r["agent_pred"] == "CONTINUE"
            ],
            "human_sim_continue_ids": [
                r["website"] + ": " + r["last_repr"][:50]
                for r in subset
                if r["human_sim_pred"] == "CONTINUE"
            ],
        }

    complete = [r for r in rows if r["endpoint_quality"] == "complete"]
    report = {
        "rubric": {
            "complete": "Last action reasonably fulfills the stated task.",
            "ambiguous": "Results or a partial constraint; a person might still inspect or book.",
            "incomplete": "Hover-not-click, explicit next/Continue, or task clearly unfinished.",
        },
        "counts": dict(counts),
        "terminal_continue": {
            "all_40": term_continue(rows),
            "complete_only": term_continue(complete),
            "complete_plus_ambiguous": term_continue(
                [r for r in rows if r["endpoint_quality"] != "incomplete"]
            ),
        },
        "endpoints": rows,
    }
    (RESULTS_DIR / "endpoint_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"counts": report["counts"], "terminal_continue": report["terminal_continue"]}, indent=2))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import RESULTS_DIR  # noqa: F401

    main()
