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


def parse_ccxt_ohlcv(rows: list, source: str, keep_time: bool = False) -> pd.DataFrame:
    """CCXT candles are [milliseconds, open, high, low, close, volume]."""
    parsed = []
    for row in rows:
        ms, open_, high, low, close, volume = row[:6]
        stamp = pd.to_datetime(int(ms), unit="ms", utc=True).tz_convert(None)
        parsed.append(
            {
                "date": stamp if keep_time else stamp.normalize(),
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


def drop_open_bars(frame: pd.DataFrame, bar_hours: int, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Drop a candle whose close is still in the future. Completed 4-hour bars today stay."""
    if frame.empty:
        return frame
    if now is None:
        now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    closed = frame["date"] + pd.Timedelta(hours=bar_hours) <= now
    return frame.loc[closed].copy()


def drop_unfinished_day(frame: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    if frame.empty:
        return frame
    if today is None:
        today = pd.Timestamp(datetime.now(timezone.utc).date())
    return frame.loc[frame["date"] < today].copy()


def fetch_public_ohlcv(exchange_id: str, symbol: str, limit: int = 10, timeframe: str = "1d") -> pd.DataFrame:
    import ccxt

    exchange_cls = getattr(ccxt, exchange_id)
    exchange = exchange_cls({"enableRateLimit": True})
    if exchange.apiKey or exchange.secret:
        raise RuntimeError("public market data was configured with a key; refusing to continue")
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return parse_ccxt_ohlcv(raw, source=f"ccxt:{exchange_id}:{symbol}:{timeframe}", keep_time=timeframe != "1d")


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


def refresh_cached_prices(
    assets: dict[str, pd.DataFrame],
    limit: int = 10,
    timeframe: str = "1d",
) -> dict[str, pd.DataFrame]:
    """Append only candles newer than the cache. Does not replace older history."""
    updated = {}
    errors = []
    bar_hours = 24 if timeframe == "1d" else 4
    for asset, exchange_id, symbol in SOURCES:
        try:
            fresh = drop_open_bars(
                fetch_public_ohlcv(exchange_id, symbol, limit=limit, timeframe=timeframe),
                bar_hours,
            )
        except Exception as exc:  # network or exchange hiccup; keep the cache
            errors.append(f"{asset} {timeframe}: {exc}")
            updated[asset] = assets[asset]
            continue
        updated[asset] = merge_recent(assets[asset], fresh, only_newer=True)
        latest = fresh["date"].max() if len(fresh) else None
        print(f"CCXT {exchange_id} {symbol} {timeframe}: แท่งปิดล่าสุด {latest}")
    if errors and all(updated[a].index.max() == assets[a].index.max() for a, _, _ in SOURCES if a in assets):
        print("คำเตือน: ดึงแท่งใหม่ผ่าน CCXT ไม่สำเร็จ ใช้ไฟล์แคชเดิม")
        for line in errors:
            print(" -", line)
    return updated
