#!/usr/bin/env python3
"""Debug Notion signup code IMAP matching."""
from __future__ import annotations

import email
import imaplib
import json
import time
from pathlib import Path

from mvp.email_codes import (
    _CODE_RE,
    _SIGNUP_HINTS,
    _alias_match,
    _body_text,
    _decode,
    _find_code,
    _imap_creds,
    _recipients,
    latest_signup_code,
)


def main() -> None:
    user, pw = _imap_creds()
    print("user", user)
    alias = "shreyashfs+notion@gmail.com"
    ids_path = Path("secrets/identities.json")
    if ids_path.is_file():
        idsj = json.loads(ids_path.read_text())
        prod = (idsj.get("products") or {}).get("notion.so") or {}
        print("identity email", prod.get("email"))
        if prod.get("email"):
            alias = prod["email"]

    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(user, pw.replace(" ", ""))
    M.select("INBOX")
    typ, data = M.search(None, "ALL")
    ids = data[0].split()[-100:]
    hits = 0
    for mid in reversed(ids):
        typ, raw = M.fetch(mid, "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        rec = _recipients(msg)
        if "notion" not in rec and not _alias_match(rec, alias):
            continue
        sub = _decode(msg.get("Subject"))
        body = _body_text(msg)
        low = f"{sub}\n{body}".lower()
        print(
            "HIT",
            sub[:90],
            "| alias",
            _alias_match(rec, alias),
            "| hints",
            any(h in low for h in _SIGNUP_HINTS),
            "| code_re",
            bool(_CODE_RE.search(low)),
            "| find",
            _find_code(sub, body),
            "| to",
            rec[:140],
        )
        hits += 1
        if hits >= 8:
            break
    print("latest_signup_code", latest_signup_code(alias, newer_than=time.time() - 7200))
    M.logout()


if __name__ == "__main__":
    main()
