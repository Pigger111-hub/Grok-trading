#!/usr/bin/env python3
"""Refresh public candles, extend the paper book, rebuild the dashboard.

Safe to run over and over. Does not place orders and does not rerun the full
research sweep. Used by GitHub Actions.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import load_cached  # noqa: E402
from crypto_lab.db import connect  # noqa: E402
from crypto_lab.market import refresh_cached_prices  # noqa: E402
from crypto_lab.paper import sync_paper  # noqa: E402
from crypto_lab.publish import publish  # noqa: E402


def main() -> None:
    assets = refresh_cached_prices(load_cached())
    conn = connect()
    sync_paper(conn, assets)
    publish(conn, assets)
    print("อัปเดตสมุดกระดาษและแดชบอร์ดแล้ว")


if __name__ == "__main__":
    main()
