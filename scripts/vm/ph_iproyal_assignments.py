#!/usr/bin/env python3
"""Per-slot IPRoyal purl assignments (rotate egress IP on block / VM restart)."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse as up
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get("PACE_REPO_ROOT", Path(__file__).resolve().parents[2]))


def art_dir() -> Path:
    run = os.environ.get("PACE_FLEET_RUN_ID", "").lower()
    if not run:
        p = _root() / "results/ph_fleet_full/latest_run.txt"
        if p.is_file():
            run = p.read_text().strip().lower()
    return Path(os.environ.get("FLEET_ART", _root() / f"results/ph_fleet_full/{run}"))


def assign_path() -> Path:
    return art_dir() / "iproyal_assignments.json"


def pool_path() -> Path:
    root = _root()
    p = Path(os.environ.get("PACE_IPROYAL_POOL", root / "secrets/iproyal.pool"))
    return p if p.is_absolute() else root / p


def pool_lines(root: Path, pool: Path) -> list[str]:
    lines = [
        ln.strip()
        for ln in pool.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    out = []
    for ln in lines:
        out.append(ln if ln.startswith("/") else str(root / ln))
    return out


def purl_host(purl: Path) -> str:
    u = up.urlparse(purl.read_text().strip())
    return u.hostname or ""


def load_state() -> dict:
    ap = assign_path()
    if ap.is_file():
        return json.loads(ap.read_text())
    return {"slots": {}, "version": 1}


def save_state(st: dict) -> None:
    ap = assign_path()
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(st, indent=2) + "\n")


def init_from_pool() -> dict:
    root = _root()
    pool = pool_path()
    st = load_state()
    if not pool.is_file():
        return st
    lines = pool_lines(root, pool)
    slots_tsv = art_dir() / "slots.tsv"
    if slots_tsv.is_file():
        for ln in slots_tsv.read_text().splitlines():
            parts = ln.split("\t")
            if not parts or not parts[0].isdigit():
                continue
            slot = parts[0]
            if slot not in st["slots"]:
                idx = int(slot) - 1
                if 0 <= idx < len(lines):
                    p = lines[idx]
                    st["slots"][slot] = {
                        "purl": p,
                        "host": purl_host(Path(p)),
                        "gen": 0,
                    }
    save_state(st)
    return st


def get_purl_abs(slot: int | str) -> str:
    root = _root()
    st = init_from_pool()
    slot = str(slot)
    sl = st["slots"].get(slot)
    if sl and Path(sl["purl"]).is_file():
        return sl["purl"]
    if slot in live_slots():
        rebalance()
        sl = load_state()["slots"].get(slot)
        if sl and Path(sl["purl"]).is_file():
            return sl["purl"]
    lines = pool_lines(root, pool_path())
    idx = int(slot) - 1
    if 0 <= idx < len(lines):
        return lines[idx]
    return os.environ.get("PACE_PROXY_FILE", str(root / "secrets/iproyal.purl"))


def _fi_purls(root: Path, lines: list[str]) -> list[str]:
    spain = str((root / "secrets/iproyal.purl").resolve())
    return [p for p in lines if Path(p).resolve() != Path(spain).resolve() and "iproyal_fi_" in p]


def live_slots() -> set[str]:
    """Slots in slots.tsv (VMs that exist). Deleted slots must not hold IPs."""
    p = art_dir() / "slots.tsv"
    if not p.is_file():
        return set()
    return {ln.split("\t", 1)[0] for ln in p.read_text().splitlines() if ln[:1].isdigit()}


def pick_next_purl(slot: str, current: str, lines: list[str]) -> str | None:
    fi = _fi_purls(_root(), lines)
    if not fi:
        return None
    st = load_state()
    live = live_slots()
    used = {
        (st["slots"].get(s) or {}).get("host", "")
        for s in st["slots"]
        if s != slot and (not live or s in live)
    }
    used.discard("")
    ordered = fi
    if current in ordered:
        i = ordered.index(current)
        candidates = ordered[i + 1 :] + ordered[: i + 1]
    else:
        candidates = ordered
    for p in candidates:
        if p == current:
            continue
        h = purl_host(Path(p))
        if h and h not in used:
            return p
    # Never put two VMs on one IP: they trip Cloudflare together and both stall.
    return None


def rebalance() -> dict:
    """Give every live slot its own IP: keep the current one when unique, else move to a free one."""
    root = _root()
    lines = pool_lines(root, pool_path())
    fi = _fi_purls(root, lines)
    st = init_from_pool()
    live = sorted(live_slots(), key=int)
    for s in list(st["slots"]):
        if s not in live:
            del st["slots"][s]
    taken: dict[str, str] = {}
    moved = []
    need = []
    for s in live:
        sl = st["slots"].get(s) or {}
        h = sl.get("host", "")
        if h and h not in taken and Path(sl.get("purl", "")).is_file():
            taken[h] = s
        else:
            need.append(s)
    free = [p for p in fi if purl_host(Path(p)) not in taken]
    from datetime import datetime, timezone

    for s in need:
        if not free:
            break
        p = free.pop(0)
        h = purl_host(Path(p))
        old = (st["slots"].get(s) or {}).get("host", "")
        st["slots"][s] = {
            "purl": p,
            "host": h,
            "gen": int((st["slots"].get(s) or {}).get("gen") or 0) + 1,
            "last_reason": "rebalance_unique",
            "last_rotate_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        taken[h] = s
        moved.append(
            {
                "slot": s,
                "from_host": old,
                "to_host": h,
                "reason": "rebalance_unique",
                "gen": st["slots"][s]["gen"],
                "utc": st["slots"][s]["last_rotate_utc"],
            }
        )
    save_state(st)
    if moved:
        try:
            from ph_iproyal_rotate_audit import append_row, row_from_rebalance_move

            for m in moved:
                append_row(row_from_rebalance_move(m), flush_gcs=False)
            from ph_iproyal_rotate_audit import flush_mirror_to_gcs

            flush_mirror_to_gcs()
        except Exception:
            pass
    return {
        "live": len(live),
        "unique_hosts": len(taken),
        "moved": moved,
        "free_ips": [purl_host(Path(p)) for p in free],
    }


def rotate_cooldown_ok(slot: str, sec: float = 1200.0) -> bool:
    st = load_state()
    sl = st["slots"].get(slot) or {}
    import datetime as _dt

    last = sl.get("last_rotate_utc")
    if not last:
        return True
    try:
        t = _dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
        return (_dt.datetime.now(_dt.timezone.utc) - t).total_seconds() >= sec
    except Exception:
        return True


def rotate(slot: int | str, reason: str = "block") -> dict:
    root = _root()
    slot = str(slot)
    if not rotate_cooldown_ok(slot):
        return {"ok": False, "reason": "rotate_cooldown", "slot": slot}
    pool = pool_path()
    lines = pool_lines(root, pool)
    st = init_from_pool()
    cur = (st["slots"].get(slot) or {}).get("purl") or get_purl_abs(slot)
    nxt = pick_next_purl(slot, cur, lines)
    if not nxt or nxt == cur:
        return {"ok": False, "reason": "no_alternate_ip", "slot": slot, "host": purl_host(Path(cur))}
    gen = int((st["slots"].get(slot) or {}).get("gen") or 0) + 1
    from datetime import datetime, timezone

    st["slots"][slot] = {
        "purl": nxt,
        "host": purl_host(Path(nxt)),
        "gen": gen,
        "last_reason": reason,
        "last_rotate_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_state(st)
    out = {
        "ok": True,
        "slot": slot,
        "from": cur,
        "to": nxt,
        "from_host": purl_host(Path(cur)),
        "to_host": st["slots"][slot]["host"],
        "gen": gen,
        "reason": reason,
        "utc": st["slots"][slot]["last_rotate_utc"],
    }
    try:
        from ph_iproyal_rotate_audit import record_rotate_result

        record_rotate_result(out)
    except Exception:
        pass
    return out


def cmd_print(slot: str) -> None:
    print(get_purl_abs(slot))


def cmd_rotate(slot: str, reason: str) -> None:
    print(json.dumps(rotate(slot, reason)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: ph_iproyal_assignments.py get|rotate|init [SLOT] [reason]", file=sys.stderr)
        sys.exit(1)
    op = sys.argv[1]
    if op == "init":
        print(json.dumps(init_from_pool(), indent=2))
        raise SystemExit(0)
    if op == "rebalance":
        print(json.dumps(rebalance()))
        raise SystemExit(0)
    if len(sys.argv) < 3:
        print("usage: ph_iproyal_assignments.py get|rotate SLOT [reason]", file=sys.stderr)
        sys.exit(1)
    slot = sys.argv[2]
    if op == "get":
        cmd_print(slot)
    elif op == "rotate":
        cmd_rotate(slot, sys.argv[3] if len(sys.argv) > 3 else "block")
    else:
        sys.exit(2)
