"""Daily backtest.

Timing rule (this is what stops look-ahead bias):
  * A signal on today's row may use today's close and anything older.
  * The order is filled at the NEXT day's open, not at today's close.
  * If the signal is on the last row, there is no next open, so it does not trade.

Long only, no leverage, no shorting. 1 means "be fully invested". 0 or a missing
value means "be in cash". Cash earns 0% unless the caller passes
cash_annual_yield. A position still open at the end is marked at the last close
and is not charged an exit fee, because the coins were not sold.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_lab.assumptions import CASH_ANNUAL_YIELD, FEE_RATE, INITIAL_CASH, PERIODS_PER_YEAR, SLIPPAGE_RATE
from crypto_lab.metrics import compute_metrics
from crypto_lab.timeframes import weekly_step_bars


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list
    metrics: dict
    held: np.ndarray
    final_cash: float = 0.0
    final_units: float = 0.0


def cash_growth_factor(annual_yield: float, elapsed_days: float) -> float:
    """Compound `annual_yield` across `elapsed_days` of a 365-day year.

    The rate is an assumption the caller already chose. It is not estimated
    from prices. `elapsed_days` must be known when the bar opens: one day for
    the first bar, and the gap since the previous bar after that.
    """
    if elapsed_days <= 0.0 or annual_yield == 0.0:
        return 1.0
    return (1.0 + annual_yield) ** (elapsed_days / PERIODS_PER_YEAR)


def _elapsed_days(index) -> np.ndarray:
    """Days of cash yield each bar may earn, without reading prices or the future.

    Bar 0 counts as one day. Bar i uses index[i] - index[i - 1], which is known
    at that bar's open. A later bar's date cannot change an earlier factor.
    """
    n = len(index)
    elapsed = np.ones(n, dtype=float)
    if n <= 1:
        return elapsed
    delta = pd.Series(pd.DatetimeIndex(index)).diff().iloc[1:]
    elapsed[1:] = delta.dt.total_seconds().to_numpy(dtype=float) / 86400.0
    return elapsed


def run_backtest(
    bars: pd.DataFrame,
    signal: pd.Series,
    initial_cash: float = INITIAL_CASH,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
    cash_annual_yield: float = CASH_ANNUAL_YIELD,
) -> BacktestResult:
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must be indexed by date")
    if not math.isfinite(cash_annual_yield) or cash_annual_yield <= -1.0:
        raise ValueError("cash_annual_yield must be finite and greater than -100%")
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
    elapsed_days = _elapsed_days(dates) if cash_annual_yield != 0.0 else None

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
        # Yield follows the position after today's open fill. That fill used
        # yesterday's signal, so today's close cannot turn the yield on or off.
        # A long day has no cash, so it earns nothing. The trade's own return
        # was recorded at the fill, before this accrual.
        if elapsed_days is not None and units == 0.0 and cash > 0.0:
            cash *= cash_growth_factor(cash_annual_yield, float(elapsed_days[i]))
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
    step_days: int | None = None,
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
    if step_days is None:
        step_days = weekly_step_bars(bars.index)
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
