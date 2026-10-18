"""Run predict.py's context-only cells (B0, B1) on the v2 cases: same model, prompt and schema."""
import asyncio
import sys
from pathlib import Path

import predict

HERE = Path(__file__).resolve().parent
predict.PACKETS = HERE / "v2" / "packets"
predict.RESULTS = HERE / "v2" / "results"

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--cells", "B0,B1", "--cases", "all"]
    asyncio.run(predict.main())
