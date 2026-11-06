"""Daily backtest.

Timing rule (this is what stops look-ahead bias):
  * A signal on today's row may use today's close and anything older.
  * The order is filled at the NEXT day's open, not at today's close.
  * If the signal is on the last row, there is no next open, so it does not trade.

Long only, no leverage, no shorting. 1 means "be fully invested". 0 or a missing
value means "be in cash". Cash earns 0%. A position still open at the end is
marked at the last close and is not charged an exit fee, because the coins
were not sold.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_lab.assumptions import FEE_RATE, INITIAL_CASH, SLIPPAGE_RATE
from crypto_lab.metrics import compute_metrics


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list
    metrics: dict
    held: np.ndarray
    final_cash: float = 0.0
    final_units: float = 0.0


def run_backtest(
    bars: pd.DataFrame,
    signal: pd.Series,
    initial_cash: float = INITIAL_CASH,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
) -> BacktestResult:
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must be indexed by date")
    sig = pd.Series(signal, index=getattr(signal, "index", None)).reindex(bars.index)
    sig_values = sig.to_numpy(dtype=float)
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    cash = float(initial_cash)
    units = 0.0
    equity = np.empty(n)
    held = np.zeros(n)
    trades: list[dict] = []
    open_trade = None
    dates = bars.index

    for i in range(n):
        if i > 0 and not np.isnan(sig_values[i - 1]):
            want_long = sig_values[i - 1] >= 0.5
            is_long = units > 0
            if want_long and not is_long and cash > 0:
                price = opens[i] * (1.0 + slippage_rate)
                if price > 0:
                    cash_in = cash
                    units = cash_in * (1.0 - fee_rate) / price
                    cash = 0.0
                    open_trade = {
                        "entry_date": dates[i],
                        "entry_price": price,
                        "cash_in": cash_in,
                    }
            elif (not want_long) and is_long:
                price = opens[i] * (1.0 - slippage_rate)
                cash = units * price * (1.0 - fee_rate)
                trades.append(
                    {
                        "entry_date": open_trade["entry_date"],
                        "exit_date": dates[i],
                        "entry_price": open_trade["entry_price"],
                        "exit_price": price,
                        "return": cash / open_trade["cash_in"] - 1.0,
                        "closed": True,
                    }
                )
                units = 0.0
                open_trade = None
        equity[i] = cash + units * closes[i]
        held[i] = 1.0 if units > 0 else 0.0

    if open_trade is not None:
        marked = units * closes[-1]
        trades.append(
            {
                "entry_date": open_trade["entry_date"],
                "exit_date": dates[-1],
                "entry_price": open_trade["entry_price"],
                "exit_price": float(closes[-1]),
                "return": marked / open_trade["cash_in"] - 1.0,
                "closed": False,
            }
        )

    equity_s = pd.Series(equity, index=dates, name="equity")
    return BacktestResult(
        equity=equity_s,
        trades=trades,
        metrics=compute_metrics(equity_s, trades, held),
        held=held,
        final_cash=cash,
        final_units=units,
    )


def run_dca(
    bars: pd.DataFrame,
    weeks: int = 52,
    step_days: int = 7,
    initial_cash: float = INITIAL_CASH,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
) -> BacktestResult:
    """Spend a fixed slice of the starting cash every `step_days` bars.

    The first buy is on the second bar, the same open a close-based signal
    would be allowed to use. Each slice is initial_cash / weeks. If the price
    history ends early, the leftover cash stays in cash. Slices are not
    resized. This is the "I already have the money, should I spread it out?"
    question, not a plan that adds new salary every month.
    """
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    n = len(bars)
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    cash = float(initial_cash)
    units = 0.0
    slice_cash = float(initial_cash) / float(weeks)
    equity = np.empty(n)
    held = np.zeros(n)
    trades: list[dict] = []
    next_buy = 1 if n > 1 else 0
    buys_done = 0
    dates = bars.index

    for i in range(n):
        if i == next_buy and buys_done < weeks and cash > 1e-9:
            spend = min(slice_cash, cash)
            price = opens[i] * (1.0 + slippage_rate)
            if price > 0 and spend > 0:
                units += spend * (1.0 - fee_rate) / price
                cash -= spend
                trades.append(
                    {
                        "entry_date": dates[i],
                        "exit_date": dates[-1],
                        "entry_price": price,
                        "exit_price": None,
                        "return": None,
                        "closed": False,
                        "cash_in": spend,
                    }
                )
                buys_done += 1
            next_buy += step_days
        equity[i] = cash + units * closes[i]
        held[i] = 1.0 if units > 0 else 0.0

    final_close = float(closes[-1]) if n else 0.0
    for trade in trades:
        bought = trade["cash_in"] * (1.0 - fee_rate) / trade["entry_price"]
        trade["exit_price"] = final_close
        trade["return"] = (bought * final_close) / trade["cash_in"] - 1.0

    equity_s = pd.Series(equity, index=dates, name="equity")
    return BacktestResult(
        equity=equity_s,
        trades=trades,
        metrics=compute_metrics(equity_s, trades, held),
        held=held,
        final_cash=cash,
        final_units=units,
    )
