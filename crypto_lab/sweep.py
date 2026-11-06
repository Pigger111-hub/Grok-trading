"""Parameter sweep.

Official numbers come from the same next-open engine as the journal, so a
sweep row is comparable to round 1. VectorBT runs the same shifted signals
and its ending equity is stored beside ours. On a simple buy-and-hold the two
endings match to well under a tenth of a percent. VectorBT is not allowed to
replace the official row when that check fails.
"""

from __future__ import annotations

import json

import pandas as pd

from crypto_lab.assumptions import FEE_RATE, INITIAL_CASH, SLIPPAGE_RATE
from crypto_lab.engine import run_backtest
from crypto_lab.research import backtest_window, split_point
from crypto_lab.strategies import STRATEGIES, Strategy


def _json(params: dict) -> str:
    return json.dumps(params, sort_keys=True, ensure_ascii=False)


def _orders_from_signal(signal: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Move a close-of-day target onto the next bar, which is where we trade."""
    want_long = signal.ge(0.5).fillna(False)
    execute = want_long.shift(1).fillna(False).astype(bool)
    return execute, ~execute


def vectorbt_end_values(bars: pd.DataFrame, signals: dict[str, pd.Series]) -> dict[str, float] | None:
    """One batched VectorBT portfolio. None if VectorBT cannot run this batch."""
    if not signals:
        return {}
    try:
        import vectorbt as vbt
    except ImportError:
        return None
    entries = pd.DataFrame({name: _orders_from_signal(sig)[0] for name, sig in signals.items()})
    exits = pd.DataFrame({name: _orders_from_signal(sig)[1] for name, sig in signals.items()})
    try:
        portfolio = vbt.Portfolio.from_signals(
            bars["close"],
            entries,
            exits,
            price=bars["open"],
            fees=FEE_RATE,
            slippage=SLIPPAGE_RATE,
            init_cash=INITIAL_CASH,
            freq="1D",
            direction="longonly",
        )
        ending = portfolio.value().iloc[-1]
    except Exception as exc:
        print(f"VectorBT ข้ามชุดนี้: {exc}")
        return None
    if isinstance(ending, pd.Series):
        return {name: float(ending[name]) for name in signals}
    only = next(iter(signals))
    return {only: float(ending)}


def _window_bars(bars: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    return bars.iloc[start:end]


def sweep_asset(bars: pd.DataFrame, strategies: list[Strategy] | None = None) -> list[dict]:
    """Full, in-sample, and out-of-sample metrics for every published grid point.

    Out-of-sample rows are scored after the parameter list is already fixed.
    Nothing in this function picks a parameter because it did well out of sample.
    """
    strategies = list(strategies or STRATEGIES)
    cut = split_point(len(bars))
    windows = {
        "sweep_full": (0, len(bars)),
        "sweep_is": (0, cut),
        "sweep_oos": (cut, len(bars)),
    }
    rows = []
    for experiment, (start, end) in windows.items():
        window = _window_bars(bars, start, end)
        official = []
        combined: dict[str, pd.Series] = {}
        for strategy in strategies:
            for params in strategy.grid:
                result, benchmark = backtest_window(bars, strategy, params, start, end)
                key = _json(params)
                official.append((strategy, params, key, result, benchmark))
                if strategy.kind == "signal":
                    signal = strategy.generate(bars.iloc[:end], **params).iloc[start:end]
                    combined[f"{strategy.id}::{key}"] = signal
        batched = vectorbt_end_values(window, combined) if combined else None
        for strategy, params, key, result, benchmark in official:
            vectorbt_end = None
            if batched is not None and strategy.kind == "signal":
                vectorbt_end = batched.get(f"{strategy.id}::{key}")
            rows.append(_row(strategy, experiment, params, result, benchmark, vectorbt_end))
    return rows


def _row(strategy, experiment, params, result, benchmark, vectorbt_end) -> dict:
    metrics = result.metrics
    bench = benchmark.metrics
    default = _json(params) == _json(strategy.default_params)
    return {
        "strategy": strategy.id,
        "experiment": experiment,
        "params": _json(params),
        "is_default": int(default),
        "total_return": metrics["total_return"],
        "cagr": metrics["cagr"],
        "max_drawdown": metrics["max_drawdown"],
        "sharpe": metrics["sharpe"],
        "win_rate": metrics["win_rate"],
        "n_trades": metrics["n_trades"],
        "exposure": metrics["exposure"],
        "bh_total_return": bench["total_return"],
        "bh_sharpe": bench["sharpe"],
        "engine_end_value": metrics["end_value"],
        "vectorbt_end_value": vectorbt_end,
    }


def save_sweep(conn, asset: str, rows: list[dict]) -> None:
    conn.execute("DELETE FROM sweep_results WHERE asset = ?", (asset,))
    conn.executemany(
        """
        INSERT INTO sweep_results (
            asset, strategy, experiment, params, is_default, total_return, cagr,
            max_drawdown, sharpe, win_rate, n_trades, exposure, bh_total_return,
            bh_sharpe, vectorbt_end_value, engine_end_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                asset,
                row["strategy"],
                row["experiment"],
                row["params"],
                row["is_default"],
                row["total_return"],
                row["cagr"],
                row["max_drawdown"],
                row["sharpe"],
                row["win_rate"],
                row["n_trades"],
                row["exposure"],
                row["bh_total_return"],
                row["bh_sharpe"],
                row["vectorbt_end_value"],
                row["engine_end_value"],
            )
            for row in rows
        ],
    )


def render_sweep_markdown(frame: pd.DataFrame) -> str:
    """Short Thai note: the in-sample winner is often not the out-of-sample winner."""
    lines = [
        "# กวาดพารามิเตอร์",
        "",
        "แต่ละแถวใช้เครื่องแบ็กเทสต์ตัวเดียวกับรอบแรก (สัญญาณที่ปิดวันนี้ ซื้อขายที่ราคาเปิดวันถัดไป).",
        "คอลัมน์ VectorBT คือเงินปลายทางจาก VectorBT ที่ยิงออเดอร์วันถัดไปเหมือนกัน ไว้ตรวจว่าเครื่องสองตัวไม่หลุดกัน.",
        "การเลือกค่าที่ Sharpe ในตัวอย่างสูงสุด แล้วไปดูนอกตัวอย่าง เป็นการตรวจ overfitting ไม่ใช่คำแนะนำให้ใช้ค่านั้น.",
        "",
    ]
    if frame.empty:
        lines.append("ยังไม่มีผลกวาด")
        return "\n".join(lines)
    for (asset, strategy), group in frame.groupby(["asset", "strategy"]):
        ins = group[group["experiment"] == "sweep_is"].sort_values("sharpe", ascending=False)
        if ins.empty or ins["sharpe"].isna().all():
            continue
        best = ins.iloc[0]
        oos = group[(group["experiment"] == "sweep_oos") & (group["params"] == best["params"])]
        default_oos = group[(group["experiment"] == "sweep_oos") & (group["is_default"] == 1)]
        lines.append(f"## {asset} {strategy}")
        lines.append("")
        lines.append(f"- ค่าที่ Sharpe ในตัวอย่างสูงสุด: `{best['params']}` Sharpe {best['sharpe']:.2f}")
        if len(oos):
            lines.append(f"- ค่านั้นนอกตัวอย่าง: ผลตอบแทนรวม {oos.iloc[0]['total_return'] * 100:.1f}%")
        if len(default_oos):
            lines.append(
                f"- ค่ามาตรฐานนอกตัวอย่าง: ผลตอบแทนรวม {default_oos.iloc[0]['total_return'] * 100:.1f}% "
                f"พารามิเตอร์ `{default_oos.iloc[0]['params']}`"
            )
        lines.append("")
    return "\n".join(lines)
