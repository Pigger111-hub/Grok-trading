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
