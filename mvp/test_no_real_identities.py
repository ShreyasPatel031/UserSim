"""Guard: no real run's signup identity (password, alias, token) may be committed into tests, fixtures or results.

GitGuardian incident 37980789 (PR #65): a password copied from a live signup_identity was pasted into
test_sim_mcp_loop5.py. Tests must generate throwaway values at runtime (secrets.token_urlsafe, see
test_sim_mcp_loop5.fake_password) and use synthetic aliases such as usersim.signups+t@gmail.com.
This test scans every tracked file under the paths below and fails on anything that looks real.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCAN_PREFIXES = ("mvp/test_", "tests/", "mvp/fixtures/", "results/", "src/capability/test")

# mvp.signup_tools.gen_password(): 14 letters/digits + "!" + 2 digits + "Aa"
IDENTITY_PASSWORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{14}![1-9][0-9]Aa(?![A-Za-z0-9])")
# a live alias: usersim.signups+<site tag><6 hex> (new_signup) or a Gmail dot variant of the signup inbox
LIVE_ALIAS = re.compile(r"usersim\.?signups\+[a-z0-9]{0,12}[0-9a-f]{6}@gmail\.com", re.I)
# "password": "<literal>" in JSON / dicts; fakes must say so
PASSWORD_LITERAL = re.compile(r"""["'](?:password|passwd|signup_password)["']\s*:\s*["']([^"']{8,})["']""", re.I)
FAKE_MARKERS = re.compile(r"TEST|FAKE|NOT[-_ ]?REAL|REDACTED|EXAMPLE|DUMMY|<", re.I)
# provider token shapes
TOKENS = re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|bb_live_[A-Za-z0-9]{10,})\b")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        return []
    files = []
    for name in out.splitlines():
        if name.startswith(SCAN_PREFIXES) and not name.endswith((".png", ".jpg", ".gif", ".webp", ".pdf", ".zip", ".gz")):
            files.append(ROOT / name)
    return files


def findings(text: str) -> list[str]:
    out = []
    if IDENTITY_PASSWORD.search(text):
        out.append("signup_identity-format password")
    if LIVE_ALIAS.search(text):
        out.append("live usersim.signups alias (+<site><6 hex>)")
    for m in PASSWORD_LITERAL.finditer(text):
        if not FAKE_MARKERS.search(m.group(1)):
            out.append("password literal (use a runtime fake)")
            break
    if TOKENS.search(text):
        out.append("provider token")
    return out


def local_real_values() -> set[str]:
    """Passwords and aliases actually issued on this machine (run traces, driver logs, the dot-variant ledger).

    Absent in CI; on a dev box this catches a value copied from a real run even if its shape changes.
    """
    import glob
    import os

    values: set[str] = set()
    sources = [str(ROOT / "mvp" / "runs" / "*" / "*.json"), "/tmp/usersim-mcp-driver/logs/*.json"]
    sources += [s for s in os.environ.get("MVP_IDENTITY_SOURCES", "").split(os.pathsep) if s]
    for pattern in sources:
        for name in glob.glob(pattern)[:5000]:
            try:
                if os.path.getsize(name) > 20_000_000:
                    continue
                text = Path(name).read_text(errors="ignore")
            except OSError:
                continue
            for m in re.finditer(r'\\?"password\\?"\s*:\s*\\?"([^"\\]{8,})', text):
                if not FAKE_MARKERS.search(m.group(1)) and "*" not in m.group(1):
                    values.add(m.group(1))
            for m in LIVE_ALIAS.finditer(text):
                values.add(m.group(0).lower())
    ledger = os.path.expanduser(os.environ.get("MVP_GMAIL_VARIANTS_FILE") or "~/.cache/usersim/gmail_variants_used.txt")
    try:
        for line in Path(ledger).read_text(errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2 and "." in parts[1] and parts[1].replace(".", "").lower() == "usersimsignups":
                values.add(parts[1].lower() + "@gmail.com")
    except OSError:
        pass
    return values


class NoRealIdentityTests(unittest.TestCase):
    def test_detector_catches_real_shapes_and_allows_fakes(self):
        import secrets

        from mvp.signup_tools import gen_password

        self.assertTrue(findings(f'pw = "{gen_password()}"'))
        self.assertTrue(findings("usersim.signups+formbold" + secrets.token_hex(3) + "@gmail.com"))
        self.assertTrue(findings('{"password": "' + secrets.token_urlsafe(16) + '"}'))
        self.assertFalse(findings('{"password": "TEST-PASSWORD-NOT-REAL"}'))
        self.assertFalse(findings("usersim.signups+t@gmail.com usersim.signups@gmail.com"))

    def test_no_real_identity_in_tests_fixtures_or_results(self):
        files = tracked_files()
        if not files:
            self.skipTest("not a git checkout")
        bad = []
        for path in files:
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for what in findings(text):
                bad.append(f"{path.relative_to(ROOT)}: {what}")  # never print the value itself
        self.assertEqual(bad, [], "real-looking identity data committed; replace it with runtime fakes:\n" + "\n".join(bad))

    def test_no_value_from_a_local_real_run_is_committed(self):
        files = tracked_files()
        real = local_real_values()
        if not files or not real:
            self.skipTest("no local run artifacts or not a git checkout")
        bad = []
        for path in files:
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            low = text.lower()
            hits = sum(1 for v in real if (v in low if "@" in v else v in text))
            if hits:
                bad.append(f"{path.relative_to(ROOT)}: {hits} value(s) from a real run")  # counts only, never values
        self.assertEqual(bad, [], "values issued to a real signup are committed:\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
