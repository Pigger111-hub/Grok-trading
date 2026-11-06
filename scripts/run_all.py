#!/usr/bin/env python3
"""One command: prices, backtests, parameter sweep, paper book, dashboard.

This does not connect to an exchange account and does not place orders.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crypto_lab.data import update_all  # noqa: E402
from crypto_lab.db import connect  # noqa: E402
from crypto_lab.paper import sync_paper  # noqa: E402
from crypto_lab.publish import publish, run_sweep_and_sheets, save_backtests  # noqa: E402
from crypto_lab.research import run_research  # noqa: E402


def main() -> None:
    prices = update_all()
    summary = run_research(prices)
    conn = connect()
    save_backtests(conn, summary)
    run_sweep_and_sheets(conn, prices)
    sync_paper(conn, prices)
    publish(conn, prices)
    print("เสร็จแล้ว: ตาราง, รายงาน QuantStats, สมุดกระดาษ, และ docs/index.html")


if __name__ == "__main__":
    main()
