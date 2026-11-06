"""Latest daily candles from public CCXT endpoints. No API key and no orders.

CCXT is only used to read recent OHLCV. The long history still comes from the
download script. A short response must never delete older rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# Public market-data only. create_order is never called.
SOURCES = (
    ("BTC", "bitstamp", "BTC/USD"),
    ("ETH", "coinbase", "ETH/USD"),
)


def parse_ccxt_ohlcv(rows: list, source: str) -> pd.DataFrame:
    """CCXT candles are [milliseconds, open, high, low, close, volume]."""
    parsed = []
    for row in rows:
        ms, open_, high, low, close, volume = row[:6]
        parsed.append(
            {
                "date": pd.to_datetime(int(ms), unit="ms", utc=True).tz_convert(None).normalize(),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "source": source,
            }
        )
    frame = pd.DataFrame(parsed)
    if frame.empty:
        return frame
    return frame.drop_duplicates("date", keep="last").sort_values("date")


def drop_unfinished_day(frame: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame
    if today is None:
        today = pd.Timestamp(datetime.now(timezone.utc).date())
    return frame.loc[frame["date"] < today].copy()


def fetch_public_ohlcv(exchange_id: str, symbol: str, limit: int = 10) -> pd.DataFrame:
    import ccxt

    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls({"enableRateLimit": True})
    if exchange.apiKey or exchange.secret:
        raise RuntimeError("public market data was configured with a key; refusing to continue")
    raw = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
    return parse_ccxt_ohlcv(raw, source=f"ccxt:{exchange_id}:{symbol}")


def merge_recent(history: pd.DataFrame, fresh: pd.DataFrame, only_newer: bool = False) -> pd.DataFrame:
    """Add closed days from a public feed.

    `only_newer` keeps every date already in `history`. The long Bitstamp and
    Bitfinex files stay the backtest source. CCXT is only allowed to append a
    candle that is newer than the newest day we already have.
    """
    if fresh.empty:
        return history
    base = history.copy()
    if only_newer and len(base):
        last = pd.Timestamp(base["date"].max() if "date" in base.columns else base.index.max())
        fresh = fresh.loc[fresh["date"] > last]
        if fresh.empty:
            return history
    if "date" in base.columns:
        base = base.set_index("date")
    incoming = fresh.set_index("date")
    columns = ["open", "high", "low", "close", "volume", "source"]
    for column in columns:
        if column not in base.columns:
            base[column] = pd.NA
    base = pd.concat([base.drop(index=incoming.index, errors="ignore"), incoming[columns]])
    base = base.sort_index()
    base.index.name = "date"
    return base


def refresh_cached_prices(assets: dict[str, pd.DataFrame], limit: int = 10) -> dict[str, pd.DataFrame]:
    """Return cache frames updated with the latest public daily candles."""
    updated = {}
    errors = []
    for asset, exchange_id, symbol in SOURCES:
        try:
            fresh = drop_unfinished_day(fetch_public_ohlcv(exchange_id, symbol, limit=limit))
        except Exception as exc:  # network or exchange hiccup; keep the cache
            errors.append(f"{asset}: {exc}")
            updated[asset] = assets[asset]
            continue
        updated[asset] = merge_recent(assets[asset], fresh, only_newer=True)
        print(f"CCXT {exchange_id} {symbol}: แท่งปิดล่าสุด {fresh['date'].max().date() if len(fresh) else 'ไม่มี'}")
    if errors and all(updated[a].index.max() == assets[a].index.max() for a, _, _ in SOURCES if a in assets):
        print("คำเตือน: ดึงแท่งใหม่ผ่าน CCXT ไม่สำเร็จ ใช้ไฟล์แคชเดิม")
        for line in errors:
            print(" -", line)
    return updated
