"""UserSim v0 config. Keep spend small: text candidates, no screenshots offline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"

GCP_PROJECT = "project-amer-scs-sandbox"
GCP_LOCATION = "us-central1"
GCP_ACCOUNT = "shreyas.patel@searce.com"
MODEL = "gemini-2.5-flash"
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
