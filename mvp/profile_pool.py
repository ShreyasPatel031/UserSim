"""Per-agent clones of a signed-in Chrome profile.

Transplanting cookies into a fresh browser no longer authenticates Google:
Chrome binds session cookies to the profile (device-bound session
credentials), so a copied ``LOGIN_INFO``/``SID`` set yields ``LOGGED_IN:
false`` even though every cookie is present. Cloning the profile directory
carries the binding material along, which does authenticate.

Chrome also refuses to share one ``user_data_dir`` across processes, so each
parallel agent needs its own clone. Caches are skipped — they are ~85% of the
bytes and none of the auth.

Profiles live under ``secrets/product_profiles/{host}/`` (any product) with
legacy aliases for the YouTube/Google profile used by early experiments.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
PRODUCT_PROFILES = SECRETS / "product_profiles"

# Legacy aliases kept so existing YouTube sessions keep working.
_LEGACY_PROFILES: dict[str, Path] = {
    "youtube.com": SECRETS / "youtube_browser_profile",
    "google.com": SECRETS / "youtube_browser_profile",
    "gmail.com": SECRETS / "youtube_browser_profile",
}

# Back-compat for anything that still imports PROFILES.
PROFILES: dict[str, Path] = dict(_LEGACY_PROFILES)

# Caches and models: large, regenerable, and irrelevant to being signed in.
_SKIP = {
    "Cache",
    "Code Cache",
    "Service Worker",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GraphiteDawnCache",
    "BrowserMetrics",
    "component_crx_cache",
    "optimization_guide_model_store",
    "OnDeviceHeadSuggestModel",
    "WasmTtsEngine",
    "Safe Browsing",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
}


def _safe_host(host: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "_", (host or "").lower())


def _normalize_host(url_or_host: str) -> str:
    host = (urlparse(url_or_host).hostname or url_or_host or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def profile_for_url(url: str) -> Path | None:
    """Signed-in profile that covers this URL, if one has been captured."""
    host = _normalize_host(url)
    if not host:
        return None

    # Exact product profile from auto_signup.
    candidate = PRODUCT_PROFILES / _safe_host(host)
    if candidate.is_dir() and any(candidate.iterdir()):
        return candidate

    # Also try www-prefixed / bare variants that may have been stored.
    for variant in (f"www.{host}", host):
        path = PRODUCT_PROFILES / _safe_host(variant)
        if path.is_dir() and any(path.iterdir()):
            return path

    # Legacy YouTube / Google aliases.
    for key, path in _LEGACY_PROFILES.items():
        if key in host and path.is_dir():
            return path

    # Subdomain match: app.linear.app → linear.app profile.
    parts = host.split(".")
    for i in range(1, max(1, len(parts) - 1)):
        parent = ".".join(parts[i:])
        path = PRODUCT_PROFILES / _safe_host(parent)
        if path.is_dir() and any(path.iterdir()):
            return path
        for key, legacy in _LEGACY_PROFILES.items():
            if key == parent and legacy.is_dir():
                return legacy
    return None


def clone_profile(source: Path, dest: Path | None = None) -> Path:
    """Copy the auth-bearing parts of ``source`` into a fresh directory."""
    dest = dest or Path(tempfile.mkdtemp(prefix="usersim_profile_"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        dest,
        dirs_exist_ok=True,
        symlinks=True,
        ignore=shutil.ignore_patterns(*_SKIP),
    )
    # A leftover lock makes Chrome think the profile is already open.
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        target = dest / lock
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except OSError:
                pass
    return dest


def clone_for_url(url: str) -> Path | None:
    """Disposable signed-in profile for this URL, or None when unavailable."""
    source = profile_for_url(url)
    if not source:
        return None
    try:
        return clone_profile(source)
    except Exception:
        return None


def discard(path: Path | None) -> None:
    if path and str(path).startswith(tempfile.gettempdir()):
        shutil.rmtree(path, ignore_errors=True)


def register_profile(host: str, path: Path) -> Path:
    """Ensure ``path`` is the canonical product profile for ``host``."""
    dest = PRODUCT_PROFILES / _safe_host(_normalize_host(host))
    if path.resolve() == dest.resolve():
        dest.mkdir(parents=True, exist_ok=True)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    if path.is_dir():
        shutil.copytree(path, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*_SKIP))
    else:
        dest.mkdir(parents=True, exist_ok=True)
    return dest
