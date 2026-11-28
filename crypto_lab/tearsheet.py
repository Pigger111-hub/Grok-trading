"""QuantStats HTML tear sheet versus buy-and-hold.

One file per paper-traded strategy and coin, using the full daily backtest.
QuantStats draws the charts. The numbers in the journal still come from our engine.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "DejaVu Sans"

import pandas as pd

from crypto_lab.engine import run_backtest
from crypto_lab.paper import PAPER_BOOK
from crypto_lab.research import backtest_window
from crypto_lab.strategies import STRATEGIES_BY_ID
from crypto_lab.weights import run_weight_backtest, trend_vol_weight


def write_tearsheet(equity: pd.Series, benchmark: pd.Series, path: Path, title: str) -> None:
    import quantstats as qs

    returns = equity.pct_change().rename("strategy")
    bench = benchmark.reindex(equity.index).pct_change().rename("buy_and_hold")
    both = pd.concat([returns, bench], axis=1).dropna()
    path.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(
        both["strategy"],
        benchmark=both["buy_and_hold"],
        output=str(path),
        title=title,
        download_filename=path.name,
    )


def write_strategy_tearsheet(
    bars: pd.DataFrame,
    asset: str,
    strategy_id: str,
    params: dict,
    folder: Path,
    timeframe: str = "1d",
) -> Path:
    spec = next((item for item in PAPER_BOOK if item["id"] == strategy_id), None)
    suffix = "" if timeframe == "1d" else f"_{timeframe}"
    path = folder / f"{asset.lower()}_{strategy_id}{suffix}.html"
    if spec is not None and spec.get("kind") == "weight":
        if timeframe != "1d":
            raise RuntimeError("the trend weight is not run on 4-hour bars")
        weight = trend_vol_weight(
            bars,
            target_vol=float(params["target_vol"]),
            lookback=int(params["lookback"]),
        )
        result = run_weight_backtest(bars, weight, band=float(params["band"]))
        benchmark = run_backtest(bars, pd.Series(1.0, index=bars.index))
        title = f"{asset} trend score + 40% vol target vs buy-and-hold (paper money)"
    else:
        strategy = STRATEGIES_BY_ID[strategy_id]
        result, benchmark = backtest_window(bars, strategy, params, 0, len(bars))
        title = f"{asset} {strategy.name_en} vs buy-and-hold"
    write_tearsheet(result.equity, benchmark.equity, path, title=title)
    return path
