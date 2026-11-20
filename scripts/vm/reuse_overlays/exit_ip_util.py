#!/usr/bin/env python3
"""Append exit_ip rows to vm status jsonl (Population no-rotation audit)."""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import urllib.parse as up
import urllib.request
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_proxy_env() -> None:
    """Match supervisor_strat: proxy from metadata + optional port_override."""
    if os.environ.get("PROXY_URL"):
        po = pathlib.Path("/opt/ph/reuse/port_override")
        if po.is_file() and not os.environ.get("PROXY_PORT"):
            os.environ["PROXY_PORT"] = po.read_text().strip()
        return
    try:
        md = "http://metadata.google.internal/computeMetadata/v1/instance/attributes"
        hdr = {"Metadata-Flavor": "Google"}
        os.environ["PROXY_URL"] = urllib.request.urlopen(
            urllib.request.Request(f"{md}/proxy-url", headers=hdr), timeout=4
        ).read().decode()
        os.environ["PROXY_PORT"] = urllib.request.urlopen(
            urllib.request.Request(f"{md}/proxy-port", headers=hdr), timeout=4
        ).read().decode().strip()
        po = pathlib.Path("/opt/ph/reuse/port_override")
        if po.is_file():
            os.environ["PROXY_PORT"] = po.read_text().strip()
    except Exception:
        pass


def exit_info() -> dict:
    ensure_proxy_env()
    port = int(os.environ.get("PROXY_PORT", 0) or 0)
    o: dict = {"proxy_port": port, "ts": _now(), "exit_ip": None, "exit_asn": None, "exit_org": None}
    if not os.environ.get("PROXY_URL"):
        o["exit_err"] = "no_proxy_env"
        return o
    try:
        p = up.urlparse(os.environ["PROXY_URL"])
        pu = f"{p.scheme}://{p.username}:{p.password}@{p.hostname}:{port or p.port}"
        op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": pu, "https": pu}))
        d = json.loads(op.open("https://ipinfo.io/json", timeout=12).read())
        org = d.get("org") or ""
        o.update(
            exit_ip=d.get("ip"),
            exit_asn=(org.split(" ", 1)[0] if org.startswith("AS") else None),
            exit_org=(org.split(" ", 1)[1] if org.startswith("AS") and " " in org else org) or None,
            exit_country=d.get("country"),
        )
    except Exception as e:
        o["exit_err"] = type(e).__name__
    return o


def vm_name() -> str:
    return os.environ.get("VM") or socket.gethostname()


def status_path() -> str:
    return f"/opt/ph/reuse/status_{vm_name()}.jsonl"


def gcs_status_uri() -> str | None:
    root = os.environ.get("PACE_GCS_VM_ROOT", "").rstrip("/")
    if not root.startswith("gs://"):
        return None
    return f"{root}/status/{vm_name()}.jsonl"


def _append_status(path: str, line: str) -> None:
    try:
        with open(path, "a") as f:
            f.write(line)
    except PermissionError:
        subprocess.run(["sudo", "tee", "-a", path], input=line.encode(), check=False)


def _flush_status(path: str, uri: str) -> None:
    cmd = ["gsutil", "-q", "cp", path, uri]
    if os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    subprocess.run(cmd, check=False)


def log_event(event: str, note: str | None = None, flush: bool = True) -> dict:
    ei = exit_info()
    row = {"vm": vm_name(), "event": event, "utc": _now(), **ei}
    if note:
        row["note"] = note
    path = status_path()
    _append_status(path, json.dumps(row) + "\n")
    if flush:
        uri = gcs_status_uri()
        if uri:
            _flush_status(path, uri)
    return row


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: exit_ip_util.py log <event> [note]", file=sys.stderr)
        return 2
    if sys.argv[1] == "log":
        ev = sys.argv[2]
        note = sys.argv[3] if len(sys.argv) > 3 else None
        row = log_event(ev, note=note)
        print(json.dumps(row))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())