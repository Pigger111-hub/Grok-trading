"""How much of a good backtest is luck from trying many things?

Three checks, none of which looks at future prices:

  * deflated_sharpe: Bailey and Lopez de Prado (2014). The best Sharpe out of
    N tries is high even when every try is worthless. This gives the chance
    that the true Sharpe is above what luck alone would produce.
  * pbo_cscv: Bailey, Borwein, Lopez de Prado and Zhu (2015). Cut history into
    blocks, pick the best try on half of the blocks, and see where it ranks
    on the other half. PBO is how often the winner lands in the bottom half.
  * rolling_starts: the same rule started on many different dates. A rule
    that only wins from one lucky start date shows up here.
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np
import pandas as pd

from crypto_lab.assumptions import PERIODS_PER_YEAR

_NORMAL = NormalDist()
_EULER = 0.5772156649015329


def expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    """Sharpe the luckiest of `n_trials` useless strategies is expected to show.

    Same units as `sharpe_std` (per bar here, not per year).
    """
    if n_trials < 2 or not sharpe_std or math.isnan(sharpe_std):
        return 0.0
    first = _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    second = _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return float(sharpe_std) * ((1.0 - _EULER) * first + _EULER * second)


def deflated_sharpe(returns: pd.Series, n_trials: int, sharpe_std: float) -> dict:
    """Chance that the true Sharpe beats the luck hurdle. Above 0.95 is the usual bar.

    `returns` are per-bar returns of the chosen strategy. `sharpe_std` is the
    spread of per-bar Sharpe ratios across everything that was tried.
    """
    values = pd.Series(returns).dropna().to_numpy(dtype=float)
    count = len(values)
    std = values.std(ddof=1) if count > 2 else float("nan")
    if count < 30 or not std or math.isnan(std):
        return {"sharpe": float("nan"), "hurdle": float("nan"), "dsr": float("nan"), "n_obs": count}
    sharpe = values.mean() / std
    centred = (values - values.mean()) / values.std(ddof=0)
    skew = float(np.mean(centred**3))
    kurt = float(np.mean(centred**4))
    hurdle = expected_max_sharpe(n_trials, sharpe_std)
    spread = 1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe**2
    if spread <= 0:
        return {"sharpe": sharpe, "hurdle": hurdle, "dsr": float("nan"), "n_obs": count}
    z = (sharpe - hurdle) * math.sqrt(count - 1) / math.sqrt(spread)
    return {"sharpe": float(sharpe), "hurdle": float(hurdle), "dsr": float(_NORMAL.cdf(z)), "n_obs": count}


def per_bar_sharpes(matrix: pd.DataFrame) -> pd.Series:
    std = matrix.std(ddof=1)
    return (matrix.mean() / std).where(std > 0)


def pbo_cscv(matrix: pd.DataFrame, n_blocks: int = 16) -> dict:
    """Probability of backtest overfitting.

    `matrix` has one row per bar and one column per thing that was tried.
    Returns the share of splits where the in-sample winner ranked in the
    bottom half out of sample, plus the winner's median out-of-sample rank
    (1.0 = best, 0.0 = worst).
    """
    data = matrix.dropna(how="any")
    values = data.to_numpy(dtype=float)
    rows, trials = values.shape
    if trials < 2 or rows < n_blocks * 2 or n_blocks % 2:
        return {"pbo": float("nan"), "median_rank": float("nan"), "n_splits": 0, "n_trials": trials}
    usable = rows - rows % n_blocks
    blocks = values[:usable].reshape(n_blocks, usable // n_blocks, trials)
    size = blocks.shape[1]
    sums = blocks.sum(axis=1)
    squares = (blocks**2).sum(axis=1)

    def sharpe(block_ids):
        count = len(block_ids) * size
        total = sums[block_ids].sum(axis=0)
        total_sq = squares[block_ids].sum(axis=0)
        mean = total / count
        var = (total_sq - count * mean**2) / (count - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            out = mean / np.sqrt(var)
        return np.where(var > 0, out, -np.inf)

    all_ids = set(range(n_blocks))
    below = 0
    ranks = []
    splits = 0
    for chosen in combinations(range(n_blocks), n_blocks // 2):
        inside = sharpe(list(chosen))
        outside = sharpe(sorted(all_ids - set(chosen)))
        winner = int(np.argmax(inside))
        # 1 = worst, trials = best. Dividing by trials + 1 keeps it inside (0, 1).
        rank = float((outside <= outside[winner]).sum()) / (trials + 1.0)
        ranks.append(rank)
        if rank <= 0.5:
            below += 1
        splits += 1
    return {
        "pbo": below / splits,
        "median_rank": float(np.median(ranks)),
        "n_splits": splits,
        "n_trials": trials,
    }


def _max_drawdown(values: np.ndarray) -> float:
    peaks = np.maximum.accumulate(values)
    return float((values / peaks - 1.0).min())


def rolling_starts(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    horizon_bars: int,
    step_bars: int = 30,
) -> dict:
    """Start both on many dates, hold for `horizon_bars`, and count who wins.

    Uses per-bar returns of two already-finished backtests, so an entry fee at
    each new start date is not charged again. That is the same for both sides.
    """
    joined = pd.concat([strategy_returns, benchmark_returns], axis=1, keys=["s", "b"]).dropna()
    s = joined["s"].to_numpy(dtype=float)
    b = joined["b"].to_numpy(dtype=float)
    wins_return = 0
    wins_drawdown = 0
    gaps = []
    count = 0
    for start in range(0, len(joined) - horizon_bars + 1, step_bars):
        s_path = np.cumprod(1.0 + s[start : start + horizon_bars])
        b_path = np.cumprod(1.0 + b[start : start + horizon_bars])
        wins_return += s_path[-1] > b_path[-1]
        wins_drawdown += _max_drawdown(s_path) > _max_drawdown(b_path)
        gaps.append(s_path[-1] / b_path[-1] - 1.0)
        count += 1
    if count == 0:
        return {"n_starts": 0, "win_return": float("nan"), "win_drawdown": float("nan"), "median_gap": float("nan")}
    return {
        "n_starts": count,
        "win_return": wins_return / count,
        "win_drawdown": wins_drawdown / count,
        "median_gap": float(np.median(gaps)),
    }


def annualise(per_bar_sharpe: float, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    return float(per_bar_sharpe) * math.sqrt(periods_per_year)
