"""Download SimBench Pop + Grouped pickles into data/simbench/."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download

from config import ROOT

DATA = ROOT / "data" / "simbench"
FILES = ("SimBenchPop.pkl", "SimBenchGrouped.pkl", "SimBenchPop.csv", "SimBenchGrouped.csv")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = hf_hub_download(
            "pitehu/SimBench",
            name,
            repo_type="dataset",
            local_dir=str(DATA),
        )
        size = Path(path).stat().st_size
        print(f"OK {name} ({size:,} bytes) -> {path}")
    print("\nNext: PYTHONPATH=src python -m human_sim.simbench_cost")


if __name__ == "__main__":
    main()
