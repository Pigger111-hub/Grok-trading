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

from crypto_lab.research import backtest_window
from crypto_lab.strategies import STRATEGIES_BY_ID


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
    strategy = STRATEGIES_BY_ID[strategy_id]
    result, benchmark = backtest_window(bars, strategy, params, 0, len(bars))
    suffix = "" if timeframe == "1d" else f"_{timeframe}"
    path = folder / f"{asset.lower()}_{strategy_id}{suffix}.html"
    write_tearsheet(
        result.equity,
        benchmark.equity,
        path,
        title=f"{asset} {strategy.name_en} vs buy-and-hold",
    )
    return path
