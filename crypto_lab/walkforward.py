"""Pick parameters on past data only, then trade the next unseen year.

The first training span is used only for choosing. It is not part of the
walk-forward score. Indicators may look at every price already known on that
day. The score used to pick parameters uses only the most recent training
window, and never the year being tested.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from crypto_lab.assumptions import (
    INITIAL_CASH,
    WALK_FORWARD_TEST_DAYS,
    WALK_FORWARD_TRAIN_DAYS,
)
from crypto_lab.engine import BacktestResult, run_backtest, run_dca
from crypto_lab.metrics import compute_metrics


@dataclass
class WalkForwardResult:
    result: BacktestResult
    benchmark: BacktestResult
    folds: list
    signal: pd.Series


def choose_params(history: pd.DataFrame, strategy, train_days: int):
    """Return (params, train_sharpe). Higher Sharpe wins. NaN never wins."""
    best_params = dict(strategy.default_params)
    best_score = -np.inf
    window = history.iloc[-train_days:] if len(history) > train_days else history
    for params in strategy.grid:
        if strategy.kind == "dca":
            scored = run_dca(window, weeks=int(params["weeks"]))
        else:
            signal = strategy.generate(history, **params)
            scored = run_backtest(window, signal.reindex(window.index))
        score = scored.metrics["sharpe"]
        if isinstance(score, (float, np.floating)) and not np.isnan(score) and score > best_score:
            best_score = float(score)
            best_params = dict(params)
    if best_score == -np.inf:
        return dict(strategy.default_params), float("nan")
    return best_params, float(best_score)


def _fold_bounds(n: int, train_days: int, test_days: int):
    test_start = train_days
    while test_start < n:
        test_end = min(n, test_start + test_days)
        yield test_start, test_end
        if test_end == n:
            break
        test_start = test_end


def _walk_forward_dca(bars, strategy, train_days, test_days) -> WalkForwardResult:
    """Each test year starts a new DCA schedule. Ending cash carries into the next year.

    DCA is not a hold/flat signal, so a position is not kept across the boundary.
    The journal says this in plain language.
    """
    pieces = []
    held_parts = []
    trades = []
    folds = []
    capital = INITIAL_CASH
    n = len(bars)
    for test_start, test_end in _fold_bounds(n, train_days, test_days):
        params, score = choose_params(bars.iloc[:test_start], strategy, train_days)
        window = bars.iloc[test_start:test_end]
        scored = run_dca(window, weeks=int(params["weeks"]), initial_cash=capital)
        pieces.append(scored.equity)
        held_parts.append(scored.held)
        trades.extend(scored.trades)
        capital = float(scored.equity.iloc[-1])
        folds.append(
            {
                "test_start": bars.index[test_start],
                "test_end": bars.index[test_end - 1],
                "params": params,
                "train_sharpe": score,
            }
        )
    equity = pd.concat(pieces)
    equity.name = "equity"
    held = np.concatenate(held_parts)
    result = BacktestResult(
        equity=equity,
        trades=trades,
        metrics=compute_metrics(equity, trades, held),
        held=held,
    )
    bench_bars = bars.loc[equity.index]
    benchmark = run_backtest(bench_bars, pd.Series(1.0, index=bench_bars.index))
    return WalkForwardResult(result=result, benchmark=benchmark, folds=folds, signal=pd.Series(dtype=float))


def walk_forward(
    bars: pd.DataFrame,
    strategy,
    train_days: int = WALK_FORWARD_TRAIN_DAYS,
    test_days: int = WALK_FORWARD_TEST_DAYS,
) -> WalkForwardResult:
    if strategy.kind == "dca":
        return _walk_forward_dca(bars, strategy, train_days, test_days)

    n = len(bars)
    folds = []
    stitched = pd.Series(np.nan, index=bars.index, dtype=float)
    for test_start, test_end in _fold_bounds(n, train_days, test_days):
        params, score = choose_params(bars.iloc[:test_start], strategy, train_days)
        # Prices after test_end are not passed in. Causal indicators make each
        # day inside the window independent of later days in the same window.
        signal = strategy.generate(bars.iloc[:test_end], **params)
        stitched.iloc[test_start:test_end] = signal.iloc[test_start:test_end].to_numpy()
        folds.append(
            {
                "test_start": bars.index[test_start],
                "test_end": bars.index[test_end - 1],
                "params": params,
                "train_sharpe": score,
            }
        )

    if stitched.notna().sum() == 0:
        raise RuntimeError(f"{strategy.id}: walk-forward produced no test days")
    start_ts = stitched.first_valid_index()
    window = bars.loc[start_ts:]
    result = run_backtest(window, stitched.loc[start_ts:])
    benchmark = run_backtest(window, pd.Series(1.0, index=window.index))
    return WalkForwardResult(result=result, benchmark=benchmark, folds=folds, signal=stitched)
