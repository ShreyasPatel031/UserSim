"""Engine identity: which code and which config produced a study.

engine_version is the git commit the server runs plus its content id (the git tree
hash), e.g. "b212561bb4ea+tree.81190a54bf9b". Patches applied with `git am` get new
commit SHAs but the same tree, so the tree id matches the origin commit with the same
code (compare with `git rev-parse <origin-sha>^{tree}`). USERSIM_ENGINE_VERSION wins,
for deploys without a .git; USERSIM_ORIGIN_SHA, when set, is appended as "+origin.<sha>". config_hash covers every MVP_* / model / Browserbase
setting, so two servers on the same commit but different env still differ.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CONFIG_PREFIXES = ("MVP_", "BROWSERBASE_MAX", "GEMINI_MODEL", "USE_BROWSERBASE", "VERTEX_LOCATION")


@lru_cache(maxsize=1)
def engine_version() -> str:
    pinned = (os.environ.get("USERSIM_ENGINE_VERSION") or "").strip()
    if pinned:
        return pinned
    try:
        sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"
    if not sha:
        return "unknown"
    tree = content_id()
    out = sha + (f"+tree.{tree}" if tree else "")
    origin = (os.environ.get("USERSIM_ORIGIN_SHA") or "").strip()[:12]
    if origin:
        out += f"+origin.{origin}"
    return f"{out}-dirty" if dirty else out


@lru_cache(maxsize=1)
def content_id() -> str:
    """Git tree hash of HEAD: identical for identical code, whatever the commit SHA."""
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD^{tree}"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def config_hash() -> str:
    items = sorted(
        (k, v)
        for k, v in os.environ.items()
        if k.startswith(_CONFIG_PREFIXES) and "KEY" not in k and "TOKEN" not in k and "PASSWORD" not in k
    )
    blob = "\n".join(f"{k}={v}" for k, v in items)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def stamp() -> dict[str, str]:
    return {"engine_version": engine_version(), "content_id": content_id(), "config_hash": config_hash()}
