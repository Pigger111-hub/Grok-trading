"""SQLite file for prices, sweep results, and the paper-trading book.

The file is data/lab.sqlite. It is safe to delete and rebuild with
`python scripts/run_all.py`. Nothing in this database is a live order.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "lab.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_results (
    asset TEXT NOT NULL,
    strategy TEXT NOT NULL,
    experiment TEXT NOT NULL,
    params TEXT NOT NULL,
    total_return REAL,
    cagr REAL,
    max_drawdown REAL,
    sharpe REAL,
    win_rate REAL,
    n_trades INTEGER,
    exposure REAL,
    bh_total_return REAL,
    bh_sharpe REAL,
    bh_max_drawdown REAL,
    beat_bh_return INTEGER,
    beat_bh_sharpe INTEGER,
    PRIMARY KEY (asset, strategy, experiment, params)
);

CREATE TABLE IF NOT EXISTS sweep_results (
    asset TEXT NOT NULL,
    strategy TEXT NOT NULL,
    experiment TEXT NOT NULL,
    params TEXT NOT NULL,
    is_default INTEGER NOT NULL,
    total_return REAL,
    cagr REAL,
    max_drawdown REAL,
    sharpe REAL,
    win_rate REAL,
    n_trades INTEGER,
    exposure REAL,
    bh_total_return REAL,
    bh_sharpe REAL,
    vectorbt_end_value REAL,
    engine_end_value REAL,
    PRIMARY KEY (asset, strategy, experiment, params)
);

CREATE TABLE IF NOT EXISTS paper_strategies (
    strategy TEXT PRIMARY KEY,
    params TEXT NOT NULL,
    why_th TEXT NOT NULL,
    selected INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_equity (
    asset TEXT NOT NULL,
    strategy TEXT NOT NULL,
    date TEXT NOT NULL,
    equity REAL NOT NULL,
    PRIMARY KEY (asset, strategy, date)
);

CREATE TABLE IF NOT EXISTS paper_trades (
    asset TEXT NOT NULL,
    strategy TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    exit_date TEXT,
    entry_price REAL,
    exit_price REAL,
    return_pct REAL,
    closed INTEGER NOT NULL,
    PRIMARY KEY (asset, strategy, entry_date)
);

CREATE TABLE IF NOT EXISTS paper_positions (
    asset TEXT NOT NULL,
    strategy TEXT NOT NULL,
    units REAL NOT NULL,
    cash REAL NOT NULL,
    last_price REAL,
    market_value REAL,
    side TEXT NOT NULL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (asset, strategy)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
