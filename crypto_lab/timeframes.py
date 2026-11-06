"""Daily decisions on a 4-hour clock, without peeking inside the day.

One-hour bars are not supported. A 1-hour book would fire many more orders,
and the 0.10% fee plus 0.05% slippage would dominate the small moves.
"""

from __future__ import annotations

import pandas as pd


def hold_daily_signal(daily_signal: pd.Series, intraday_index: pd.DatetimeIndex) -> pd.Series:
    """Repeat a daily target across 4-hour bars until the next daily close.

    A daily bar is stamped at 00:00 UTC and its close is not known until the
    next 00:00. The target therefore becomes available on the first 4-hour bar
    of the following day, then stays unchanged at 04:00, 08:00, 12:00, 16:00,
    and 20:00. The backtest engine still fills that target on the next bar's
    open, so a daily decision is not traded on a 4-hour bar from the same day.
    """
    available = daily_signal.copy()
    available.index = pd.DatetimeIndex(available.index) + pd.Timedelta(days=1)
    stretched = available.reindex(intraday_index.union(available.index)).sort_index().ffill()
    return stretched.reindex(intraday_index)


def weekly_step_bars(index: pd.DatetimeIndex) -> int:
    """How many bars make seven days, so DCA stays weekly on a 4-hour chart."""
    if len(index) < 3:
        return 7
    hours = pd.Series(index).diff().dropna().median().total_seconds() / 3600.0
    if 3.0 <= hours <= 5.0:
        return 7 * 6
    return 7
