#!/usr/bin/env python3
"""One command: refresh prices, then run every backtest.

This does not connect to an exchange account and does not place orders.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import update_all  # noqa: E402
from crypto_lab.research import run_research  # noqa: E402


def main() -> None:
    prices = update_all()
    run_research(prices)


if __name__ == "__main__":
    main()