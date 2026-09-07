"""UserSim v0 config. Keep spend small: text candidates, no screenshots offline."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    RESULTS_DIR = Path("/tmp/usersim-results")
else:
    RESULTS_DIR = ROOT / "results"

GCP_PROJECT = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or os.environ.get("GCLOUD_PROJECT")
    or ""
)
GCP_LOCATION = os.environ.get("VERTEX_LOCATION") or os.environ.get("GCP_LOCATION") or ""
GCP_ACCOUNT = os.environ.get("GOOGLE_CLOUD_ACCOUNT") or ""
MODEL = os.environ.get("MVP_SIGNUP_MODEL") or "gemini-2.5-flash"
# All capability / bakeoff agent + judge runs use MODEL (cheap). Do not default to 3.6.

# Vertex Gemini 2.5 Flash list prices (USD / 1M tokens). Used for spend tracking.
PRICE_INPUT_PER_M = 0.30
PRICE_OUTPUT_PER_M = 2.50

N_CANDIDATES = 50  # 1 gold + 49 distractors, Mind2Web-style
MAX_TRAJECTORIES = 40
MAX_STEPS_PER_TASK = 8
WORKERS = 8

RAW_TRAIN_JSON = DATA_DIR / "hf" / "data" / "train" / "train_0.json"
SLIM_JSON = DATA_DIR / "mind2web_v0.json"
