"""Summary numbers for one equity curve."""

import math

import numpy as np
import pandas as pd

from crypto_lab.assumptions import PERIODS_PER_YEAR


def infer_periods_per_year(index) -> int:
    """365 for daily bars, 365*6 for 4-hour bars. One-hour bars are not used."""
    if len(index) < 3:
        return PERIODS_PER_YEAR
    delta = pd.Series(pd.DatetimeIndex(index)).diff().dropna().median()
    hours = pd.Timedelta(delta).total_seconds() / 3600.0
    if 3.0 <= hours <= 5.0:
        return 365 * 6
    return PERIODS_PER_YEAR


def compute_metrics(
    equity: pd.Series,
    trades: list,
    held: np.ndarray,
    periods_per_year: int | None = None,
) -> dict:
    start_val = float(equity.iloc[0])
    end_val = float(equity.iloc[-1])
    total_return = end_val / start_val - 1.0
    days = max(int((equity.index[-1] - equity.index[0]).days), 1)
    cagr = (end_val / start_val) ** (365.25 / days) - 1.0

    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())

    returns = equity.pct_change().dropna()
    if len(returns) > 1:
        std = float(returns.std(ddof=1))
    else:
        std = float("nan")
    periods = infer_periods_per_year(equity.index) if periods_per_year is None else periods_per_year
    if std and not math.isnan(std) and std > 0:
        sharpe = float(returns.mean() / std * math.sqrt(periods))
    else:
        sharpe = float("nan")

    n_trades = len(trades)
    wins = sum(1 for trade in trades if trade["return"] is not None and trade["return"] > 0)
    win_rate = wins / n_trades if n_trades else float("nan")
    exposure = float(np.mean(held)) if len(held) else float("nan")

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "n_trades": n_trades,
        "exposure": exposure,
        "start_value": start_val,
        "end_value": end_val,
        "days": days,
    }
