"""Write the database, CSV copies, tear sheets, and the static dashboard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from crypto_lab.dashboard import write_dashboard
from crypto_lab.data import CACHE_DIR
from crypto_lab.db import set_meta
from crypto_lab.paper import PAPER_BOOK
from crypto_lab.sweep import render_sweep_markdown, save_sweep, sweep_asset
from crypto_lab.tearsheet import write_strategy_tearsheet

ROOT = Path(__file__).resolve().parents[1]


def save_ohlcv(frame: pd.DataFrame, path: Path) -> None:
    out = frame.copy()
    if out.index.name == "date" or "date" not in out.columns:
        out = out.reset_index()
    out.to_csv(path, index=False)


def save_backtests(conn: sqlite3.Connection, frame: pd.DataFrame) -> None:
    conn.execute("DELETE FROM backtest_results")
    conn.executemany(
        """
        INSERT INTO backtest_results (
            asset, timeframe, strategy, experiment, params, total_return, cagr, max_drawdown,
            sharpe, win_rate, n_trades, exposure, bh_total_return, bh_sharpe,
            bh_max_drawdown, beat_bh_return, beat_bh_sharpe
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.asset,
                getattr(row, "timeframe", "1d"),
                row.strategy,
                row.experiment,
                row.params,
                row.total_return,
                row.cagr,
                row.max_drawdown,
                row.sharpe,
                row.win_rate,
                int(row.n_trades),
                row.exposure,
                row.bh_total_return,
                row.bh_sharpe,
                row.bh_max_drawdown,
                int(bool(row.beat_bh_return)),
                int(bool(row.beat_bh_sharpe)),
            )
            for row in frame.itertuples(index=False)
        ],
    )


def export_csv(conn: sqlite3.Connection) -> None:
    folder = ROOT / "data"
    for name in ("backtest_results", "sweep_results", "paper_trades", "paper_positions"):
        table = pd.read_sql_query(f"SELECT * FROM {name}", conn)
        table.to_csv(folder / f"{name}.csv", index=False)


def run_sweep_and_sheets(
    conn: sqlite3.Connection,
    assets: dict[str, pd.DataFrame],
    timeframe: str = "1d",
) -> pd.DataFrame:
    frames = []
    for asset, bars in assets.items():
        print(f"กวาดพารามิเตอร์ {asset} {timeframe} ...")
        rows = sweep_asset(bars)
        for row in rows:
            row["asset"] = asset
            row["timeframe"] = timeframe
        save_sweep(conn, asset, rows, timeframe=timeframe)
        frames.append(pd.DataFrame(rows))
    sweep = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    (ROOT / "results" / "sweep.md").write_text(render_sweep_markdown(sweep), encoding="utf-8")
    folder = ROOT / "docs" / "tearsheets"
    for asset, bars in assets.items():
        for spec in PAPER_BOOK:
            print(f"รายงาน QuantStats {asset} {spec['id']} ...")
            try:
                write_strategy_tearsheet(bars, asset, spec["id"], spec["params"], folder, timeframe=timeframe)
            except Exception as exc:
                print(f"ข้าม tear sheet {asset} {spec['id']}: {exc}")
    return sweep


def publish(
    conn: sqlite3.Connection,
    assets: dict[str, pd.DataFrame],
    intraday: dict[str, pd.DataFrame] | None = None,
) -> None:
    chart_prices = intraday or assets
    latest = min(frame.index.max() for frame in chart_prices.values())
    stamp = pd.Timestamp(latest)
    as_of = stamp.strftime("%Y-%m-%d %H:%M UTC") if stamp != stamp.normalize() else stamp.date().isoformat()
    set_meta(conn, "price_as_of", as_of)
    export_csv(conn)
    for asset, frame in assets.items():
        save_ohlcv(frame, CACHE_DIR / f"{asset.lower()}_usd_daily.csv")
    if intraday:
        for asset, frame in intraday.items():
            save_ohlcv(frame, CACHE_DIR / f"{asset.lower()}_usd_4h.csv")
    write_dashboard(conn, chart_prices)
    conn.commit()
