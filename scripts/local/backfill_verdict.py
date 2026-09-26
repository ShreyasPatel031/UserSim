"""Write the verdict summary onto a finished study (local server copy and GCS).

Usage: backfill_verdict.py STUDY_ID [STUDY_ID ...]
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from mvp.report_insights import build_report_insights, write_verdict_summary  # noqa: E402


def main() -> None:
    from google.cloud import storage

    bucket = storage.Client().bucket("usersim-bakeoff-347838016394")
    for sid in sys.argv[1:]:
        blob = bucket.blob(f"mvp_studies/{sid}/study.json")
        data = json.loads(blob.download_as_text())
        insights = build_report_insights(data)
        text = asyncio.run(write_verdict_summary(data, insights))
        data.setdefault("summary", {})["verdict_summary"] = text
        blob.upload_from_string(json.dumps(data), content_type="application/json")
        local = ROOT / "results" / "mvp_studies" / sid / "study.json"
        if local.exists():
            local.write_text(json.dumps(data))
        print(sid, "->", text[:300])


if __name__ == "__main__":
    main()
