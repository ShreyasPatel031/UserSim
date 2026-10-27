"""The "no direct proxy use" check: fails when code outside the gateway (src/fetchgate/) names a proxy host, the
Apify API or token, the old ~/php/proxy.txt, or builds / passes a proxy itself. Run by pytest
(src/fetchgate/test_scan.py), the pre-commit hook (.githooks/pre-commit) and CI.

    python -m fetchgate scan                       # every tracked code file
    python -m fetchgate scan --staged a.py b.sh    # the staged content of these (the pre-commit hook)

To fetch, call fetchgate.fetch() / fetchgate.run_actor(). A line that only *names* a credential for the gateway
can be allowed per file below, with the reason; nothing may be allowed to reach a proxy or Apify directly.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = "src/fetchgate/"
CODE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ts", ".html", ".ipynb", ".service", ".timer",
                 ".toml", ".yaml", ".yml", ".cfg", ".ini", ".env", ".example", ".tf"}
RULES: dict[str, re.Pattern[str]] = {
    "proxy host (proxy.apify.com / DataImpulse)": re.compile(r"proxy\.apify\.com|dataimpulse", re.I),
    "Apify API or client": re.compile(r"api\.apify\.com|apify[-_]client|ApifyClient|apify-cli"),
    "Apify token": re.compile(r"APIFY_TOKEN|\.config/apify/token"),
    "proxy.txt": re.compile(r"proxy\.txt"),
    "saved residential proxy (PROXY_URL, discovery_keys.json)": re.compile(r"\bPROXY_URL\b|discovery_keys\.json"),
    "builds a proxy login (groups-*, //auto:, __cr.*)": re.compile(r"groups-[A-Z]|//auto:|__cr\.[a-z]{2}\b"),
    "passes a proxy to an HTTP client or browser": re.compile(
        r"\bproxies\s*=\s*\{\s*[\"']https?[\"']|[\"']server[\"']\s*:\s*f[\"']https?://\{|--proxy-server|\bcurl\b[^\n]*\s(-x|--proxy)\s"),
}
# file -> (rules it may match, why). Only for names handed to the gateway, never for network use.
ALLOW: dict[str, tuple[set[str], str]] = {
    "mvp/discovery.py": ({"Apify token", "saved residential proxy (PROXY_URL, discovery_keys.json)"},
                         "names the fetch credentials a /discovery user saves or passes for one run; the values only "
                         "go to fetchgate (creds_override)"),
    "mvp/server.py": ({"Apify token", "saved residential proxy (PROXY_URL, discovery_keys.json)"},
                      "the /discovery form's key fields, passed to mvp.discovery"),
    "mvp/test_discovery.py": ({"Apify token"}, "tests of the /discovery key handling (fake values)"),
    "mvp/test_agent_mode.py": ({"Apify token"}, "asserts the user-facing 'no token' message"),
    "scripts/vm/video_experiment_shard.py": ({"passes a proxy to an HTTP client or browser"},
                                             "signed-in YouTube study browser; the operator passes --proxy by hand, "
                                             "the script reads no credential"),
}


def tracked(paths: list[str] | None = None) -> list[str]:
    if paths:
        return [str(Path(p)) for p in paths]
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def is_code(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in CODE_SUFFIXES or p.name in {"Dockerfile", "Makefile", "pre-commit"} or \
        (p.suffix == "" and p.parent.name in {"bin", ".githooks", "hooks"})


def _read(rel: str, staged: bool) -> str | None:
    if staged:
        r = subprocess.run(["git", "show", f":{rel}"], cwd=ROOT, capture_output=True)
        return r.stdout.decode(errors="replace") if r.returncode == 0 else None
    try:
        return (ROOT / rel).read_text(errors="replace")
    except OSError:  # deleted in the working tree
        return None


def violations(paths: list[str] | None = None, *, staged: bool = False) -> list[str]:
    found: list[str] = []
    for rel in tracked(paths):
        rel = rel.replace("\\", "/")
        if Path(rel).name == "proxy.txt":
            found.append(f"{rel}: a proxy.txt file is committed")
            continue
        if rel.startswith(GATEWAY) or not is_code(rel):
            continue
        text = _read(rel, staged)
        if text is None:
            continue
        allowed, _ = ALLOW.get(rel, (set(), ""))
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in RULES.items():
                if name not in allowed and rx.search(line):
                    found.append(f"{rel}:{n}: {name}: {line.strip()[:140]}")
    return found


def main(paths: list[str] | None = None) -> int:
    paths = list(paths or [])
    staged = "--staged" in paths
    paths = [p for p in paths if p != "--staged"]
    if staged and not paths:
        return 0
    bad = violations(paths or None, staged=staged)
    if not bad:
        print("fetchgate scan: no direct proxy or Apify use outside src/fetchgate/")
        return 0
    print("fetchgate scan: direct proxy / Apify use outside the gateway. Fetch through fetchgate.fetch() or "
          "fetchgate.run_actor() instead (see AGENTS.md, docs/discovery/FETCH_LADDER.md):", file=sys.stderr)
    for b in bad:
        print("  " + b, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
