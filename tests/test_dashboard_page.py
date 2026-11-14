"""The beginner Thai dashboard shell stays readable and does not invent new math."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from crypto_lab.assumptions import INITIAL_CASH
from crypto_lab.dashboard import write_dashboard
from crypto_lab.db import connect, set_meta
from crypto_lab.paper import sync_paper

ROOT = Path(__file__).resolve().parents[1]


def _market(n=40, start="2025-01-01"):
    index = pd.date_range(start, periods=n, freq="D")
    close = pd.Series(range(100, 100 + n), index=index, dtype="float64")
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame(
        {
            "open": open_,
            "high": pd.concat([open_, close], axis=1).max(axis=1),
            "low": pd.concat([open_, close], axis=1).min(axis=1),
            "close": close,
            "volume": 1.0,
        }
    )


def test_beginner_page_is_plain_thai_and_uses_the_json():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "docs" / "dashboard.js").read_text(encoding="utf-8")
    css = (ROOT / "docs" / "dashboard.css").read_text(encoding="utf-8")
    for phrase in (
        "เงินสมมติเท่านั้น ไม่รับประกันกำไร",
        "ข้อมูลอัปเดตล่าสุด",
        "SMA 200",
        "MACD",
        "Donchian",
        "ซื้อแล้วถือเฉยๆ",
        "drawdown",
        "out-of-sample",
        "paper trading",
        "ถือเหรียญ",
        "ถือเงินสด",
        "สมุดวิจัย",
        "Asia/Bangkok",
        "ไม่ใช้ API key",
        "lightweight-charts@4.2.1",
    ):
        assert phrase in html, phrase
    assert "Noto+Sans+Thai" in html
    assert "IBM+Plex+Sans+Thai" in html
    assert "Noto Sans Thai" in css
    assert "IBM Plex Sans Thai" in css
    assert 'fetch("data/dashboard.json")' in js
    assert "const STALE_HOURS = 8" in js
    match = re.search(r"const START_DOLLARS = (\d+);", js)
    assert match and int(match.group(1)) == int(INITIAL_CASH)
    sizes = [int(size) for size in re.findall(r"font-size:\s*(\d+)px", css)]
    assert sizes and min(sizes) >= 16
    payload = json.loads((ROOT / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    assert set(payload["candles"]) >= {"BTC", "ETH"}
    assert payload["positions"]
    assert payload["equity"]["BTC"] and payload["equity"]["ETH"]


def test_weekly_sma_filter_is_not_on_the_paper_dashboard(tmp_path):
    conn = connect(tmp_path / "lab.sqlite")
    bars = _market()
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start="2025-01-10")
    conn.execute(
        """
        INSERT INTO backtest_results (
            asset, timeframe, strategy, experiment, params, total_return, cagr,
            max_drawdown, sharpe, win_rate, n_trades, exposure, bh_total_return,
            bh_sharpe, bh_max_drawdown, beat_bh_return, beat_bh_sharpe
        ) VALUES
            ('BTC', '1d', 'sma_filter_weekly', 'oos_default', '{"window": 200}',
             1.0, 0.2, -0.3, 0.5, 0.3, 4, 0.5, 0.4, 0.4, -0.5, 1, 1),
            ('BTC', '1d', 'sma_filter', 'oos_default', '{"window": 200}',
             2.0, 0.3, -0.2, 0.8, 0.3, 9, 0.6, 0.4, 0.4, -0.5, 1, 1)
        """
    )
    set_meta(conn, "price_as_of", "2025-02-09")
    write_dashboard(conn, {"BTC": bars, "ETH": bars.copy()}, folder=tmp_path / "docs")
    data = json.loads((tmp_path / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    shown = {row["strategy"] for row in data["leaderboard"]}
    assert "sma_filter" in shown
    assert "sma_filter_weekly" not in shown
    assert "sma_filter_weekly" not in json.dumps(data)


def test_write_dashboard_keeps_the_beginner_shell(tmp_path):
    conn = connect(tmp_path / "lab.sqlite")
    bars = _market()
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start="2025-01-10")
    set_meta(conn, "price_as_of", "2025-02-09")
    page = write_dashboard(conn, {"BTC": bars, "ETH": bars.copy()}, folder=tmp_path / "docs")
    text = page.read_text(encoding="utf-8")
    assert "เงินสมมติเท่านั้น ไม่รับประกันกำไร" in text
    assert "สมุดวิจัย" in text
    data = json.loads((tmp_path / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    assert "positions" in data and "equity" in data and "candles" in data
    assert (tmp_path / "docs" / "dashboard.js").is_file()
    assert (tmp_path / "docs" / "dashboard.css").is_file()


def test_ranking_puts_buy_and_hold_beside_the_result_and_flags_stale_prices():
    node = shutil.which("node")
    assert node, "node is required to check the page's ranking helper"
    script = r"""
const path = require("path");
const dash = require(path.resolve("docs/dashboard.js"));
const now = Date.parse("2026-11-10T02:44:00Z");
const eth = Date.parse("2026-11-06T12:00:00Z") / 1000;
const btc = Date.parse("2026-11-09T20:00:00Z") / 1000;
const eightHours = 8 * 60 * 60 * 1000;
if (!dash.priceIsStale(eth, now)) process.exit(2);
if (dash.priceIsStale(btc, now)) process.exit(3);
if (dash.priceIsStale(btc, btc * 1000 + eightHours)) process.exit(4);
if (!dash.priceIsStale(btc, btc * 1000 + eightHours + 1)) process.exit(5);
if (!dash.priceIsStale(null, now)) process.exit(6);
const rows = [
  {strategy:"sma_filter", timeframe:"1d", cash:100, market_value:0},
  {strategy:"donchian", timeframe:"4h", cash:0, market_value:9000},
  {strategy:"macd", timeframe:"1d", cash:0, market_value:8000},
  {strategy:"sma_filter", timeframe:"4h", cash:0, market_value:12000},
  {strategy:"buy_and_hold", timeframe:"4h", cash:0, market_value:7000},
];
const ranked = dash.rankRows(rows);
if (ranked.best.strategy !== "sma_filter" || ranked.best.timeframe !== "4h") process.exit(7);
if (!ranked.benchmark || ranked.benchmark.strategy !== "buy_and_hold") process.exit(8);
if (ranked.rows.some((row) => row.strategy === "buy_and_hold")) process.exit(9);
if (ranked.rows.map((row) => row.value).join(",") !== "12000,9000,8000,100") process.exit(10);
const keys = dash.defaultSeriesKeys(rows);
if (keys[0] !== "sma_filter|4h") process.exit(11);
if (keys.indexOf("buy_and_hold|4h") === -1) process.exit(12);
if (keys.length !== 4) process.exit(13);
const loss = dash.describePnl(9379);
if (loss.tone !== "bad" || loss.label.indexOf("ขาดทุน") === -1) process.exit(14);
const gain = dash.describePnl(16027);
if (gain.tone !== "good" || gain.label.indexOf("กำไร") === -1) process.exit(15);
const gap = dash.describeGap(9658, 8051);
if (gap.tone !== "good" || gap.label.indexOf("มากกว่าซื้อแล้วถือ") === -1) process.exit(16);
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
