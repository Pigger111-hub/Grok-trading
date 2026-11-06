#!/usr/bin/env python3
"""Backtest every strategy and refresh results/. Needs data/cache already downloaded."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.research import run_research  # noqa: E402


def main() -> None:
    run_research()


if __name__ == "__main__":
    main()
