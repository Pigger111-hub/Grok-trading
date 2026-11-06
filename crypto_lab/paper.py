"""Simulated paper book. Virtual cash only.

The book opens on PAPER_START with INITIAL_CASH per strategy and per coin.
Re-running on the same candles replaces those rows with the same rows, so the
job can be repeated or resumed after a crash. A new closed daily candle extends
the book. No exchange method that sends an order is called.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from crypto_lab.assumptions import PAPER_START
from crypto_lab.engine import run_backtest
from crypto_lab.research import backtest_window
from crypto_lab.strategies import STRATEGIES_BY_ID

# Chosen from round 1, not from the largest full-sample profit.
# Donchian made the most money on all of BTC and then lost the latest 30%.
# It is tracked on purpose so the paper book can show whether that continues.
PAPER_BOOK = (
    {
        "id": "sma_filter",
        "params": {"window": 200},
        "why_th": (
            "กลยุทธ์เดียวในรอบแรกที่กำไรรวมชนะซื้อแล้วถือ ทั้งช่วง 30% ท้าย "
            "และ walk-forward บนทั้ง BTC และ ETH"
        ),
    },
    {
        "id": "macd",
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "why_th": (
            "ชนะ walk-forward ทั้งสองเหรียญ แต่แพ้ช่วง 30% ท้ายด้วยค่าตามตำรา "
            "และแพ้ทั้งช่วงถ้าค่าธรรมเนียมขึ้นเป็น 0.50%"
        ),
    },
    {
        "id": "donchian",
        "params": {"entry": 20, "exit": 10},
        "why_th": (
            "กำไรทั้งช่วงของ BTC สูงสุดในรอบแรก แต่ช่วง 30% ท้ายแพ้ซื้อแล้วถือทั้ง BTC และ ETH "
            "ใส่ไว้ในสมุดกระดาษเพื่อดูว่าช่วงหลังจะเป็นอย่างที่นอกตัวอย่างบอกหรือไม่"
        ),
    },
)


def _date(value) -> str:
    return pd.Timestamp(value).date().isoformat()


def _start_index(bars: pd.DataFrame, start: str) -> int:
    position = int(bars.index.searchsorted(pd.Timestamp(start)))
    position = min(position, len(bars) - 1)
    return max(position - 1, 0)


def _run_one(bars: pd.DataFrame, strategy_id: str, params: dict, start: str):
    start_i = _start_index(bars, start)
    if strategy_id == "buy_and_hold":
        window = bars.iloc[start_i:]
        return run_backtest(window, pd.Series(1.0, index=window.index))
    strategy = STRATEGIES_BY_ID[strategy_id]
    result, _benchmark = backtest_window(bars, strategy, params, start_i, len(bars))
    return result


def sync_paper(
    conn: sqlite3.Connection,
    assets: dict[str, pd.DataFrame],
    start: str = PAPER_START,
) -> None:
    """Replace the paper book for every tracked strategy. Same candles, same rows."""
    specs = list(PAPER_BOOK) + [
        {
            "id": "buy_and_hold",
            "params": {},
            "why_th": "ตัวเทียบซื้อแล้วถือ ไม่ใช่กลยุทธ์ที่ถูกเลือก แต่ต้องมีไว้บนกราฟ",
        }
    ]
    conn.execute("DELETE FROM paper_strategies")
    conn.execute("DELETE FROM paper_equity")
    conn.execute("DELETE FROM paper_trades")
    conn.execute("DELETE FROM paper_positions")
    conn.executemany(
        "INSERT INTO paper_strategies(strategy, params, why_th, selected) VALUES(?, ?, ?, ?)",
        [
            (
                spec["id"],
                json.dumps(spec["params"], sort_keys=True),
                spec["why_th"],
                0 if spec["id"] == "buy_and_hold" else 1,
            )
            for spec in specs
        ],
    )
    for asset, bars in assets.items():
        for spec in specs:
            result = _run_one(bars, spec["id"], spec["params"], start)
            conn.executemany(
                "INSERT INTO paper_equity(asset, strategy, date, equity) VALUES(?, ?, ?, ?)",
                [
                    (asset, spec["id"], _date(day), float(value))
                    for day, value in result.equity.items()
                ],
            )
            conn.executemany(
                """
                INSERT INTO paper_trades(
                    asset, strategy, entry_date, exit_date, entry_price, exit_price, return_pct, closed
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        asset,
                        spec["id"],
                        _date(trade["entry_date"]),
                        _date(trade["exit_date"]) if trade.get("exit_date") is not None else None,
                        trade.get("entry_price"),
                        trade.get("exit_price"),
                        trade.get("return"),
                        1 if trade.get("closed") else 0,
                    )
                    for trade in result.trades
                ],
            )
            last_price = float(bars["close"].iloc[-1])
            market_value = result.final_units * last_price
            conn.execute(
                """
                INSERT INTO paper_positions(
                    asset, strategy, units, cash, last_price, market_value, side, as_of
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset,
                    spec["id"],
                    result.final_units,
                    result.final_cash,
                    last_price,
                    market_value,
                    "long" if result.final_units > 0 else "cash",
                    _date(bars.index[-1]),
                ),
            )
