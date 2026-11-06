#!/usr/bin/env python3
"""One command: prices, backtests, parameter sweep, paper book, dashboard.

This does not connect to an exchange account and does not place orders.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from crypto_lab.data import load_4h, update_all  # noqa: E402
from crypto_lab.db import connect  # noqa: E402
from crypto_lab.paper import sync_paper  # noqa: E402
from crypto_lab.publish import publish, run_sweep_and_sheets, save_backtests  # noqa: E402
from crypto_lab.research import persist_summary, run_research  # noqa: E402


def main() -> None:
    daily = update_all()
    intraday = load_4h()
    summaries = [
        run_research(daily, timeframe="1d", write_summary=False),
        run_research(intraday, timeframe="4h", write_summary=False),
    ]
    summary = pd.concat(summaries, ignore_index=True)
    persist_summary(summary)
    conn = connect()
    save_backtests(conn, summary)
    sweeps = [
        run_sweep_and_sheets(conn, daily, timeframe="1d"),
        run_sweep_and_sheets(conn, intraday, timeframe="4h"),
    ]
    from crypto_lab.sweep import render_sweep_markdown

    (ROOT / "results" / "sweep.md").write_text(
        render_sweep_markdown(pd.concat(sweeps, ignore_index=True)),
        encoding="utf-8",
    )
    sync_paper(conn, daily, intraday=intraday)
    publish(conn, daily, intraday)
    print("เสร็จแล้ว: รายวันและ 4 ชั่วโมง, สมุดกระดาษ, และ docs/index.html")


if __name__ == "__main__":
    main()
