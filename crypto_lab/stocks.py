"""When to buy a stock index fund: four questions answered on past prices.

  1. I have a lump of money. Buy it all now, or spread it over 12 months?
  2. Should I wait for the price to drop 10% or 20% before buying?
  3. Does "only hold above the 200-day average" help with stocks?
  4. Where is the price today, and what happened after days like today?

Prices come from Yahoo Finance and are adjusted for dividends and splits, so
the returns are total returns. Funds are used instead of single companies on
purpose: one company can go to zero, an index fund is much less likely to.

This is research on old prices. Nothing here places an order.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from crypto_lab.data import CACHE_DIR, http_get_json
from crypto_lab.engine import run_backtest
from crypto_lab.indicators import sma
from crypto_lab.metrics import compute_metrics
from crypto_lab.strategies import sma_filter_signal

STOCK_CACHE = CACHE_DIR / "stocks"

# Yahoo symbol -> what it is, in plain words.
STOCKS = {
    "SPY": "กองทุน ETF ตามดัชนี S&P 500 (หุ้นใหญ่สหรัฐ 500 ตัว)",
    "QQQ": "กองทุน ETF ตามดัชนี Nasdaq-100 (หุ้นเทคโนโลยีใหญ่สหรัฐ)",
    "TDEX.BK": "กองทุน ETF ตามดัชนี SET50 (หุ้นใหญ่ไทย 50 ตัว)",
}

# Stock markets are closed on weekends: about 252 trading days a year, 21 a month.
STOCK_PERIODS_PER_YEAR = 252
BARS_PER_MONTH = 21

# 0.15% per trade is near what Thai brokers charge online before VAT.
# Assumption, not a quote from any broker.
STOCK_FEE_RATE = 0.0015
STOCK_SLIPPAGE_RATE = 0.0005

DRAWDOWN_BUCKETS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01))


def parse_yahoo_chart(payload: dict, symbol: str) -> pd.DataFrame:
    """Dividend-adjusted daily candles. Rows without a close are dropped."""
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert(None).normalize(),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "raw_close": quote["close"],
            "adj_close": adjusted,
            "volume": quote["volume"],
        }
    ).set_index("date")
    frame = frame.astype(float).dropna(subset=["open", "high", "low", "raw_close", "adj_close"])
    frame = frame[(frame["raw_close"] > 0) & (frame["open"] > 0)]
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    factor = frame["adj_close"] / frame["raw_close"]
    out = pd.DataFrame(
        {
            "open": frame["open"] * factor,
            "high": frame["high"] * factor,
            "low": frame["low"] * factor,
            "close": frame["adj_close"],
            "raw_close": frame["raw_close"],
            "volume": frame["volume"].fillna(0.0),
        }
    )
    out["source"] = f"yahoo:{symbol}"
    out.index.name = "date"
    return out


def fetch_stock(symbol: str) -> pd.DataFrame:
    payload = http_get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        {"period1": 0, "period2": 4102444800, "interval": "1d", "events": "div,splits"},
    )
    return parse_yahoo_chart(payload, symbol)


def _cache_path(symbol: str, cache_dir: Path = STOCK_CACHE) -> Path:
    return cache_dir / f"{symbol.lower().replace('.', '_')}_daily.csv"


def update_stocks(cache_dir: Path = STOCK_CACHE) -> dict[str, pd.DataFrame]:
    """Download every fund and overwrite the cache. Drops today's unfinished candle."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.now(tz="UTC").tz_convert(None).normalize()
    out = {}
    for symbol in STOCKS:
        frame = fetch_stock(symbol)
        frame = frame[frame.index < today]
        if len(frame) < 1000:
            raise RuntimeError(f"{symbol}: ได้ข้อมูลมาแค่ {len(frame)} วัน น้อยเกินไป")
        frame.round(6).to_csv(_cache_path(symbol, cache_dir))
        out[symbol] = frame
    return out


def load_stocks(cache_dir: Path = STOCK_CACHE) -> dict[str, pd.DataFrame]:
    out = {}
    for symbol in STOCKS:
        path = _cache_path(symbol, cache_dir)
        if path.exists():
            out[symbol] = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    return out


def lump_vs_dca(
    bars: pd.DataFrame,
    months: int = 12,
    cost: float = STOCK_FEE_RATE + STOCK_SLIPPAGE_RATE,
) -> dict:
    """All in on day one, against equal buys every month for `months` months.

    One comparison per starting month, measured on the day of the last buy's
    month end. Money waiting to be invested earns 0%. After the last buy both
    sides hold the same fund, so the gap in percent stays the same from then on.
    """
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    need = months * BARS_PER_MONTH
    gaps = []
    for start in range(0, len(bars) - need, BARS_PER_MONTH):
        end_price = closes[start + need - 1]
        lump = end_price / opens[start] * (1.0 - cost)
        buys = opens[start : start + need : BARS_PER_MONTH]
        dca = float(np.mean(end_price / buys)) * (1.0 - cost)
        gaps.append(lump / dca - 1.0)
    gaps = np.array(gaps)
    if len(gaps) == 0:
        return {"n_starts": 0}
    return {
        "n_starts": len(gaps),
        "lump_wins": float((gaps > 0).mean()),
        "median_gap": float(np.median(gaps)),
        "worst_decile_gap": float(np.quantile(gaps, 0.10)),
        "best_decile_gap": float(np.quantile(gaps, 0.90)),
    }


def wait_for_dip(
    bars: pd.DataFrame,
    dip: float = 0.10,
    horizon_bars: int = 5 * STOCK_PERIODS_PER_YEAR,
    cost: float = STOCK_FEE_RATE + STOCK_SLIPPAGE_RATE,
) -> dict:
    """Hold cash until the close is `dip` below its highest close so far, then buy and hold.

    Compared with buying on day one. Start dates where the price is already
    that far down are left out: there is nothing to wait for, both sides buy
    on the same day. If the dip never comes inside the horizon, the waiting
    money is still cash at the end.
    """
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    peak = np.maximum.accumulate(closes)
    dipped = closes <= peak * (1.0 - dip)
    # next_dip[i] = first row j >= i where the dip rule is true, or n if none.
    next_dip = np.full(n + 1, n, dtype=int)
    for i in range(n - 1, -1, -1):
        next_dip[i] = i if dipped[i] else next_dip[i + 1]
    gaps = []
    never = 0
    skipped = 0
    for start in range(0, n - horizon_bars - 1, BARS_PER_MONTH):
        if dipped[start]:
            skipped += 1
            continue
        end = start + horizon_bars
        now = closes[end] / opens[start + 1] * (1.0 - cost)
        signal_row = next_dip[start]
        if signal_row + 1 <= end:
            waited = closes[end] / opens[signal_row + 1] * (1.0 - cost)
        else:
            waited = 1.0
            never += 1
        gaps.append(waited / now - 1.0)
    gaps = np.array(gaps)
    if len(gaps) == 0:
        return {"n_starts": 0, "already_down": skipped}
    return {
        "n_starts": len(gaps),
        "already_down": skipped,
        "waiting_wins": float((gaps > 0).mean()),
        "median_gap": float(np.median(gaps)),
        "never_bought": never / len(gaps),
    }


def drawdown_from_high(close: pd.Series) -> pd.Series:
    """How far below the highest close so far, as a positive number. 0.12 means 12% below."""
    return 1.0 - close / close.cummax()


def forward_by_state(bars: pd.DataFrame, horizon_bars: int = STOCK_PERIODS_PER_YEAR) -> pd.DataFrame:
    """What the next year looked like, grouped by where the price stood on the day.

    Neighbouring days share most of their next year, so the day counts are much
    bigger than the number of independent examples.
    """
    close = bars["close"]
    forward = close.shift(-horizon_bars) / close - 1.0
    average = sma(close, 200)
    depth = drawdown_from_high(close)
    known = forward.notna() & average.notna()
    rows = []

    def add(label: str, mask: pd.Series) -> None:
        picked = forward[mask & known]
        rows.append(
            {
                "state": label,
                "days": int(len(picked)),
                "mean": float(picked.mean()) if len(picked) else float("nan"),
                "median": float(picked.median()) if len(picked) else float("nan"),
                "positive": float((picked > 0).mean()) if len(picked) else float("nan"),
                "worst": float(picked.min()) if len(picked) else float("nan"),
            }
        )

    add("ทุกวัน", pd.Series(True, index=close.index))
    add("ราคาเหนือเส้น 200 วัน", close > average)
    add("ราคาใต้เส้น 200 วัน", close <= average)
    for low, high in DRAWDOWN_BUCKETS:
        add(bucket_label(low, high), (depth >= low) & (depth < high))
    return pd.DataFrame(rows)


def bucket_label(low: float, high: float) -> str:
    if high > 1.0:
        return f"ต่ำกว่าจุดสูงสุดเกิน {low * 100:.0f}%"
    return f"ต่ำกว่าจุดสูงสุด {low * 100:.0f}–{high * 100:.0f}%"


def status_today(bars: pd.DataFrame) -> dict:
    close = bars["close"]
    average = sma(close, 200)
    depth = float(drawdown_from_high(close).iloc[-1])
    bucket = next(bucket_label(low, high) for low, high in DRAWDOWN_BUCKETS if low <= depth < high)
    return {
        "date": bars.index[-1].date().isoformat(),
        "price": float(bars["raw_close"].iloc[-1]) if "raw_close" in bars else float(close.iloc[-1]),
        "vs_sma200": float(close.iloc[-1] / average.iloc[-1] - 1.0),
        "above_sma200": bool(close.iloc[-1] > average.iloc[-1]),
        "drawdown": depth,
        "bucket": bucket,
    }


def filter_vs_hold(bars: pd.DataFrame) -> dict:
    """The 200-day rule against holding, both starting once the average exists."""
    signal = sma_filter_signal(bars)
    start = signal.first_valid_index()
    window = bars.loc[start:]
    costs = {"fee_rate": STOCK_FEE_RATE, "slippage_rate": STOCK_SLIPPAGE_RATE}
    rule = run_backtest(window, signal.loc[start:], **costs)
    hold = run_backtest(window, pd.Series(1.0, index=window.index), **costs)
    out = {"start": window.index[0].date().isoformat()}
    for name, result in (("rule", rule), ("hold", hold)):
        out[name] = compute_metrics(
            result.equity, result.trades, result.held, periods_per_year=STOCK_PERIODS_PER_YEAR
        )
        out[name + "_returns"] = result.equity.pct_change().dropna()
    return out
