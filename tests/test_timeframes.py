"""4-hour bars versus daily decisions. One-hour bars are intentionally absent."""

import numpy as np
import pandas as pd

from crypto_lab.metrics import compute_metrics, infer_periods_per_year
from crypto_lab.market import drop_open_bars
from crypto_lab.timeframes import hold_daily_signal, weekly_step_bars


def test_daily_signal_changes_only_after_the_daily_close():
    daily_index = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    daily = pd.Series([0.0, 1.0, 1.0], index=daily_index)
    intraday = pd.date_range("2025-01-01", periods=18, freq="4h")
    held = hold_daily_signal(daily, intraday)
    # The 1 on 2 Jan is not known until 3 Jan 00:00.
    assert held.loc["2025-01-02 00:00"] == 0
    assert held.loc["2025-01-02 20:00"] == 0
    assert held.loc["2025-01-03 00:00"] == 1
    assert held.loc["2025-01-03 04:00"] == 1
    assert held.loc["2025-01-03 08:00"] == 1


def test_open_4h_bar_is_dropped_but_a_finished_one_stays():
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-11-06 04:00", "2026-11-06 08:00"]),
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
        }
    )
    kept = drop_open_bars(frame, bar_hours=4, now=pd.Timestamp("2026-11-06 10:00"))
    assert list(kept["date"]) == [pd.Timestamp("2026-11-06 04:00")]


def test_sharpe_uses_six_bars_per_day_on_4h_data():
    index = pd.date_range("2024-01-01", periods=40, freq="4h")
    equity = pd.Series(np.linspace(100, 130, 40), index=index)
    assert infer_periods_per_year(index) == 365 * 6
    four_hour = compute_metrics(equity, [], np.ones(40))
    daily_index = pd.date_range("2024-01-01", periods=40, freq="D")
    daily = compute_metrics(pd.Series(equity.to_numpy(), index=daily_index), [], np.ones(40))
    assert four_hour["sharpe"] == daily["sharpe"] * (6 ** 0.5) or abs(four_hour["sharpe"] / daily["sharpe"] - 6 ** 0.5) < 1e-9
    assert weekly_step_bars(index) == 42
