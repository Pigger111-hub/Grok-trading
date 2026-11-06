"""Summary numbers for one equity curve."""

import math

import numpy as np
import pandas as pd

from crypto_lab.assumptions import PERIODS_PER_YEAR


def compute_metrics(equity: pd.Series, trades: list, held: np.ndarray) -> dict:
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
    if std and not math.isnan(std) and std > 0:
        sharpe = float(returns.mean() / std * math.sqrt(PERIODS_PER_YEAR))
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
