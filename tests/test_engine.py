"""Backtest engine: next-open fills, fees, slippage, and no same-bar lookahead."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.engine import run_backtest


def _bars(opens, closes, start="2020-01-01"):
    idx = pd.date_range(start, periods=len(opens), freq="D")
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes),
            "low": np.minimum(opens, closes),
            "close": closes,
        },
        index=idx,
    )


def test_buy_and_hold_fills_next_open_and_charges_fee_and_slippage():
    bars = _bars(
        opens=[100.0, 100.0, 110.0],
        closes=[100.0, 110.0, 121.0],
    )
    signal = pd.Series([1.0, 1.0, 1.0], index=bars.index)
    res = run_backtest(bars, signal, initial_cash=10_000, fee_rate=0.001, slippage_rate=0.0005)

    exec_px = 100.0 * 1.0005
    units = 10_000 * 0.999 / exec_px
    assert res.equity.iloc[0] == pytest.approx(10_000)
    assert res.equity.iloc[1] == pytest.approx(units * 110.0)
    assert res.equity.iloc[2] == pytest.approx(units * 121.0)
    assert res.metrics["n_trades"] == 1
    assert res.trades[0]["closed"] is False
    # Still holding, so the open trade is marked at the last close with no exit fee.
    assert res.trades[0]["return"] == pytest.approx((units * 121.0) / 10_000 - 1)


def test_round_trip_sells_at_the_next_open():
    bars = _bars(
        opens=[100.0, 100.0, 110.0],
        closes=[100.0, 110.0, 110.0],
    )
    # Want long after day 0, flat after day 1. Buy at day-1 open, sell at day-2 open.
    signal = pd.Series([1.0, 0.0, 0.0], index=bars.index)
    res = run_backtest(bars, signal, initial_cash=10_000, fee_rate=0.001, slippage_rate=0.0005)

    buy_px = 100.0 * 1.0005
    units = 10_000 * 0.999 / buy_px
    sell_px = 110.0 * (1 - 0.0005)
    cash = units * sell_px * 0.999
    assert res.equity.iloc[1] == pytest.approx(units * 110.0)
    assert res.equity.iloc[2] == pytest.approx(cash)
    assert res.trades[0]["closed"] is True
    assert res.trades[0]["return"] == pytest.approx(cash / 10_000 - 1)
    assert res.metrics["n_trades"] == 1
    assert res.metrics["exposure"] == pytest.approx(1 / 3)


def test_signal_on_day_t_does_not_change_equity_on_day_t():
    bars = _bars(opens=[10, 10, 10, 10], closes=[10, 10, 10, 50])
    flat = pd.Series([0.0, 0.0, 0.0, 0.0], index=bars.index)
    late = pd.Series([0.0, 0.0, 0.0, 1.0], index=bars.index)
    a = run_backtest(bars, flat, fee_rate=0.0, slippage_rate=0.0)
    b = run_backtest(bars, late, fee_rate=0.0, slippage_rate=0.0)
    # The long signal is only on the last close, so there is no later open to trade.
    pd.testing.assert_series_equal(a.equity, b.equity)
    assert b.metrics["n_trades"] == 0


def test_future_prices_do_not_change_past_equity():
    bars = _bars(opens=[10, 11, 12, 13, 14], closes=[10, 11, 12, 13, 14.0])
    signal = pd.Series([1.0, 1.0, 0.0, 0.0, 0.0], index=bars.index)
    base = run_backtest(bars, signal, fee_rate=0.001, slippage_rate=0.0005)

    shocked = bars.copy()
    shocked.loc[shocked.index[3] :, ["open", "high", "low", "close"]] = 1_000.0
    shocked_signal = signal.copy()
    shocked_signal.iloc[3:] = 1.0
    alt = run_backtest(shocked, shocked_signal, fee_rate=0.001, slippage_rate=0.0005)

    # Days 0 and 1 are fully determined before the shock. Day 2's open is still 12
    # (the sell), but its close was shocked, so equity on day 2 may differ.
    assert alt.equity.iloc[0] == pytest.approx(base.equity.iloc[0])
    assert alt.equity.iloc[1] == pytest.approx(base.equity.iloc[1])


def test_warmup_nan_stays_in_cash_until_a_real_signal():
    bars = _bars(opens=[5, 5, 5, 5], closes=[5, 5, 5, 8])
    signal = pd.Series([np.nan, np.nan, 1.0, 1.0], index=bars.index)
    res = run_backtest(bars, signal, initial_cash=1_000, fee_rate=0.0, slippage_rate=0.0)
    assert res.equity.iloc[0] == pytest.approx(1_000)
    assert res.equity.iloc[1] == pytest.approx(1_000)
    assert res.equity.iloc[2] == pytest.approx(1_000)
    # Buy at the last open (5) and mark at the last close (8).
    assert res.equity.iloc[3] == pytest.approx(1_000 / 5 * 8)
    assert res.metrics["n_trades"] == 1


def test_fees_reduce_a_round_trip_versus_zero_cost():
    bars = _bars(opens=[100, 100, 110, 110], closes=[100, 105, 110, 110])
    signal = pd.Series([1.0, 1.0, 0.0, 0.0], index=bars.index)
    free = run_backtest(bars, signal, fee_rate=0.0, slippage_rate=0.0)
    paid = run_backtest(bars, signal, fee_rate=0.001, slippage_rate=0.0005)
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]


def test_metrics_drawdown_and_win_rate():
    idx = pd.date_range("2020-01-01", periods=3, freq="D")
    equity = pd.Series([100.0, 150.0, 90.0], index=idx)
    trades = [{"return": 0.5, "closed": True}, {"return": -0.4, "closed": True}]
    from crypto_lab.metrics import compute_metrics

    m = compute_metrics(equity, trades, held=np.array([1, 1, 0]))
    assert m["total_return"] == pytest.approx(-0.10)
    assert m["max_drawdown"] == pytest.approx(90 / 150 - 1)
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["n_trades"] == 2
    assert m["exposure"] == pytest.approx(2 / 3)
