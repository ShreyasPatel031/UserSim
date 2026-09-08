#!/usr/bin/env python3
"""Download public raw sources for the 8B-Base SFT pilot corpus.

- OpenPsychometrics BIG5 (~19.7k) → data/fm_train/raw/BIG5/
- Mei et al. ChatGPT-Behavioral game CSVs → data/fm_train/raw/
"""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "fm_train" / "raw"
BIG5_URL = "https://openpsychometrics.org/_rawdata/BIG5.zip"
MEI_REPO = "https://github.com/yutxie/ChatGPT-Behavioral.git"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    zpath = RAW / "BIG5.zip"
    if not (RAW / "BIG5" / "data.csv").exists():
        print("fetching BIG5…", flush=True)
        urlretrieve(BIG5_URL, zpath)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(RAW)

    mei = RAW / "_mei_clone"
    need = [
        "dictator.csv",
        "bomb_risk.csv",
        "public_goods_linear_water.csv",
        "push_pull.csv",
        "trust_investment.csv",
        "ultimatum_strategy.csv",
        "bigfive_data.csv",
    ]
    if not all((RAW / n).exists() for n in need):
        print("cloning Mei ChatGPT-Behavioral…", flush=True)
        if mei.exists():
            subprocess.run(["rm", "-rf", str(mei)], check=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", MEI_REPO, str(mei)],
            check=True,
        )
        for n in need:
            src = mei / "data" / n
            if src.exists():
                dest = RAW / n
                dest.write_bytes(src.read_bytes())
                print("copied", n, flush=True)
        subprocess.run(["rm", "-rf", str(mei)], check=True)

    print("raw ready:", RAW, flush=True)
    for p in sorted(RAW.iterdir()):
        if p.is_file():
            print(f"  {p.name:40s} {p.stat().st_size:10d}")


if __name__ == "__main__":
    main()
