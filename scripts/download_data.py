#!/usr/bin/env python3
"""Download BTC and ETH history into data/cache. Safe to run again later."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import update_all  # noqa: E402


def main() -> None:
    update_all()


if __name__ == "__main__":
    main()
