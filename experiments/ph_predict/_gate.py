"""Finds the fetch gateway for the VM scripts: the repo's src/ when run from a checkout, /opt/fetchgate/src on the VM
(where FETCHGATE_URL points the calls at the gateway service, which alone holds the proxy credentials)."""
import sys
from pathlib import Path

for p in (Path(__file__).resolve().parents[2] / "src", Path("/opt/fetchgate/src")):
    if (p / "fetchgate").is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fetchgate  # noqa: E402,F401
