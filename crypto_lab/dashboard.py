"""Static dashboard data, plus the beginner Thai page shell.

The layout lives in docs/index.html, docs/dashboard.css, and docs/dashboard.js.
This module refreshes docs/data/dashboard.json. It does not change how a
strategy, backtest, or the paper book is calculated.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

COLORS = {
    "sma_filter": "#3dff9a",
    "macd": "#4cc9ff",
    "donchian": "#ff4fd8",
    "buy_and_hold": "#9aa4b2",
}

NAMES_TH = {
    "sma_filter": "เส้น 200 วัน (200-day SMA)",
    "macd": "MACD 12/26/9",
    "donchian": "ดอนเชียน 20/10 (Donchian)",
    "buy_and_hold": "ซื้อแล้วถือ (buy and hold)",
    "sma_cross": "เส้น 50/200 (SMA cross)",
    "rsi": "RSI 14",
    "bollinger": "โบลลินเจอร์ (Bollinger)",
    "dca_weekly": "ทยอยซื้อ 52 สัปดาห์ (DCA)",
}


def _bangkok_now() -> str:
    return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M")


def _records(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def _series(rows: list[dict], value_key: str = "equity") -> list[dict]:
    points = []
    for row in rows:
        value = row[value_key]
        if value is None or pd.isna(value):
            continue
        points.append({"time": row["date"], "value": round(float(value), 4)})
    return points


def _normalize(points: list[dict]) -> list[dict]:
    if not points or points[0]["value"] == 0:
        return points
    base = points[0]["value"]
    return [{"time": point["time"], "value": round(point["value"] / base * 100, 4)} for point in points]


def _unix(value) -> int:
    return int(pd.Timestamp(value).timestamp())


def build_payload(conn: sqlite3.Connection, prices: dict[str, pd.DataFrame]) -> dict:
    candles = {}
    for asset, frame in prices.items():
        recent = frame.iloc[-720:]
        candles[asset] = [
            {
                "time": _unix(index),
                "open": round(float(row.open), 2),
                "high": round(float(row.high), 2),
                "low": round(float(row.low), 2),
                "close": round(float(row.close), 2),
            }
            for index, row in recent.iterrows()
        ]
    markers = []
    for trade in _records(
        conn,
        "SELECT * FROM paper_trades WHERE strategy = 'sma_filter' ORDER BY entry_date",
    ):
        clock = trade.get("timeframe") or "1d"
        color = "#d6ff4a" if clock == "1d" else COLORS["sma_filter"]
        label = "รายวัน" if clock == "1d" else "4ชม."
        markers.append(
            {
                "asset": trade["asset"],
                "time": _unix(trade["entry_date"]),
                "position": "belowBar",
                "color": color,
                "shape": "arrowUp",
                "text": f"ซื้อ {label}",
            }
        )
        if trade["closed"] and trade["exit_date"]:
            markers.append(
                {
                    "asset": trade["asset"],
                    "time": _unix(trade["exit_date"]),
                    "position": "aboveBar",
                    "color": color,
                    "shape": "arrowDown",
                    "text": f"ขาย {label}",
                }
            )
    paper_equity = {}
    names = {}
    colors = {}
    for row in _records(
        conn,
        "SELECT asset, timeframe, strategy, date, equity FROM paper_equity ORDER BY date",
    ):
        key = f"{row['strategy']}|{row['timeframe']}"
        paper_equity.setdefault(row["asset"], {}).setdefault(key, []).append(
            {"date": row["date"], "equity": row["equity"]}
        )
        clock = "รายวัน (1d)" if row["timeframe"] == "1d" else "4 ชั่วโมง (4h)"
        names[key] = f"{NAMES_TH.get(row['strategy'], row['strategy'])} {clock}"
        colors[key] = "#d6ff4a" if row["strategy"] == "sma_filter" and row["timeframe"] == "1d" else COLORS.get(row["strategy"], "#ffffff")
    equity = {}
    for asset, strategies in paper_equity.items():
        equity[asset] = {
            name: _normalize([{"time": _unix(point["date"]), "value": point["equity"]} for point in points])
            for name, points in strategies.items()
        }

    leaderboard = []
    for row in _records(
        conn,
        """
        SELECT asset, timeframe, strategy, total_return, cagr, max_drawdown, sharpe, win_rate, n_trades
        FROM backtest_results
        WHERE experiment = 'oos_default'
        ORDER BY asset, timeframe, strategy
        """,
    ):
        leaderboard.append(
            {
                "asset": row["asset"],
                "timeframe": row["timeframe"],
                "timeframe_th": "รายวัน (1d)" if row["timeframe"] == "1d" else "4 ชั่วโมง (4h)",
                "strategy": row["strategy"],
                "name_th": NAMES_TH.get(row["strategy"], row["strategy"]),
                "book": "นอกตัวอย่าง (out of sample)",
                "cagr": row["cagr"],
                "max_drawdown": row["max_drawdown"],
                "sharpe": row["sharpe"],
                "win_rate": row["win_rate"],
                "n_trades": row["n_trades"],
            }
        )
    positions = _records(conn, "SELECT * FROM paper_positions ORDER BY asset, strategy")
    for position in positions:
        position["name_th"] = NAMES_TH.get(position["strategy"], position["strategy"])
        position["side_th"] = "ถือเหรียญ" if position["side"] == "long" else "เงินสด"
    trades = _records(
        conn,
        """
        SELECT * FROM paper_trades
        WHERE strategy != 'buy_and_hold'
        ORDER BY entry_date DESC
        LIMIT 12
        """,
    )
    for trade in trades:
        trade["name_th"] = NAMES_TH.get(trade["strategy"], trade["strategy"])
    reasons = _records(conn, "SELECT * FROM paper_strategies WHERE selected = 1")
    as_of = conn.execute("SELECT value FROM meta WHERE key = 'price_as_of'").fetchone()
    return {
        "updated_bangkok": _bangkok_now(),
        "price_as_of": as_of["value"] if as_of else None,
        "disclaimer": "นี่คือการจำลองเท่านั้น ไม่มีคำสั่งซื้อขายจริง และไม่ใช้ API key",
        "candles": candles,
        "markers": markers,
        "equity": equity,
        "leaderboard": leaderboard,
        "positions": positions,
        "trades": trades,
        "reasons": reasons,
        "colors": colors,
        "names": names,
    }


PAGE_FILES = ("index.html", "dashboard.css", "dashboard.js")


def install_page(folder: Path) -> Path:
    """Copy the beginner page next to the data. Leave the source files untouched."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in PAGE_FILES:
        source = DOCS / name
        dest = folder / name
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.resolve() == dest.resolve():
            continue
        shutil.copyfile(source, dest)
    return folder / "index.html"


def write_dashboard(conn: sqlite3.Connection, prices: dict[str, pd.DataFrame], folder: Path = DOCS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".nojekyll").write_text("", encoding="utf-8")
    payload = build_payload(conn, prices)
    (folder / "data").mkdir(exist_ok=True)
    (folder / "data" / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return install_page(folder)
