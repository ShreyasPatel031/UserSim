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
    lines = pool_lines(root, pool_path())
    idx = int(slot) - 1
    if 0 <= idx < len(lines):
        return lines[idx]
    return os.environ.get("PACE_PROXY_FILE", str(root / "secrets/iproyal.purl"))


def _fi_purls(root: Path, lines: list[str]) -> list[str]:
    spain = str((root / "secrets/iproyal.purl").resolve())
    return [p for p in lines if Path(p).resolve() != Path(spain).resolve() and "iproyal_fi_" in p]


def pick_next_purl(slot: str, current: str, lines: list[str]) -> str | None:
    fi = _fi_purls(_root(), lines)
    if not fi:
        return None
    st = load_state()
    used = {
        (st["slots"].get(s) or {}).get("host", "")
        for s in st["slots"]
        if s != slot
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
    # All hosts taken — advance cyclically anyway.
    for p in candidates:
        if p != current:
            return p
    return None


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
    return {
        "ok": True,
        "slot": slot,
        "from": cur,
        "to": nxt,
        "from_host": purl_host(Path(cur)),
        "to_host": st["slots"][slot]["host"],
        "gen": gen,
        "reason": reason,
    }


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
