"""Materialize GCP creds from cloud-agent secrets. Never ask the user to paste.

Cloud boxes already inject:
  CLOUDSDK_CORE_PROJECT / GOOGLE_CLOUD_PROJECT / GCP_PROJECT / GCLOUD_PROJECT
  GOOGLE_APPLICATION_CREDENTIALS          (often a stub path that does not exist)
  GOOGLE_APPLICATION_CREDENTIALS_B64      (the actual key)
  GOOGLE_APPLICATION_CREDENTIALS_JSON     (optional raw JSON)

A missing file at GOOGLE_APPLICATION_CREDENTIALS is NOT "no creds".
Write ADC from _B64/_JSON, then gcloud auth activate-service-account.
Never print or commit the key.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ADC_FALLBACK = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

SECRET_ENV_NAMES = (
    "CLOUDSDK_CORE_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "GCP_PROJECT",
    "GCLOUD_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_APPLICATION_CREDENTIALS_B64",
    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
    "ZONE",
    "GCP_ZONE",
    "COMPUTE_ZONE",
    "WATCHDOG_ZONE",
)


def present_secret_names() -> list[str]:
    return [n for n in SECRET_ENV_NAMES if (os.environ.get(n) or "").strip()]


def project_id() -> str:
    for key in (
        "CLOUDSDK_CORE_PROJECT",
        "GOOGLE_CLOUD_PROJECT",
        "GCP_PROJECT",
        "GCLOUD_PROJECT",
    ):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    raise SystemExit(
        "PROTOCOL: GCP project env is missing "
        "(CLOUDSDK_CORE_PROJECT / GOOGLE_CLOUD_PROJECT). "
        "Do not ask the user to paste it — it should already be a secret."
    )


def zone() -> str:
    for key in ("ZONE", "GCP_ZONE", "COMPUTE_ZONE", "FM_FLOOR_ZONE"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return "".join(("us-", "central", "1-a"))


def watchdog_zone() -> str:
    for key in ("WATCHDOG_ZONE", "FM_WATCHDOG_ZONE"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return "".join(("us-", "central", "1-b"))


def region() -> str:
    z = zone()
    return z.rsplit("-", 1)[0] if z.count("-") >= 2 else z


def gcloud_bin() -> str:
    found = shutil.which("gcloud")
    if found:
        return found
    fallback = Path.home() / "google-cloud-sdk" / "bin" / "gcloud"
    if fallback.is_file():
        bin_dir = str(fallback.parent)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        return str(fallback)
    raise SystemExit(
        "PROTOCOL: gcloud binary missing. Install the SDK; "
        "do not ask the user for a key."
    )


def _usable_key_file(path: str) -> bool:
    p = Path(path)
    return p.is_file() and p.stat().st_size > 100


def _write_adc(raw: bytes) -> Path:
    dest = ADC_FALLBACK
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    dest.chmod(0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(dest)
    return dest


def ensure_adc() -> Path:
    """Write ADC from B64/JSON when GOOGLE_APPLICATION_CREDENTIALS is a stub."""
    path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if path and _usable_key_file(path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
        return Path(path)

    raw_json = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
    if raw_json:
        json.loads(raw_json)  # fail closed on garbage
        return _write_adc(raw_json.encode("utf-8"))

    b64 = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64") or "").strip()
    if not b64:
        raise SystemExit(
            "PROTOCOL: GOOGLE_APPLICATION_CREDENTIALS is a missing stub and "
            "GOOGLE_APPLICATION_CREDENTIALS_B64 / _JSON are unset. "
            "Use injected secrets; do not ask the user to paste a key. "
            f"present_env={present_secret_names()}"
        )
    return _write_adc(base64.b64decode(b64))


def gcloud_env() -> dict[str, str]:
    adc = ensure_adc()
    env = os.environ.copy()
    env["CLOUDSDK_CORE_PROJECT"] = project_id()
    env["GOOGLE_CLOUD_PROJECT"] = env["CLOUDSDK_CORE_PROJECT"]
    env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc)
    bin_dir = str(Path(gcloud_bin()).parent)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def activate_service_account() -> None:
    adc = ensure_adc()
    subprocess.run(
        [gcloud_bin(), "auth", "activate-service-account", f"--key-file={adc}", "--quiet"],
        check=True,
        env=gcloud_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    subprocess.run(
        [gcloud_bin(), "config", "set", "project", project_id(), "--quiet"],
        check=True,
        env=gcloud_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def gcloud(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    activate_service_account()
    cmd = [gcloud_bin(), *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, env=gcloud_env())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--export":
        p = ensure_adc()
        activate_service_account()
        print(f"export PROJECT={project_id()}")
        print(f"export ZONE={zone()}")
        print(f"export GOOGLE_APPLICATION_CREDENTIALS={p}")
        print(f"export PATH={Path(gcloud_bin()).parent}:$PATH")
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        adc = ensure_adc()
        activate_service_account()
        print(
            json.dumps(
                {
                    "ok": True,
                    "adc": str(adc),
                    "project": project_id(),
                    "zone": zone(),
                    "region": region(),
                    "present_env": present_secret_names(),
                    "gcloud": gcloud_bin(),
                },
                indent=2,
            )
        )
        sys.exit(0)
    raise SystemExit("usage: gcp_auth.py --export|--status")
