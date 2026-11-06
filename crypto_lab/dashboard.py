"""Static dashboard. Thai labels, English terms in brackets, no secret keys."""

from __future__ import annotations

import json
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


def build_payload(conn: sqlite3.Connection, prices: dict[str, pd.DataFrame]) -> dict:
    candles = {}
    for asset, frame in prices.items():
        recent = frame.iloc[-900:]
        candles[asset] = [
            {
                "time": index.date().isoformat(),
                "open": round(float(row.open), 2),
                "high": round(float(row.high), 2),
                "low": round(float(row.low), 2),
                "close": round(float(row.close), 2),
            }
            for index, row in recent.iterrows()
        ]
    markers = []
    for trade in _records(conn, "SELECT * FROM paper_trades WHERE strategy != 'buy_and_hold' ORDER BY entry_date"):
        if trade["strategy"] != "sma_filter":
            continue
        color = COLORS.get(trade["strategy"], "#ffffff")
        markers.append(
            {
                "asset": trade["asset"],
                "time": trade["entry_date"],
                "position": "belowBar",
                "color": color,
                "shape": "arrowUp",
                "text": "ซื้อ SMA",
            }
        )
        if trade["closed"] and trade["exit_date"]:
            markers.append(
                {
                    "asset": trade["asset"],
                    "time": trade["exit_date"],
                    "position": "aboveBar",
                    "color": color,
                    "shape": "arrowDown",
                    "text": "ขาย SMA",
                }
            )
    paper_equity = {}
    for row in _records(conn, "SELECT asset, strategy, date, equity FROM paper_equity ORDER BY date"):
        paper_equity.setdefault(row["asset"], {}).setdefault(row["strategy"], []).append(row)
    equity = {}
    for asset, strategies in paper_equity.items():
        equity[asset] = {name: _normalize(_series(points)) for name, points in strategies.items()}

    leaderboard = []
    for row in _records(
        conn,
        """
        SELECT asset, strategy, total_return, cagr, max_drawdown, sharpe, win_rate, n_trades
        FROM backtest_results
        WHERE experiment = 'oos_default'
        ORDER BY asset, strategy
        """,
    ):
        leaderboard.append(
            {
                "asset": row["asset"],
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
        "colors": COLORS,
    }


def render_html(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return HTML.replace("__DATA__", data)


def write_dashboard(conn: sqlite3.Connection, prices: dict[str, pd.DataFrame], folder: Path = DOCS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".nojekyll").write_text("", encoding="utf-8")
    payload = build_payload(conn, prices)
    (folder / "data").mkdir(exist_ok=True)
    (folder / "data" / "dashboard.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    path = folder / "index.html"
    path.write_text(render_html(payload), encoding="utf-8")
    return path


HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>สมุดวิจัย BTC / ETH</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Noto+Sans+Thai:wght@400;600&display=swap" rel="stylesheet" />
<script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root {
    --bg: #07080d;
    --panel: #10141d;
    --line: #1d3d32;
    --text: #d7ffe8;
    --muted: #7f9c8d;
    --neon: #3dff9a;
    --cyan: #4cc9ff;
    --pink: #ff4fd8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: radial-gradient(1200px 500px at 10% -10%, #123226 0%, var(--bg) 55%);
    color: var(--text);
    font-family: "IBM Plex Mono", "Noto Sans Thai", ui-monospace, monospace;
  }
  header, .grid, footer { padding: 16px 18px; }
  header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; border-bottom: 1px solid var(--line); }
  h1 { margin: 0; font-size: 22px; letter-spacing: 0.04em; }
  h1 span { color: var(--neon); }
  .sub { color: var(--muted); font-size: 12px; margin-top: 6px; }
  .stamp { text-align: right; font-size: 12px; color: var(--cyan); }
  .grid { display: grid; grid-template-columns: 1.35fr 1fr 0.9fr; gap: 12px; }
  .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px; min-width: 0; }
  .panel h2 { margin: 0 0 8px; font-size: 13px; color: var(--neon); font-weight: 600; }
  .chart { height: 340px; }
  .chart.short { height: 220px; }
  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th, td { text-align: right; padding: 4px 3px; border-bottom: 1px solid #1a2420; white-space: nowrap; }
  th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
  th { color: var(--muted); font-weight: 400; }
  .pos { color: var(--neon); }
  .neg { color: #ff7b7b; }
  .cash { color: var(--muted); }
  ul { margin: 0; padding-left: 16px; color: var(--muted); font-size: 12px; }
  footer { color: var(--muted); font-size: 12px; }
  a { color: var(--cyan); }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } header { flex-direction: column; align-items: flex-start; } .stamp { text-align: left; } }
</style>
</head>
<body>
<header>
  <div>
    <h1>สมุดวิจัย <span>BTC / ETH</span></h1>
    <div class="sub" id="disclaimer"></div>
  </div>
  <div class="stamp">อัปเดตล่าสุด (Asia/Bangkok)<br /><strong id="updated"></strong><br />ราคาปิดถึง <span id="asof"></span></div>
</header>
<main class="grid">
  <section class="panel">
    <h2>ราคาและจุดซื้อขาย (price + markers)</h2>
    <div style="margin-bottom:8px;font-size:12px">
      <button data-asset="BTC" class="asset">BTC</button>
      <button data-asset="ETH" class="asset">ETH</button>
    </div>
    <p class="sub">จุดบนกราฟคือเส้น 200 วัน (SMA) เท่านั้น เทรดของ MACD และดอนเชียนอยู่ในตารางขวา</p>
    <div id="price" class="chart"></div>
    <h2 style="margin-top:12px">สถานะกระดาษตอนนี้ (open positions)</h2>
    <div id="positions"></div>
  </section>
  <section class="panel">
    <h2>เส้นเงินสมุดกระดาษ เทียบซื้อแล้วถือ (paper equity)</h2>
    <div id="equity" class="chart short"></div>
    <h2 style="margin-top:12px">ตารางอันดับ นอกตัวอย่าง (leaderboard)</h2>
    <div id="board"></div>
  </section>
  <section class="panel">
    <h2>เทรดกระดาษล่าสุด (recent paper trades)</h2>
    <div id="trades"></div>
    <h2 style="margin-top:12px">ทำไมถึงจำลองสามตัวนี้</h2>
    <ul id="reasons"></ul>
    <p class="sub">รายงาน QuantStats (เทียบซื้อแล้วถือทั้งช่วง):
      <a href="tearsheets/btc_sma_filter.html">BTC เส้น 200 วัน</a> ·
      <a href="tearsheets/btc_macd.html">BTC MACD</a> ·
      <a href="tearsheets/btc_donchian.html">BTC ดอนเชียน</a><br />
      <a href="tearsheets/eth_sma_filter.html">ETH เส้น 200 วัน</a> ·
      <a href="tearsheets/eth_macd.html">ETH MACD</a> ·
      <a href="tearsheets/eth_donchian.html">ETH ดอนเชียน</a>
    </p>
  </section>
</main>
<footer>จำลองเท่านั้น เงิน 10,000 ดอลลาร์ต่อกลยุทธ์ต่อเหรียญ ค่าธรรมเนียม 0.10% และ slippage 0.05% ไม่มีการส่งคำสั่งจริง</footer>
<script id="lab-data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById("lab-data").textContent);
document.getElementById("disclaimer").textContent = data.disclaimer;
document.getElementById("updated").textContent = data.updated_bangkok;
document.getElementById("asof").textContent = data.price_as_of || "—";

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return (value * 100).toFixed(1) + "%";
}
function num(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toFixed(2);
}
function chartOptions(height) {
  return {
    height,
    layout: { background: { color: "#10141d" }, textColor: "#d7ffe8", fontFamily: "IBM Plex Mono, Noto Sans Thai, monospace" },
    grid: { vertLines: { color: "#182033" }, horzLines: { color: "#182033" } },
    rightPriceScale: { borderColor: "#1d3d32" },
    timeScale: { borderColor: "#1d3d32" },
    crosshair: { mode: 0 }
  };
}
let priceChart;
let candle;
function drawPrice(asset) {
  const el = document.getElementById("price");
  el.innerHTML = "";
  priceChart = LightweightCharts.createChart(el, chartOptions(340));
  candle = priceChart.addCandlestickSeries({
    upColor: "#3dff9a", downColor: "#ff4fd8", borderUpColor: "#3dff9a", borderDownColor: "#ff4fd8",
    wickUpColor: "#3dff9a", wickDownColor: "#ff4fd8"
  });
  candle.setData(data.candles[asset] || []);
  const times = new Set((data.candles[asset] || []).map(c => c.time));
  const markers = (data.markers || []).filter(m => m.asset === asset && times.has(m.time))
    .map(({time, position, color, shape, text}) => ({time, position, color, shape, text}))
    .sort((a, b) => a.time.localeCompare(b.time) || a.text.localeCompare(b.text));
  candle.setMarkers(markers);
  priceChart.timeScale().fitContent();
  drawEquity(asset);
  document.querySelectorAll("button.asset").forEach(btn => {
    btn.style.borderColor = btn.dataset.asset === asset ? "#3dff9a" : "#1d3d32";
    btn.style.color = btn.dataset.asset === asset ? "#3dff9a" : "#7f9c8d";
  });
}
function drawEquity(asset) {
  const el = document.getElementById("equity");
  el.innerHTML = "";
  const chart = LightweightCharts.createChart(el, chartOptions(220));
  const book = (data.equity && data.equity[asset]) || {};
  Object.keys(book).forEach(name => {
    const series = chart.addLineSeries({
      color: (data.colors && data.colors[name]) || "#ffffff",
      lineWidth: name === "buy_and_hold" ? 1 : 2,
      lineStyle: name === "buy_and_hold" ? 2 : 0,
      title: name
    });
    series.setData(book[name]);
  });
  chart.timeScale().fitContent();
}
document.querySelectorAll("button.asset").forEach(btn => {
  btn.style.background = "transparent";
  btn.style.border = "1px solid #1d3d32";
  btn.style.font = "inherit";
  btn.style.padding = "4px 8px";
  btn.style.marginRight = "6px";
  btn.style.cursor = "pointer";
  btn.addEventListener("click", () => drawPrice(btn.dataset.asset));
});
drawPrice("BTC");

const board = document.getElementById("board");
let html = "<table><tr><th>เหรียญ</th><th>กลยุทธ์</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>Win</th><th>เทรด</th></tr>";
(data.leaderboard || []).forEach(row => {
  const klass = row.cagr >= 0 ? "pos" : "neg";
  html += `<tr><td>${row.asset}</td><td>${row.name_th}</td><td class="${klass}">${pct(row.cagr)}</td><td class="neg">${pct(row.max_drawdown)}</td><td>${num(row.sharpe)}</td><td>${pct(row.win_rate)}</td><td>${row.n_trades}</td></tr>`;
});
board.innerHTML = html + "</table>";

const pos = document.getElementById("positions");
let phtml = "<table><tr><th>เหรียญ</th><th>กลยุทธ์</th><th>สถานะ</th><th>เงินสด</th><th>มูลค่าเหรียญ</th></tr>";
(data.positions || []).forEach(row => {
  const klass = row.side === "long" ? "pos" : "cash";
  phtml += `<tr><td>${row.asset}</td><td>${row.name_th}</td><td class="${klass}">${row.side_th}</td><td>${num(row.cash)}</td><td>${num(row.market_value)}</td></tr>`;
});
pos.innerHTML = phtml + "</table>";

const trades = document.getElementById("trades");
let thtml = "<table><tr><th>เข้า</th><th>ออก</th><th>คู่</th><th>ผล</th></tr>";
(data.trades || []).forEach(row => {
  const ret = row.closed ? pct(row.return_pct) : "ถืออยู่";
  thtml += `<tr><td>${row.entry_date}</td><td>${row.exit_date || "—"}</td><td>${row.asset} ${row.name_th}</td><td>${ret}</td></tr>`;
});
trades.innerHTML = thtml + "</table>";

const reasons = document.getElementById("reasons");
(data.reasons || []).forEach(row => {
  const li = document.createElement("li");
  li.textContent = row.strategy + ": " + row.why_th;
  reasons.appendChild(li);
});
</script>
</body>
</html>
"""
