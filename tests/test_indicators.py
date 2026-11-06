"""Known-value tests for indicators. Expected numbers are computed by hand."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.indicators import bollinger, donchian, ema, rsi, sma


def test_sma_matches_hand_calculation():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = sma(close, 3)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_ema_span3_matches_hand_calculation():
    # alpha = 2 / (3 + 1) = 0.5, seed = first price
    close = pd.Series([1.0, 2.0, 3.0])
    out = ema(close, 3)
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(1.5)
    assert out.iloc[2] == pytest.approx(2.25)


def test_rsi_wilder_matches_hand_calculation():
    # period 3. Changes: +1, +1, -1, -1, -1, +1, +1
    close = pd.Series([10.0, 11.0, 12.0, 11.0, 10.0, 9.0, 10.0, 11.0])
    out = rsi(close, 3)
    assert np.isnan(out.iloc[2])
    # First average ends on the 4th price (index 3): RS = 2, RSI = 66.666...
    assert out.iloc[3] == pytest.approx(100 - 100 / 3)
    # Next step: RS = 0.8, RSI = 44.444...
    assert out.iloc[4] == pytest.approx(100 - 100 / 1.8)


def test_rsi_is_100_when_every_day_is_up():
    close = pd.Series([float(x) for x in range(1, 20)])
    out = rsi(close, 14)
    assert out.iloc[-1] == pytest.approx(100.0)


def test_bollinger_uses_population_std():
    close = pd.Series([1.0, 2.0, 3.0])
    mid, upper, lower = bollinger(close, window=3, nstd=2)
    # population variance = ((1-2)^2 + 0 + (3-2)^2) / 3 = 2/3
    assert mid.iloc[2] == pytest.approx(2.0)
    assert upper.iloc[2] == pytest.approx(2 + 2 * np.sqrt(2 / 3))
    assert lower.iloc[2] == pytest.approx(2 - 2 * np.sqrt(2 / 3))


def test_donchian_channel_excludes_today():
    high = pd.Series([1.0, 2.0, 3.0, 100.0])
    low = pd.Series([1.0, 2.0, 3.0, 0.1])
    prior_high, prior_low = donchian(high, low, entry=2, exit=2)
    # At the last bar the channel is max/min of the previous two bars, not today's 100 / 0.1.
    assert prior_high.iloc[3] == pytest.approx(3.0)
    assert prior_low.iloc[3] == pytest.approx(2.0)
