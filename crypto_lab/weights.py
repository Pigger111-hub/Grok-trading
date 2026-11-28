"""Partial positions: a blended trend score, sized by how wild the price is.

The first round of the lab was all-in or all-out on one rule. This module asks
a different question: what if several trend rules vote, and the size of the
position shrinks when the price swings harder?

Nothing here is tuned on the lab's data. The five votes use windows people
publish (50, 100, 200 days and the two Turtle channels). The volatility target
is fixed before any result is read, and the report prints the neighbours too.

Timing is the same as the main engine: a weight on today's row may use today's
close, and the order is filled at the NEXT bar's open.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from crypto_lab.assumptions import FEE_RATE, INITIAL_CASH, PERIODS_PER_YEAR, SLIPPAGE_RATE
from crypto_lab.indicators import sma
from crypto_lab.metrics import compute_metrics
from crypto_lab.strategies import donchian_signal

# Fixed in advance. See results/trend_sizing.md for what the neighbours do.
TARGET_VOL = 0.40
VOL_LOOKBACK = 30
REBALANCE_BAND = 0.10

SMA_WINDOWS = (50, 100, 200)
CHANNELS = ((20, 10), (55, 20))


def trend_score(bars: pd.DataFrame) -> pd.Series:
    """Share of the five trend rules that say "hold". 0, 0.2, ... 1.0.

    Missing until the slowest rule (the 200-bar average) has a full window.
    """
    close = bars["close"]
    votes = [(close > sma(close, window)).astype(float) for window in SMA_WINDOWS]
    votes += [donchian_signal(bars, entry=entry, exit=exit_n).fillna(0.0) for entry, exit_n in CHANNELS]
    score = sum(votes) / float(len(votes))
    return score.where(sma(close, max(SMA_WINDOWS)).notna())


def realized_vol(close: pd.Series, lookback: int = VOL_LOOKBACK, periods_per_year: int = PERIODS_PER_YEAR) -> pd.Series:
    """Annualised standard deviation of the last `lookback` close-to-close moves."""
    returns = close.pct_change()
    return returns.rolling(lookback, min_periods=lookback).std(ddof=1) * np.sqrt(periods_per_year)


def vol_scale(
    close: pd.Series,
    target_vol: float | None = TARGET_VOL,
    lookback: int = VOL_LOOKBACK,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> pd.Series:
    """How much of the money may be invested: target / recent swing, never above 1 (no leverage)."""
    if target_vol is None:
        return pd.Series(1.0, index=close.index)
    vol = realized_vol(close, lookback, periods_per_year)
    scale = (float(target_vol) / vol).clip(upper=1.0)
    return scale.where(vol > 0)


def trend_vol_weight(
    bars: pd.DataFrame,
    target_vol: float | None = TARGET_VOL,
    lookback: int = VOL_LOOKBACK,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> pd.Series:
    """Target share of the account in the asset, between 0 and 1."""
    return trend_score(bars) * vol_scale(bars["close"], target_vol, lookback, periods_per_year)


@dataclass
class WeightResult:
    equity: pd.Series
    weights: pd.Series  # share of the account actually held at each close
    metrics: dict
    n_rebalances: int
    turnover: float  # total traded amount / starting cash
    # One trade is a round trip: leaving cash, then returning to cash.
    # A resize that stays invested is part of that trip, not a new trade.
    # An open trip at the last bar is included and marked, same as the all-in engine.
    trades: list = field(default_factory=list)
    final_cash: float = 0.0
    final_units: float = 0.0


def run_weight_backtest(
    bars: pd.DataFrame,
    weight: pd.Series,
    initial_cash: float = INITIAL_CASH,
    fee_rate: float = FEE_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
    band: float = REBALANCE_BAND,
    periods_per_year: int | None = None,
) -> WeightResult:
    """Hold `weight` of the account in the asset. Long only, no leverage.

    The order uses yesterday's weight and today's open. To avoid paying fees
    on tiny adjustments, it only trades when the held share is at least `band`
    away from the target, or when the target is exactly zero.
    """
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise TypeError("bars must be indexed by date")
    target = pd.Series(weight).reindex(bars.index).to_numpy(dtype=float)
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    cash = float(initial_cash)
    units = 0.0
    equity = np.empty(n)
    held = np.zeros(n)
    rebalances = 0
    traded = 0.0
    trades: list[dict] = []
    episode = None
    dates = bars.index

    for i in range(n):
        if i > 0 and not np.isnan(target[i - 1]) and opens[i] > 0:
            want = min(max(target[i - 1], 0.0), 1.0)
            account = cash + units * opens[i]
            have = units * opens[i] / account if account > 0 else 0.0
            gap = want - have
            must_exit = want == 0.0 and units > 0
            if abs(gap) >= band or must_exit:
                was_flat = units <= 0.0
                if gap > 0:
                    spend = min(gap * account, cash)
                    units += spend * (1.0 - fee_rate) / (opens[i] * (1.0 + slippage_rate))
                    cash -= spend
                    traded += spend
                else:
                    sell_units = units if must_exit else min(units, -gap * account / opens[i])
                    cash += sell_units * opens[i] * (1.0 - slippage_rate) * (1.0 - fee_rate)
                    units -= sell_units
                    traded += sell_units * opens[i]
                rebalances += 1
                if was_flat and units > 0.0:
                    episode = {
                        "entry_date": dates[i],
                        "entry_price": float(opens[i] * (1.0 + slippage_rate)),
                        "equity_at_entry": float(account),
                    }
                elif episode is not None and units <= 0.0:
                    base = episode["equity_at_entry"]
                    trades.append(
                        {
                            "entry_date": episode["entry_date"],
                            "exit_date": dates[i],
                            "entry_price": episode["entry_price"],
                            "exit_price": float(opens[i] * (1.0 - slippage_rate)),
                            "return": (cash / base - 1.0) if base else None,
                            "closed": True,
                        }
                    )
                    episode = None
        equity[i] = cash + units * closes[i]
        held[i] = units * closes[i] / equity[i] if equity[i] > 0 else 0.0

    if episode is not None:
        marked = cash + units * float(closes[-1])
        base = episode["equity_at_entry"]
        trades.append(
            {
                "entry_date": episode["entry_date"],
                "exit_date": dates[-1],
                "entry_price": episode["entry_price"],
                "exit_price": float(closes[-1]),
                "return": (marked / base - 1.0) if base else None,
                "closed": False,
            }
        )

    equity_s = pd.Series(equity, index=bars.index, name="equity")
    metrics = compute_metrics(equity_s, [], held, periods_per_year=periods_per_year)
    # A rebalance is not a round trip, so a win rate would be meaningless here.
    metrics["win_rate"] = float("nan")
    metrics["n_trades"] = rebalances
    return WeightResult(
        equity=equity_s,
        weights=pd.Series(held, index=bars.index, name="weight"),
        metrics=metrics,
        n_rebalances=rebalances,
        turnover=traded / float(initial_cash),
        trades=trades,
        final_cash=cash,
        final_units=units,
    )


def round_trip_stats(trades: list) -> dict:
    """Win rate of round trips. A resize that never returns to cash is not its own trade.

    The open trip at the end counts, marked at the last close with no exit fee.
    `n_rebalances` on the result is the separate count of band crossings.
    """
    counted = [trade for trade in trades if trade.get("return") is not None]
    wins = sum(1 for trade in counted if trade["return"] > 0)
    return {
        "n_trades": len(counted),
        "win_rate": (wins / len(counted)) if counted else float("nan"),
    }
