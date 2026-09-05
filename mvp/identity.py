"""Deterministic signup identity per product host.

Each product gets a stable Gmail plus-alias (``you+notion@gmail.com``) and a
generated password, stored in ``secrets/identities.json`` so re-runs reuse the
same account instead of creating duplicates. Base email / phone / name come
from the existing credential vault.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mvp.credentials import _load_vault, credentials_for_url

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
REGISTRY = SECRETS / "identities.json"
PRODUCT_PROFILES = SECRETS / "product_profiles"


@dataclass
class Identity:
    host: str
    email: str
    password: str
    full_name: str
    company: str
    phone: str
    alias_tag: str
    status: str = "provisioned"  # provisioned | signed_up | blocked
    blocker: str | None = None
    profile_dir: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Safe to log — never includes password."""
        return {
            "host": self.host,
            "email": self.email,
            "full_name": self.full_name,
            "company": self.company,
            "phone": bool(self.phone),
            "alias_tag": self.alias_tag,
            "status": self.status,
            "blocker": self.blocker,
            "profile_dir": self.profile_dir,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def safe_host(host: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "_", (host or "").lower())


def host_for_url(url: str) -> str:
    host = (urlparse(url).hostname or url or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def alias_tag_for_host(host: str) -> str:
    """Turn ``linear.app`` into a Gmail-safe plus-tag ``linear``."""
    base = host.split(".")[0] if host else "product"
    tag = re.sub(r"[^a-z0-9]", "", base.lower())
    return (tag or "product")[:32]


def _generate_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    # Guarantee mixed classes so sites with silly password rules accept it.
    parts = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*-_"),
    ]
    parts += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(parts)
    return "".join(parts)


def _base_identity_fields() -> dict[str, str]:
    vault = _load_vault()
    # Prefer the Google vault entry (has username/phone); fall back to any site.
    sites = vault.get("sites") or []
    google = next(
        (
            s
            for s in sites
            if any("google" in (p or "").lower() or "gmail" in (p or "").lower() for p in (s.get("match") or []))
        ),
        sites[0] if sites else {},
    )
    username = (google.get("username") or "").strip()
    phone = (google.get("phone") or "").strip()
    # Optional owner profile fields in vault root.
    owner = vault.get("owner") or {}
    full_name = (owner.get("full_name") or "Shreyas Patel").strip()
    company = (owner.get("company") or "UserSim").strip()
    return {
        "username": username,
        "phone": phone,
        "full_name": full_name,
        "company": company,
    }


def _load_registry() -> dict[str, Any]:
    if not REGISTRY.is_file():
        return {"products": {}}
    try:
        data = json.loads(REGISTRY.read_text())
    except Exception:
        return {"products": {}}
    if not isinstance(data, dict):
        return {"products": {}}
    data.setdefault("products", {})
    return data


def _save_registry(data: dict[str, Any]) -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, indent=2) + "\n")


def _from_dict(host: str, raw: dict[str, Any]) -> Identity:
    return Identity(
        host=host,
        email=raw["email"],
        password=raw["password"],
        full_name=raw.get("full_name") or "Shreyas Patel",
        company=raw.get("company") or "UserSim",
        phone=raw.get("phone") or "",
        alias_tag=raw.get("alias_tag") or alias_tag_for_host(host),
        status=raw.get("status") or "provisioned",
        blocker=raw.get("blocker"),
        profile_dir=raw.get("profile_dir"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def get_identity(url: str) -> Identity | None:
    host = host_for_url(url)
    raw = _load_registry().get("products", {}).get(host)
    if not raw:
        return None
    return _from_dict(host, raw)


def list_identities() -> list[Identity]:
    products = _load_registry().get("products") or {}
    return [_from_dict(h, raw) for h, raw in sorted(products.items())]


def provision_identity(url: str) -> Identity:
    """Return existing identity for this host, or create and persist a new one."""
    from datetime import datetime, timezone

    host = host_for_url(url)
    if not host:
        raise ValueError(f"Cannot derive host from url={url!r}")

    existing = get_identity(url)
    if existing:
        return existing

    base = _base_identity_fields()
    if not base["username"] or "@" not in base["username"]:
        raise RuntimeError(
            "No base email in secrets/credentials.json — add a vault site with username"
        )
    local, domain = base["username"].rsplit("@", 1)
    tag = alias_tag_for_host(host)
    email = f"{local}+{tag}@{domain}"
    now = datetime.now(timezone.utc).isoformat()
    profile = PRODUCT_PROFILES / safe_host(host)
    identity = Identity(
        host=host,
        email=email,
        password=_generate_password(),
        full_name=base["full_name"],
        company=base["company"],
        phone=base["phone"],
        alias_tag=tag,
        status="provisioned",
        profile_dir=str(profile),
        created_at=now,
        updated_at=now,
    )
    data = _load_registry()
    data["products"][host] = asdict(identity)
    _save_registry(data)
    return identity


def update_identity(url: str, **fields: Any) -> Identity:
    from datetime import datetime, timezone

    host = host_for_url(url)
    data = _load_registry()
    raw = data.get("products", {}).get(host)
    if not raw:
        raise KeyError(f"No identity for host={host}")
    for key, value in fields.items():
        if key == "password":
            continue  # never overwrite via public update path accidentally
        if key in raw or key in {
            "status",
            "blocker",
            "profile_dir",
            "full_name",
            "company",
            "phone",
        }:
            raw[key] = value
    raw["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["products"][host] = raw
    _save_registry(data)
    return _from_dict(host, raw)


def credentials_exist_for_url(url: str) -> bool:
    """True when the vault already has a sign-in entry for this host."""
    return credentials_for_url(url) is not None


def profile_path_for_host(host: str) -> Path:
    return PRODUCT_PROFILES / safe_host(host)
