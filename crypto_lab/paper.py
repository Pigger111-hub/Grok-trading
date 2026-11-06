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
from crypto_lab.timeframes import hold_daily_signal

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


def _stamp(value) -> str:
    ts = pd.Timestamp(value)
    if ts == ts.normalize():
        return ts.date().isoformat()
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


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


def _run_clock(daily_bars, intraday_bars, strategy_id: str, params: dict, timeframe: str, start: str):
    """`1d` on a 4-hour tape changes position only after the daily close."""
    if intraday_bars is None or timeframe == "4h":
        bars = daily_bars if intraday_bars is None else intraday_bars
        return _run_one(bars, strategy_id, params, start), bars
    start_i = _start_index(intraday_bars, start)
    window = intraday_bars.iloc[start_i:]
    if strategy_id == "buy_and_hold":
        return run_backtest(window, pd.Series(1.0, index=window.index)), intraday_bars
    daily_signal = STRATEGIES_BY_ID[strategy_id].generate(daily_bars, **params)
    held = hold_daily_signal(daily_signal, intraday_bars.index).iloc[start_i:]
    return run_backtest(window, held), intraday_bars


def sync_paper(
    conn: sqlite3.Connection,
    assets: dict[str, pd.DataFrame],
    start: str = PAPER_START,
    intraday: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Replace the paper book. Same candles produce the same rows.

    When 4-hour bars are provided, each selected strategy is simulated twice:
    once with a 4-hour signal, and once with the daily signal held flat until
    the next daily close. The job itself is expected to run every 4 hours.
    """
    specs = list(PAPER_BOOK) + [
        {
            "id": "buy_and_hold",
            "params": {},
            "why_th": "ตัวเทียบซื้อแล้วถือ ไม่ใช่กลยุทธ์ที่ถูกเลือก แต่ต้องมีไว้บนกราฟ",
        }
    ]
    clocks = ("1d", "4h") if intraday is not None else ("1d",)
    conn.execute("DELETE FROM paper_strategies")
    conn.execute("DELETE FROM paper_equity")
    conn.execute("DELETE FROM paper_trades")
    conn.execute("DELETE FROM paper_positions")
    conn.executemany(
        """
        INSERT INTO paper_strategies(strategy, timeframe, params, why_th, selected)
        VALUES(?, ?, ?, ?, ?)
        """,
        [
            (
                spec["id"],
                clock,
                json.dumps(spec["params"], sort_keys=True),
                spec["why_th"],
                0 if spec["id"] == "buy_and_hold" else 1,
            )
            for spec in specs
            for clock in clocks
            if not (spec["id"] == "buy_and_hold" and clock == "1d" and intraday is not None)
        ],
    )
    for asset, daily_bars in assets.items():
        intra = None if intraday is None else intraday[asset]
        for spec in specs:
            for clock in clocks:
                if spec["id"] == "buy_and_hold" and clock == "1d" and intraday is not None:
                    continue
                result, bars = _run_clock(daily_bars, intra, spec["id"], spec["params"], clock, start)
                conn.executemany(
                    "INSERT INTO paper_equity(asset, timeframe, strategy, date, equity) VALUES(?, ?, ?, ?, ?)",
                    [
                        (asset, clock, spec["id"], _stamp(day), float(value))
                        for day, value in result.equity.items()
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO paper_trades(
                        asset, timeframe, strategy, entry_date, exit_date, entry_price,
                        exit_price, return_pct, closed
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            asset,
                            clock,
                            spec["id"],
                            _stamp(trade["entry_date"]),
                            _stamp(trade["exit_date"]) if trade.get("exit_date") is not None else None,
                            trade.get("entry_price"),
                            trade.get("exit_price"),
                            trade.get("return"),
                            1 if trade.get("closed") else 0,
                        )
                        for trade in result.trades
                    ],
                )
                last_price = float(bars["close"].iloc[-1])
                conn.execute(
                    """
                    INSERT INTO paper_positions(
                        asset, timeframe, strategy, units, cash, last_price, market_value, side, as_of
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset,
                        clock,
                        spec["id"],
                        result.final_units,
                        result.final_cash,
                        last_price,
                        result.final_units * last_price,
                        "long" if result.final_units > 0 else "cash",
                        _stamp(bars.index[-1]),
                    ),
                )
