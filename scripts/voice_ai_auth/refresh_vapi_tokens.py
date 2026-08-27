#!/usr/bin/env python3
"""CLI wrapper around capability.voice_ai_dashboards.refresh_vapi_workos_session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability.voice_ai_dashboards import refresh_vapi_workos_session


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client-id", default="client_01JS5DFXFQRR9DVGVCG18WKT2T")
    ap.add_argument("--organization-id", default=None)
    args = ap.parse_args()
    info = refresh_vapi_workos_session(
        client_id=args.client_id,
        organization_id=args.organization_id,
    )
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
