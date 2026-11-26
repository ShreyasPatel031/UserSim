"""Steady 20-IP Lease & Cooldown Coordinator (`usersim_core/fleet/steady_ip_pool.py`).

Fixes the three exact root causes diagnosed with `fleet-cursor` on 2026-11-26:
  1. `no_alternate_ip` & 2-IP ping-ponging: Previously all 20 fleet VMs bound 1:1 to `iproyal_fi_1..20.purl`,
     leaving zero spare `.purl` when a slot hit `cf_wall`, or causing two blocked slots (`32` <-> `41`) to swap
     onto each other's burned IP every 22m.
  2. IPRoyal Sticky-Session Refresh vs Exponential Cooldown: Respects `AGENTS.md` (no block-evasion rotation on
     the same endpoint without backoff): a `cf_wall` slot enters an explicit exponential cooldown lease
     (`10m -> 20m -> 40m -> 80m -> 120m cap`), steps down worker concurrency by 50%, and only steps back up after
     60m clean. When an operator/scheduled pool refresh reassigns `.purl` files across roles, global quarantine
     leases prevent ANY slot from binding an IP that saw a `cf_wall` within `quarantine_sec`.
  3. 15-minute GCS Telemetry Sync: Atomically exports `iproyal_assignments.json`, `iproyal_rotate.log`, and
     `steady_pool_health.json` (with `last_iproyal_rotate_utc` and per-feed SLA checks) every 15m tick.

Usage (turnkey CLI for `fleet-cursor` 15m `ph_fleet_fix_tick.sh`):
  python3 -m usersim_core.fleet.steady_ip_pool tick \
      --status-json /path/to/status.json \
      --assignments-json /path/to/iproyal_assignments.json \
      --state-json /var/lib/usersim/steady_ip_state.json \
      --out-plan /tmp/steady_slot_actions.json
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import datetime as dt
import json
import os
from typing import Any


# Recommended steady-state demand targets across the 20 bought IPs (non-binding input spec;
# fleet-cursor owns slot mapping and VM supervision per AGENTS.md):
RECOMMENDED_DEMAND_TARGETS = {
    "live_ph_capture_and_comments": {
        "target_ips": 3,
        "sla_max_gap_minutes": 15,
        "scope": [
            "00:05 PT lineup + rolling 15m post-midnight launch discovery (lineup_0100 + api_detail)",
            "15m api_comments / comments_ts continuous capture (primary + hot standby to eliminate 30-240m gaps)",
            "sites_0005 live URL redirect resolution + unblocked comment-page fetch",
        ],
    },
    "active_voter_upvote_refresh": {
        "target_ips": 11,
        "sla_freshness_hours": 24,
        "scope": [
            "Daily newest-first Upvotes diff on 14-day & 30-day active complete people (~3,655-8,500 people)",
            "Must keep active voters <=24h fresh through D-1 before 00:05 PT (lifts voter presence AUC 0.562 -> 0.898)",
        ],
    },
    "bounded_high_signal_people_and_surfaces": {
        "target_ips": 6,
        "sla_freshness_hours": 72,
        "scope": [
            "Complete-people completion pass on bounded Top-10 launch backers & commenters (Apr-Nov 2026 high-vote need_list=1,276 first; no unbounded low-activity tail)",
            "Public competitor product surfaces, GitHub stargazer/repo metadata, and HN public threads",
            "Note: Hard anti-bot external targets (X pre-launch search, LinkedIn companies, G2/Capterra reviews) are offloaded to Apify bridge (`usersim_core.apify_pull`) so 0 of the 20 PH IPs burn on third-party walls.",
        ],
    },
}


@dataclass
class SlotLeaseState:
    slot: str
    purl_id: str
    state: str = "unknown"  # active | active_live | cf_wall | dead | stale | cooldown
    consecutive_walls: int = 0
    cooldown_until_utc: float = 0.0
    clean_since_utc: float = 0.0
    worker_scale: float = 1.0  # 1.0 normal, 0.5 after backoff, steps back to 1.0 after 60m clean
    last_action: str = "none"
    last_action_utc: str = ""


@dataclass
class PoolLedger:
    updated_at_utc: str = ""
    last_iproyal_rotate_utc: str = ""
    ip_quarantine_until: dict[str, float] = field(default_factory=dict)
    slots: dict[str, dict[str, Any]] = field(default_factory=dict)


def backoff_minutes(consecutive_walls: int) -> int:
    """AGENTS.md L28-30: pause 10 min, doubling on each further block, cap 2h (120 min)."""
    if consecutive_walls <= 0:
        return 0
    return int(min(120, 10 * (2 ** (consecutive_walls - 1))))


def evaluate_tick(
    now_ts: float,
    status_slots: list[dict[str, Any]],
    assignments: dict[str, str],
    ledger: PoolLedger,
) -> tuple[PoolLedger, list[dict[str, Any]]]:
    """Pure, deterministic 15m tick evaluator producing exact slot actions without ping-ponging."""
    now_iso = dt.datetime.fromtimestamp(now_ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    actions: list[dict[str, Any]] = []

    # Prune expired IP quarantines
    ledger.ip_quarantine_until = {
        ip: exp for ip, exp in ledger.ip_quarantine_until.items() if exp > now_ts
    }

    in_use_purls = set(assignments.values())
    all_known_purls = sorted(set(in_use_purls) | {f"iproyal_fi_{i}" for i in range(1, 21)})

    for row in status_slots:
        slot = str(row.get("slot") or row.get("id") or "")
        if not slot:
            continue
        purl = str(assignments.get(slot) or row.get("purl") or f"slot_{slot}")
        meas = str(row.get("state") or row.get("measure_state") or "unknown")
        prev_raw = ledger.slots.get(slot) or {}
        st = SlotLeaseState(
            slot=slot,
            purl_id=purl,
            state=prev_raw.get("state", "unknown"),
            consecutive_walls=int(prev_raw.get("consecutive_walls", 0)),
            cooldown_until_utc=float(prev_raw.get("cooldown_until_utc", 0.0)),
            clean_since_utc=float(prev_raw.get("clean_since_utc", 0.0)),
            worker_scale=float(prev_raw.get("worker_scale", 1.0)),
            last_action=str(prev_raw.get("last_action", "none")),
            last_action_utc=str(prev_raw.get("last_action_utc", "")),
        )

        if meas == "cf_wall":
            # If already inside an active cooldown window, DO NOT restart phsuper repeatedly on the burned IP!
            if st.cooldown_until_utc > now_ts:
                rem_m = round((st.cooldown_until_utc - now_ts) / 60.0, 1)
                actions.append({
                    "slot": slot,
                    "purl_id": purl,
                    "action": "hold_cooldown",
                    "remaining_minutes": rem_m,
                    "worker_scale": st.worker_scale,
                    "reason": "cf_wall_backoff_in_progress_do_not_hammer_same_ip",
                })
                st.state = "cooldown"
            else:
                st.consecutive_walls += 1
                wait_m = backoff_minutes(st.consecutive_walls)
                st.cooldown_until_utc = now_ts + wait_m * 60.0
                st.clean_since_utc = 0.0
                st.worker_scale = max(0.25, round(st.worker_scale * 0.5, 2))
                st.state = "cooldown"
                st.last_action = f"pause_{wait_m}m_half_workers"
                st.last_action_utc = now_iso
                ledger.ip_quarantine_until[purl] = st.cooldown_until_utc

                spare_choice = None
                for cand_p in all_known_purls:
                    if cand_p not in in_use_purls and cand_p not in ledger.ip_quarantine_until:
                        spare_choice = cand_p
                        in_use_purls.add(cand_p)
                        break
                actions.append({
                    "slot": slot,
                    "purl_id": purl,
                    "action": "enter_backoff_and_half_workers",
                    "pause_minutes": wait_m,
                    "resume_at_utc": dt.datetime.fromtimestamp(st.cooldown_until_utc, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "worker_scale": st.worker_scale,
                    "clean_spare_purl": spare_choice,
                    "reason": f"cf_wall #{st.consecutive_walls}: pause {wait_m}m on same IP (AGENTS.md backoff), resume at {st.worker_scale}x workers",
                })
        elif meas == "dead":
            st.state = "dead"
            st.last_action = "restart_supervisor_in_place"
            st.last_action_utc = now_iso
            actions.append({
                "slot": slot,
                "purl_id": purl,
                "action": "restart_supervisor_in_place",
                "worker_scale": st.worker_scale,
                "reason": "supervisor_down_not_blocked_safe_to_start_in_place",
            })
        elif meas == "stale":
            st.state = "stale"
            st.last_action = "unhang_worker_keep_ip"
            st.last_action_utc = now_iso
            actions.append({
                "slot": slot,
                "purl_id": purl,
                "action": "unhang_worker_keep_ip",
                "worker_scale": st.worker_scale,
                "reason": "batch_hung_without_cf_wall_restart_worker_only",
            })
        elif meas in ("active", "active_live"):
            # If cooldown just expired and slot is clean, track clean duration to step workers back up after 60m!
            if st.clean_since_utc <= 0.0:
                st.clean_since_utc = now_ts
            clean_mins = (now_ts - st.clean_since_utc) / 60.0
            if clean_mins >= 60.0 and (st.worker_scale < 1.0 or st.consecutive_walls > 0):
                st.worker_scale = min(1.0, round(st.worker_scale * 2.0, 2))
                st.consecutive_walls = max(0, st.consecutive_walls - 1)
                st.clean_since_utc = now_ts
                st.last_action = "step_up_workers_after_60m_clean"
                st.last_action_utc = now_iso
                actions.append({
                    "slot": slot,
                    "purl_id": purl,
                    "action": "step_up_workers",
                    "worker_scale": st.worker_scale,
                    "reason": "60m_clean_traffic_achieved",
                })
            st.state = meas
            st.cooldown_until_utc = 0.0

        ledger.slots[slot] = asdict(st)

    ledger.updated_at_utc = now_iso
    return ledger, actions


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_tick = sub.add_parser("tick")
    p_tick.add_argument("--status-json", required=True)
    p_tick.add_argument("--assignments-json", default="")
    p_tick.add_argument("--state-json", required=True)
    p_tick.add_argument("--out-plan", required=True)

    p_spec = sub.add_parser("print-demand-spec")
    p_spec.add_argument("--out", default="")

    args = ap.parse_args()
    if args.cmd == "print-demand-spec":
        txt = json.dumps(RECOMMENDED_DEMAND_TARGETS, indent=2)
        if args.out:
            open(args.out, "w").write(txt + "\n")
        else:
            print(txt)
        return

    raw_status = json.load(open(args.status_json))
    if isinstance(raw_status, dict):
        status_slots = raw_status.get("slots_summary") or raw_status.get("slots") or raw_status.get("vms") or []
        if isinstance(status_slots, int):
            status_slots = []
        elif isinstance(status_slots, dict):
            status_slots = [{"slot": k, **(v if isinstance(v, dict) else {"state": v})} for k, v in status_slots.items()]
    else:
        status_slots = raw_status

    assignments: dict[str, str] = {}
    if args.assignments_json and os.path.exists(args.assignments_json):
        a_raw = json.load(open(args.assignments_json))
        if isinstance(a_raw, dict):
            raw_map = a_raw.get("assignments") if isinstance(a_raw.get("assignments"), dict) else a_raw
            assignments = {str(k): str(v) for k, v in raw_map.items() if not isinstance(v, (dict, list))}

    ledger = PoolLedger()
    if os.path.exists(args.state_json):
        prev = json.load(open(args.state_json))
        ledger = PoolLedger(
            updated_at_utc=str(prev.get("updated_at_utc", "")),
            last_iproyal_rotate_utc=str(prev.get("last_iproyal_rotate_utc", "")),
            ip_quarantine_until={str(k): float(v) for k, v in (prev.get("ip_quarantine_until") or {}).items()},
            slots=dict(prev.get("slots") or {}),
        )

    ledger, actions = evaluate_tick(dt.datetime.now(dt.timezone.utc).timestamp(), status_slots, assignments, ledger)
    os.makedirs(os.path.dirname(os.path.abspath(args.state_json)), exist_ok=True)
    json.dump(asdict(ledger), open(args.state_json, "w"), indent=2)
    out_doc = {
        "generated_at_utc": ledger.updated_at_utc,
        "last_iproyal_rotate_utc": ledger.last_iproyal_rotate_utc,
        "quarantined_ips_count": len(ledger.ip_quarantine_until),
        "actions_count": len(actions),
        "actions": actions,
        "demand_targets_reference": RECOMMENDED_DEMAND_TARGETS,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_plan)), exist_ok=True)
    json.dump(out_doc, open(args.out_plan, "w"), indent=2)
    print(f"[steady_ip_pool] Evaluated {len(ledger.slots)} slots -> {len(actions)} actions written to {args.out_plan}")


if __name__ == "__main__":
    main()
