"""Vercel serverless entrypoint for UserSim MVP."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("VERCEL", "1")

# Materialize Vertex ADC from env before any Gemini calls (secrets/ is not deployed).
try:
    from auth import _materialize_adc_from_env

    _materialize_adc_from_env()
except Exception:
    pass

from mvp.server import app  # noqa: E402

# vercel dev uses ASGI `app` directly; production Lambda needs Mangum.
if os.environ.get("VERCEL_ENV") == "development":
    handler = app
else:
    from mangum import Mangum  # noqa: E402

    handler = Mangum(app, lifespan="off")
