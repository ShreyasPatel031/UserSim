"""Email the finished report to whoever asked for it on the waiting screen.

The page captured an address and promised "we'll send it when the study
finishes", but nothing ever sent anything: the address only reached
sessionStorage and no server code sent mail. This is that sender.

Uses the Gmail account already configured for signup inboxes
(GMAIL_USER / GMAIL_APP_PASSWORD), so there is no new credential to set up.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

PROD_BASE_URL = "https://usersim.vercel.app"

_SENT: set[str] = set()


def _creds() -> tuple[str, str]:
    return (
        (os.environ.get("GMAIL_USER") or "").strip(),
        (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip(),
    )


def email_configured() -> bool:
    user, password = _creds()
    return bool(user and password)


def report_base_url() -> str:
    """Where the recipient can open the report: a public URL, never localhost."""
    explicit = os.environ.get("MVP_PUBLIC_BASE_URL") or os.environ.get("MVP_REPORT_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    vercel_host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
    if vercel_host:
        return f"https://{vercel_host}".rstrip("/")
    return PROD_BASE_URL


def _product_name(url: str) -> str:
    host = (urlsplit(url or "").hostname or "").removeprefix("www.")
    return host.split(".")[0].title() if host else "your product"


def _recipient_name(email: str) -> str:
    local = (email or "").split("@")[0]
    parts = [p for p in local.replace(".", " ").replace("_", " ").split() if p.isalpha()]
    return " ".join(p.title() for p in parts[:2]) if parts else ""


def _headline(summary: Any) -> str:
    if isinstance(summary, dict):
        for key in ("headline", "verdict"):
            text = str(summary.get(key) or "").strip()
            if text:
                return text
    return ""


def build_message(study: Any, to_email: str) -> EmailMessage:
    url = str(getattr(study, "url", "") or "")
    product = _product_name(url)
    name = _recipient_name(to_email)
    link = f"{report_base_url()}/report?study={getattr(study, 'id', '')}"
    headline = _headline(getattr(study, "summary", None))

    subject = f"{name}, good news — your {product} report is in" if name else f"Your {product} report is in"

    lines = [
        f"Hi{' ' + name.split()[0] if name else ''},",
        "",
        f"Good news — the simulated user study on {url or product} has finished and the report is ready.",
    ]
    if headline:
        lines += ["", f"The short version: {headline}"]
    lines += [
        "",
        f"Read it here: {link}",
        "",
        "It covers what each simulated buyer tried to do, where they got stuck,",
        "and how the product compared with its competitors — every claim backed",
        "by the screenshot from the step it came from.",
        "",
        "— UserSim",
    ]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _creds()[0]
    msg["To"] = to_email
    msg.set_content("\n".join(lines))
    return msg


def send_report_email(study: Any, to_email: str | None = None) -> bool:
    """Send the finished report. Returns True when a mail actually went out."""
    to_email = (to_email or getattr(study, "email", "") or "").strip()
    study_id = str(getattr(study, "id", "") or "")
    if not to_email or "@" not in to_email:
        return False
    key = f"{study_id}:{to_email.lower()}"
    if key in _SENT:
        return False
    user, password = _creds()
    if not user or not password:
        print(
            "report email skipped: set GMAIL_USER and GMAIL_APP_PASSWORD to send",
            flush=True,
        )
        return False
    msg = build_message(study, to_email)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        print(f"report email to {to_email} failed: {exc!r}", flush=True)
        return False
    _SENT.add(key)
    print(f"report email sent to {to_email} for study {study_id[:8]}", flush=True)
    return True
