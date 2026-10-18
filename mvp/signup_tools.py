"""Signup tools shared by the website driver and the MCP server.

Both paths get a fresh Gmail plus-alias inbox, identity fields and the
verification-mail waits from here, so they cannot drift apart again.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
import time
from typing import Any

# Personal inboxes that must never receive signup mail. Stored as sha256 of the
# dot-less local part so no personal address appears in the code.
_FORBIDDEN_LOCAL_SHA256 = {
    "6bec6e6afc1c78fd7bb2d6ec6573755994c61c3bd01c4a27ef0207edf06cd643",
}
ALLOWED_SIGNUP_LOCAL = "usersimsignups"


def _local(addr: str) -> str:
    local = (addr or "").split("@", 1)[0].split("+", 1)[0]
    return local.replace(".", "").lower()


def inbox_allowed(addr: str) -> bool:
    local = _local(addr)
    if hashlib.sha256(local.encode()).hexdigest() in _FORBIDDEN_LOCAL_SHA256:
        return False
    # The local part alone is not enough: usersim.signups+x@some-company.com is somebody else's mailbox
    # (Loop 15 AnnounceKit: the model invented a "work" address on a real-looking company domain).
    from mvp.identity import GMAIL_DOMAINS

    domain = (addr or "").rsplit("@", 1)[-1].strip().lower() if "@" in (addr or "") else ""
    if domain not in GMAIL_DOMAINS:
        return False
    import os

    allowed = (os.environ.get("MVP_SIGNUP_ALLOWED_LOCAL") or ALLOWED_SIGNUP_LOCAL).replace(".", "").lower()
    return local == allowed


def assert_signup_inbox() -> str:
    """Base inbox for signups. Raises unless it is the dedicated signup account."""
    from mvp.email_codes import _imap_creds

    creds = _imap_creds()
    if not creds:
        from mvp.signup_inbox import GMAIL_MISSING_MSG, GmailInboxMissing

        raise GmailInboxMissing(GMAIL_MISSING_MSG)
    if not inbox_allowed(creds[0]):
        raise RuntimeError("GMAIL_USER is not the dedicated signup inbox; refusing to sign up")
    return creds[0]


def gen_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(14))
    return f"{core}!{secrets.randbelow(90) + 10}Aa"


def identity_fields(persona: dict[str, Any] | None, email: str) -> dict[str, str]:
    persona = persona or {}
    raw = str(persona.get("full_name") or persona.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]+ [A-Za-z][A-Za-z'\-]+", raw):
        raw = "Sam Rivera"
    first, last = raw.split(" ", 1)
    role = str(persona.get("role") or persona.get("job") or "Product manager")[:40]
    company = str(persona.get("company") or "Rivera Labs")[:40]
    return {
        "email": email,
        "password": gen_password(),
        "full_name": raw,
        "first_name": first,
        "last_name": last,
        "company": company,
        "workspace": re.sub(r"[^a-z0-9]", "", company.lower())[:12] + secrets.token_hex(2),
        "role": role,
        # Letters+digits only, unique per signup: many sites reject spaces or taken names.
        "username": (first + last).lower()[:14] + secrets.token_hex(2),
        "code": "",
    }


def new_signup(site_host: str, tag: str, persona: dict[str, Any] | None = None, *, dotted: bool = False) -> tuple[Any, dict[str, str]]:
    """(inbox, identity) for one brand-new signup attempt on ``site_host``.

    ``dotted``: for sites that reject ``+`` aliases, a never-used Gmail dot variant of the same inbox.
    """
    from mvp.signup_inbox import create_inbox

    assert_signup_inbox()
    inbox = create_inbox(site_host, tag, dotted=dotted)
    if not inbox_allowed(inbox.address):
        raise RuntimeError("signup alias is not on the dedicated signup inbox")
    return inbox, identity_fields(persona, inbox.address)


def existing_signup(address: str) -> tuple[Any, dict[str, str]]:
    """(inbox, identity) for signing back in to an account made earlier on the signup inbox.

    Only aliases of the dedicated signup inbox are accepted. No password is returned: the caller
    already has it, and sites that mail a login link or new-device code are read from this inbox.
    """
    from mvp.signup_inbox import GmailAliasInbox

    assert_signup_inbox()
    if not inbox_allowed(address):
        raise RuntimeError("existing_email is not an alias of the dedicated signup inbox")
    inbox = GmailAliasInbox.for_address(address)
    return inbox, {"email": inbox.address}


def wait_mail(inbox: Any, host: str, *, since: float, timeout_s: float, seen: set[str],
              want: str = "any") -> dict[str, Any] | None:
    """Next verification mail for this alias: {subject, sender, code, links}.

    want="code" / "link" keeps waiting past mails that lack that part, without using them up: Reframe (Oct 14)
    mails a code and no link, the agent called wait_for_verification_link first, that call marked the code mail
    seen, and every later wait_for_verification_code found nothing while the code sat in the inbox.
    """
    deadline = time.time() + max(5.0, timeout_s)
    local = set(seen)
    skipped: set[str] = set()
    try:
        while time.time() < deadline:
            msg = inbox.wait(host, since, max(1.0, deadline - time.time()), local)
            if not msg:
                return None
            mid = str(msg.get("id") or msg.get("subject"))
            if (want == "code" and not msg.get("code")) or (want == "link" and not msg.get("links")):
                skipped.add(mid)
                continue
            return msg
        return None
    finally:
        seen |= local - skipped
