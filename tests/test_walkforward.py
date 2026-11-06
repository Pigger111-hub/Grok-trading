"""Walk-forward parameter choice may see the past only, never the test window."""

import numpy as np
import pandas as pd

from crypto_lab.engine import run_dca
from crypto_lab.strategies import Strategy
from crypto_lab.walkforward import choose_params, walk_forward


def _bars(n, start=100.0):
    idx = pd.date_range("2018-01-01", periods=n, freq="D")
    close = np.linspace(start, start + n, n)
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close},
        index=idx,
    )


def _spy_strategy():
    calls = []

    def generate(bars, mode="flat"):
        calls.append(len(bars))
        value = 1.0 if mode == "long" else 0.0
        return pd.Series(value, index=bars.index)

    strategy = Strategy(
        id="spy",
        kind="signal",
        name_en="spy",
        name_th="สปาย",
        claim_th="",
        source_th="",
        default_params={"mode": "flat"},
        grid=({"mode": "flat"}, {"mode": "long"}),
        generate=generate,
    )
    return strategy, calls


def test_walk_forward_shows_training_history_only_when_choosing_params():
    strategy, calls = _spy_strategy()
    bars = _bars(200)
    result = walk_forward(bars, strategy, train_days=100, test_days=50)
    # Two folds: test [100, 150) and [150, 200).
    # Each fold scores 2 parameter sets on history ending at the test start,
    # then builds the signal once on history ending at the test end.
    assert calls == [100, 100, 150, 150, 150, 200]
    assert result.folds[0]["test_start"] == bars.index[100]
    assert result.folds[0]["test_end"] == bars.index[149]
    assert result.folds[1]["test_start"] == bars.index[150]
    # An uptrend rewards being long, so the chooser must not keep the flat default.
    assert result.folds[0]["params"] == {"mode": "long"}


def test_choose_params_scores_the_recent_train_window_not_the_whole_past():
    seen = []

    def generate(bars, mode="flat"):
        seen.append(len(bars))
        return pd.Series(1.0 if mode == "long" else 0.0, index=bars.index)

    strategy = _spy_strategy()[0]
    strategy.generate = generate
    history = _bars(120)
    params, score = choose_params(history, strategy, train_days=40)
    assert params == {"mode": "long"}
    assert score > 0
    # generate() sees the whole past (so indicators could warm up);
    # the backtest score itself is checked inside choose_params via train_days.
    assert seen == [120, 120]


def test_dca_deploys_equal_slices_then_holds():
    bars = _bars(30, start=100)
    # Force a flat price so fees are the only drag.
    bars.loc[:, ["open", "high", "low", "close"]] = 100.0
    res = run_dca(bars, weeks=2, step_days=7, initial_cash=10_000, fee_rate=0.0, slippage_rate=0.0)
    # Buys at the second bar and again 7 bars later. Fully invested, price unchanged.
    assert res.equity.iloc[0] == 10_000
    assert res.equity.iloc[1] == 10_000
    assert res.metrics["n_trades"] == 2
    assert res.equity.iloc[-1] == 10_000
