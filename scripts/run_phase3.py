#!/usr/bin/env python3
"""Round three: partial positions, luck checks, and stock entry timing.

Reads the cached BTC and ETH candles, downloads the stock funds from Yahoo
Finance, and writes results/trend_sizing.md, results/overfit.md and
results/stocks.md. Pass --offline to reuse the cached stock prices.

This does not connect to any account and does not place orders.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import load_cached  # noqa: E402
from crypto_lab.phase3 import run_phase3  # noqa: E402
from crypto_lab.stocks import load_stocks, update_stocks  # noqa: E402


def main() -> None:
    crypto = load_cached()
    stocks = load_stocks() if "--offline" in sys.argv else update_stocks()
    run_phase3(crypto, stocks)
    print("เสร็จแล้ว: results/trend_sizing.md, results/overfit.md, results/stocks.md")


if __name__ == "__main__":
    main()
