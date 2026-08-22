"""MVP filesystem paths (no heavy imports)."""

import os
from pathlib import Path

if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    MVP_RUNS_DIR = Path("/tmp/usersim-runs")
else:
    MVP_RUNS_DIR = Path(__file__).resolve().parent / "runs"
