#!/usr/bin/env python3
"""Refresh public candles, extend the paper book, rebuild the dashboard.

Safe to run over and over. Does not place orders and does not rerun the full
research sweep. Used by GitHub Actions.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import load_4h, load_cached  # noqa: E402
from crypto_lab.db import connect  # noqa: E402
from crypto_lab.market import refresh_cached_prices  # noqa: E402
from crypto_lab.paper import sync_paper  # noqa: E402
from crypto_lab.publish import publish  # noqa: E402


def main() -> None:
    # Walk forward from the last cached bar. A short limit used to drop
    # candles when a scheduled run was skipped, and a stale coin still
    # exited 0. refresh_cached_prices raises if either coin is behind.
    daily = refresh_cached_prices(load_cached(), timeframe="1d")
    intraday = refresh_cached_prices(load_4h(), timeframe="4h")
    conn = connect()
    sync_paper(conn, daily, intraday=intraday)
    publish(conn, daily, intraday)
    print("อัปเดตสมุดกระดาษทุก 4 ชั่วโมงแล้ว กลยุทธ์รายวันเปลี่ยนเฉพาะหลังแท่งวันปิด")


if __name__ == "__main__":
    main()
