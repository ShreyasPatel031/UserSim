#!/usr/bin/env bash
# Enrich every collected launch, then backtest. Each step skips work already on disk.
set -euo pipefail
cd "$(dirname "$0")"
python3 crawl_sites.py 2026-01-01
python3 llm_scores.py
python3 external.py
python3 evaluate.py
