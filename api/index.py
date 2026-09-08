"""Vercel serverless entrypoint for UserSim MVP."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("VERCEL", "1")

# Vercel Lambda FS is read-only except /tmp. browser-use / Playwright / auth
# libraries otherwise try ~/.config and crash with Errno 30.
if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    tmp = Path("/tmp/usersim-home")
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / ".config").mkdir(parents=True, exist_ok=True)
    (tmp / ".cache").mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(tmp)
    os.environ.setdefault("TMPDIR", "/tmp")
    os.environ.setdefault("XDG_CONFIG_HOME", str(tmp / ".config"))
    os.environ.setdefault("XDG_CACHE_HOME", str(tmp / ".cache"))
    os.environ.setdefault("XDG_DATA_HOME", str(tmp / ".local" / "share"))
    Path(os.environ["XDG_DATA_HOME"]).mkdir(parents=True, exist_ok=True)

from mvp.server import app  # noqa: E402

# vercel dev uses ASGI `app` directly; production Lambda needs Mangum.
if os.environ.get("VERCEL_ENV") == "development":
    handler = app
else:
    from mangum import Mangum  # noqa: E402

    handler = Mangum(app, lifespan="off")
