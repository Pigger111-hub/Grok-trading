"""Score the experiment-11 weight on the last 30% and a fixed walk-forward.

The target, the 30-day window, and the 10% band are the constants in
crypto_lab.weights. Nothing here searches those numbers, on the out-of-sample
slice or anywhere else. Cash still earns nothing.
"""

from __future__ import annotations

import pandas as pd

from crypto_lab.assumptions import WALK_FORWARD_TRAIN_DAYS
from crypto_lab.engine import run_backtest
from crypto_lab.research import split_point
from crypto_lab.strategies import sma_filter_signal
from crypto_lab.weights import REBALANCE_BAND, run_weight_backtest, round_trip_stats, trend_vol_weight


def _slice_scores(bars: pd.DataFrame, start: int) -> dict:
    window = bars.iloc[start:]
    weight = trend_vol_weight(bars).iloc[start:]
    trend = run_weight_backtest(window, weight, band=REBALANCE_BAND)
    sma = run_backtest(window, sma_filter_signal(bars, window=200).iloc[start:])
    hold = run_backtest(window, pd.Series(1.0, index=window.index))
    trips = round_trip_stats(trend.trades)
    return {
        "start": window.index[0].date().isoformat(),
        "end": window.index[-1].date().isoformat(),
        "trend_return": trend.metrics["total_return"],
        "trend_drawdown": trend.metrics["max_drawdown"],
        "trend_win_rate": trips["win_rate"],
        "trend_trades": trips["n_trades"],
        "trend_rebalances": trend.n_rebalances,
        "sma_return": sma.metrics["total_return"],
        "sma_drawdown": sma.metrics["max_drawdown"],
        "sma_win_rate": sma.metrics["win_rate"],
        "sma_trades": sma.metrics["n_trades"],
        "hold_return": hold.metrics["total_return"],
        "hold_drawdown": hold.metrics["max_drawdown"],
        "hold_win_rate": hold.metrics["win_rate"],
        "hold_trades": hold.metrics["n_trades"],
    }


def score_assets(assets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per coin and per judged window. Daily bars only."""
    rows = []
    for asset, bars in assets.items():
        windows = {
            "oos": split_point(len(bars)),
            "walk_forward": WALK_FORWARD_TRAIN_DAYS,
        }
        for name, start in windows.items():
            rows.append({"asset": asset, "window": name, **_slice_scores(bars, start)})
    return pd.DataFrame(rows)
