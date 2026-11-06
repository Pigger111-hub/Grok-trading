"""Price indicators. Every function at row t uses only rows 0..t."""

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    # adjust=False is the recursive form: ema_t = alpha * price_t + (1 - alpha) * ema_{t-1}
    # with alpha = 2 / (span + 1). The first value is the first price (the seed).
    return close.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. The first value uses a simple average of `period` changes."""
    delta = close.diff()
    gain = delta.clip(lower=0.0).to_numpy(dtype=float)
    loss = (-delta).clip(lower=0.0).to_numpy(dtype=float)
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    if len(close) > period:
        avg_gain[period] = np.mean(gain[1 : period + 1])
        avg_loss[period] = np.mean(loss[1 : period + 1])
        for i in range(period + 1, len(close)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        values = 100.0 - (100.0 / (1.0 + rs))
    values = np.where(avg_loss == 0, np.where(avg_gain > 0, 100.0, np.nan), values)
    values[:period] = np.nan
    return pd.Series(values, index=close.index, name="rsi")


def bollinger(close: pd.Series, window: int = 20, nstd: float = 2.0):
    """Middle band is an SMA. Width uses the population standard deviation (divide by N)."""
    mid = sma(close, window)
    std = close.rolling(window, min_periods=window).std(ddof=0)
    upper = mid + nstd * std
    lower = mid - nstd * std
    return mid, upper, lower


def donchian(high: pd.Series, low: pd.Series, entry: int = 20, exit: int = 10):
    """Prior-channel highs and lows. Today's bar is excluded on purpose."""
    prior_high = high.shift(1).rolling(entry, min_periods=entry).max()
    prior_low = low.shift(1).rolling(exit, min_periods=exit).min()
    return prior_high, prior_low


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line, signal)
    return line, signal_line, line - signal_line
