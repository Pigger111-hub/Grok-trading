"""Strategy signals are causal: day t depends only on prices up through day t."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.strategies import STRATEGIES, STRATEGIES_BY_ID


def _market(n=400, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    idx = pd.date_range("2016-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


@pytest.mark.parametrize("strategy", [s for s in STRATEGIES if s.kind == "signal"], ids=lambda s: s.id)
def test_signal_uses_only_past_and_present(strategy):
    bars = _market()
    full = strategy.generate(bars, **strategy.default_params)
    for t in (80, 150, 250, 399):
        prefix = strategy.generate(bars.iloc[: t + 1], **strategy.default_params)
        pd.testing.assert_series_equal(prefix, full.iloc[: t + 1], check_names=False)


def test_sma_cross_is_long_only_when_fast_is_above_slow():
    idx = pd.date_range("2020-01-01", periods=6, freq="D")
    # Climb, then fall hard so the fast average drops through the slow one.
    close = [1, 2, 3, 4, 1, 1]
    bars = pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close},
        index=idx,
    )
    sig = STRATEGIES_BY_ID["sma_cross"].generate(bars, fast=2, slow=4)
    assert np.isnan(sig.iloc[2])
    assert sig.iloc[3] == 1  # fast (3.5) > slow (2.5)
    assert sig.iloc[5] == 0  # fast (1) < slow (2.25)


def test_donchian_enters_on_prior_channel_not_today_high():
    strategy = STRATEGIES_BY_ID["donchian"]
    idx = pd.date_range("2020-01-01", periods=6, freq="D")
    high = [10, 10, 10, 10, 10, 100]
    low = [9, 9, 9, 9, 9, 9]
    close = [9.5, 9.5, 9.5, 9.5, 9.5, 10.5]
    bars = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=idx,
    )
    sig = strategy.generate(bars, entry=3, exit=2)
    # Close 10.5 breaks the prior 3-day high of 10, even though today's high is 100.
    assert sig.iloc[-1] == 1


def test_rsi_buys_oversold_and_sells_overbought():
    strategy = STRATEGIES_BY_ID["rsi"]
    # A long drop pushes RSI down, a long rally pushes it back up.
    down = list(np.linspace(100, 40, 40))
    up = list(np.linspace(41, 160, 80))
    close = down + up
    idx = pd.date_range("2020-01-01", periods=len(close), freq="D")
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)
    sig = strategy.generate(bars, period=14, oversold=30, overbought=70)
    assert sig.max() == 1
    # Once it has been both oversold and then overbought, we end flat.
    assert sig.iloc[-1] == 0


def test_every_signal_strategy_is_long_or_flat_or_warmup():
    bars = _market(220, seed=1)
    for strategy in STRATEGIES:
        if strategy.kind != "signal":
            continue
        sig = strategy.generate(bars, **strategy.default_params)
        finite = sig.dropna()
        assert set(finite.unique()).issubset({0.0, 1.0})
        assert finite.isna().sum() == 0


def _state_changed(previous, current) -> bool:
    previous_missing = pd.isna(previous)
    current_missing = pd.isna(current)
    if previous_missing and current_missing:
        return False
    if previous_missing or current_missing:
        return True
    return float(previous) != float(current)


def test_sma_filter_weekly_changes_state_only_on_every_seventh_bar():
    """The weekly filter may adopt a new target only on bars 0, 7, 14, ...

    Between those bars it keeps the previous target, even when the daily
    close-versus-SMA signal has already flipped. The target on a decision
    bar is that bar's own daily signal, not a later one.
    """
    # Window 4 is valid from index 3. Index 7 is the first decision bar with
    # a real average. The close jumps above that average on bar 7, then falls
    # through it on bar 8. A weekly check must stay long until bar 14.
    close = [10.0] * 7 + [14.0] + [1.0] * 14
    idx = pd.date_range("2020-01-01", periods=len(close), freq="D")
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)
    daily = STRATEGIES_BY_ID["sma_filter"].generate(bars, window=4)
    weekly = STRATEGIES_BY_ID["sma_filter_weekly"].generate(bars, window=4)

    assert weekly.iloc[:7].isna().all()
    assert daily.iloc[7] == 1
    assert weekly.iloc[7] == 1
    assert daily.iloc[8] == 0
    assert list(weekly.iloc[8:14]) == [1.0] * 6
    assert weekly.iloc[14] == daily.iloc[14] == 0

    for i in range(len(weekly)):
        if i % 7 == 0 and pd.notna(daily.iloc[i]):
            assert weekly.iloc[i] == daily.iloc[i]
        if i > 0 and _state_changed(weekly.iloc[i - 1], weekly.iloc[i]):
            assert i % 7 == 0


def test_sma_filter_weekly_does_not_look_ahead():
    strategy = STRATEGIES_BY_ID["sma_filter_weekly"]
    bars = _market(420, seed=11)
    full = strategy.generate(bars, **strategy.default_params)
    for t in (199, 206, 250, 419):
        prefix = strategy.generate(bars.iloc[: t + 1], **strategy.default_params)
        pd.testing.assert_series_equal(prefix, full.iloc[: t + 1], check_names=False)

    shocked = bars.copy()
    shocked.iloc[300:] = shocked.iloc[300:].to_numpy() * 3
    before = strategy.generate(bars.iloc[:300], **strategy.default_params)
    after = strategy.generate(shocked, **strategy.default_params).iloc[:300]
    pd.testing.assert_series_equal(before, after, check_names=False)
