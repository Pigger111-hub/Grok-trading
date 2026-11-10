"""Append closed candles from public feeds. No API key and no orders.

The long history still comes from the download script. A short response must
never delete older rows, and it must not leave a hole in front of the cache.

Coinbase public candles have no 4-hour size (the call returns "Unsupported
granularity"). ETH 4-hour updates therefore start at Bitfinex, the same
source as the stored history. If a feed is down, the next public feed is
tried. api.binance.com answers HTTP 451 from many GitHub runners, so the
Binance fallback is data-api.binance.vision only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from crypto_lab.data import (
    fetch_bitfinex,
    fetch_bitstamp,
    fetch_coinbase_daily,
    http_get_json,
)

# Old daily CCXT pair list. Refresh no longer calls Coinbase for 4-hour bars.
SOURCES = (
    ("BTC", "bitstamp", "BTC/USD"),
    ("ETH", "coinbase", "ETH/USD"),
)


class StalePriceError(RuntimeError):
    """A coin's newest closed candle is older than the bar this run should have."""


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


def parse_binance_klines(raw: list, source: str) -> pd.DataFrame:
    """Binance klines are [open time ms, open, high, low, close, volume, ...]."""
    rows = []
    for candle in raw:
        rows.append(
            {
                "date": pd.to_datetime(int(candle[0]), unit="ms", utc=True).tz_convert(None),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "source": source,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.drop_duplicates("date", keep="last").sort_values("date")


def parse_kraken_ohlc(raw: list, source: str) -> pd.DataFrame:
    """Kraken OHLC rows are [time, open, high, low, close, vwap, volume, count]."""
    rows = []
    for candle in raw:
        rows.append(
            {
                "date": pd.to_datetime(int(float(candle[0])), unit="s", utc=True).tz_convert(None),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[6]),
                "source": source,
            }
        )
    frame = pd.DataFrame(rows)
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


def fetch_kraken_ohlc(pair: str, interval_minutes: int, start: pd.Timestamp) -> pd.DataFrame:
    since = int(pd.Timestamp(start).timestamp())
    payload = http_get_json(
        "https://api.kraken.com/0/public/OHLC",
        {"pair": pair, "interval": interval_minutes, "since": since},
    )
    errors = payload.get("error") or []
    if errors:
        raise RuntimeError(f"kraken {pair}: {errors}")
    result = payload.get("result") or {}
    rows = next((value for key, value in result.items() if key != "last"), [])
    return parse_kraken_ohlc(rows, source=f"kraken:{pair}:{interval_minutes}")


def fetch_binance_vision(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Public klines from data-api.binance.vision. Not api.binance.com (HTTP 451)."""
    step_ms = {"4h": 14_400_000, "1d": 86_400_000}[interval]
    cursor = int(pd.Timestamp(start).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end).timestamp() * 1000)
    rows = []
    seen: set[int] = set()
    while cursor < end_ms:
        payload = http_get_json(
            "https://data-api.binance.vision/api/v3/klines",
            {"symbol": symbol, "interval": interval, "startTime": cursor, "limit": 1000},
        )
        if not isinstance(payload, list) or not payload:
            break
        fresh = []
        for candle in payload:
            stamp = int(candle[0])
            if stamp not in seen:
                seen.add(stamp)
                fresh.append(candle)
        if not fresh:
            break
        rows.extend(fresh)
        nxt = int(payload[-1][0]) + step_ms
        if nxt <= cursor:
            break
        cursor = nxt
        if len(payload) < 1000:
            break
    return parse_binance_klines(rows, source=f"binance.vision:{symbol}:{interval}")


def _utc_datetime(stamp) -> datetime:
    ts = pd.Timestamp(stamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _bitstamp_feed(pair: str, step_seconds: int):
    align_midnight = step_seconds >= 86_400

    def fetch(start, _end):
        return fetch_bitstamp(pair, int(pd.Timestamp(start).timestamp()), step_seconds, align_midnight)

    return fetch


def _bitfinex_feed(symbol: str, interval: str, step_ms: int):
    align_midnight = interval == "1D"

    def fetch(start, _end):
        return fetch_bitfinex(
            symbol,
            int(pd.Timestamp(start).timestamp() * 1000),
            interval,
            step_ms,
            align_midnight,
        )

    return fetch


def _coinbase_daily_feed(product: str):
    def fetch(start, end):
        return fetch_coinbase_daily(product, _utc_datetime(start), _utc_datetime(end))

    return fetch


def _kraken_feed(pair: str, interval_minutes: int):
    def fetch(start, _end):
        return fetch_kraken_ohlc(pair, interval_minutes, start)

    return fetch


def _vision_feed(symbol: str, interval: str):
    def fetch(start, end):
        return fetch_binance_vision(symbol, interval, start, end)

    return fetch


def default_feeds(timeframe: str) -> dict[str, list[tuple]]:
    """Ordered public feeds. The first that returns a fresh, gap-free tail wins."""
    if timeframe == "4h":
        return {
            "BTC": [
                ("bitstamp:btcusd:4h", _bitstamp_feed("btcusd", 14_400)),
                ("kraken:XXBTZUSD:4h", _kraken_feed("XXBTZUSD", 240)),
                ("binance.vision:BTCUSDT:4h", _vision_feed("BTCUSDT", "4h")),
            ],
            "ETH": [
                ("bitfinex:tETHUSD:4h", _bitfinex_feed("tETHUSD", "4h", 14_400_000)),
                ("bitstamp:ethusd:4h", _bitstamp_feed("ethusd", 14_400)),
                ("kraken:XETHZUSD:4h", _kraken_feed("XETHZUSD", 240)),
                ("binance.vision:ETHUSDT:4h", _vision_feed("ETHUSDT", "4h")),
            ],
        }
    if timeframe == "1d":
        return {
            "BTC": [
                ("bitstamp:btcusd:1d", _bitstamp_feed("btcusd", 86_400)),
                ("coinbase:BTC-USD:1d", _coinbase_daily_feed("BTC-USD")),
                ("kraken:XXBTZUSD:1d", _kraken_feed("XXBTZUSD", 1440)),
                ("binance.vision:BTCUSDT:1d", _vision_feed("BTCUSDT", "1d")),
            ],
            "ETH": [
                ("coinbase:ETH-USD:1d", _coinbase_daily_feed("ETH-USD")),
                ("bitfinex:tETHUSD:1d", _bitfinex_feed("tETHUSD", "1D", 86_400_000)),
                ("bitstamp:ethusd:1d", _bitstamp_feed("ethusd", 86_400)),
                ("binance.vision:ETHUSDT:1d", _vision_feed("ETHUSDT", "1d")),
            ],
        }
    raise ValueError(f"unsupported timeframe {timeframe}")


def merge_recent(history: pd.DataFrame, fresh: pd.DataFrame, only_newer: bool = False) -> pd.DataFrame:
    """Add closed bars from a public feed.

    `only_newer` keeps every date already in `history`. The long Bitstamp and
    Bitfinex files stay the backtest source. A live feed may only append a
    candle that is newer than the newest bar we already have.
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


def _naive_utc(now) -> pd.Timestamp:
    if now is None:
        now = pd.Timestamp(datetime.now(timezone.utc))
    now = pd.Timestamp(now)
    if now.tzinfo is not None:
        now = now.tz_convert("UTC").tz_localize(None)
    return now


def _bar_hours(timeframe: str) -> int:
    if timeframe == "1d":
        return 24
    if timeframe == "4h":
        return 4
    raise ValueError(f"unsupported timeframe {timeframe}")


def expected_closed_open(now, bar_hours: int, grace_minutes: int = 10) -> pd.Timestamp:
    """Open time of the newest bar that closed at least `grace_minutes` ago.

    A 4-hour bar is stamped at its open. The bar that opens at 00:00 closes
    at 04:00. A run at 04:20, with 10 minutes of grace, must already have it.
    """
    now = _naive_utc(now)
    deadline = now - pd.Timedelta(minutes=grace_minutes)
    freq = "1D" if bar_hours >= 24 else f"{int(bar_hours)}h"
    closed_at = pd.Timestamp(deadline).floor(freq)
    return closed_at - pd.Timedelta(hours=bar_hours)


def _rows(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["date", "open", "high", "low", "close", "volume", "source"]
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=columns)
    out = frame.copy()
    if "date" not in out.columns:
        out = out.reset_index()
    if "date" not in out.columns:
        raise RuntimeError("candle frame has no date column")
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_convert(None)
    return out


def _history_index(frame: pd.DataFrame) -> pd.DataFrame:
    history = frame.copy()
    if "date" in history.columns:
        history = history.set_index("date")
    history = history.sort_index()
    history.index.name = "date"
    return history


def _has_hole(previous_last, fresh: pd.DataFrame, bar_hours: int) -> bool:
    """True when `fresh` starts more than one bar after the cached candle."""
    if previous_last is None or fresh.empty:
        return False
    earliest = pd.Timestamp(fresh["date"].min())
    return earliest > pd.Timestamp(previous_last) + pd.Timedelta(hours=bar_hours)


def _is_fresh(latest, timeframe: str, now, grace_minutes: int) -> bool:
    if latest is None or pd.isna(latest):
        return False
    expected = expected_closed_open(now, _bar_hours(timeframe), grace_minutes)
    return pd.Timestamp(latest) >= expected


def refresh_cached_prices(
    assets: dict[str, pd.DataFrame],
    limit: int = 10,
    timeframe: str = "1d",
    now=None,
    feeds: dict | None = None,
    grace_minutes: int = 10,
) -> dict[str, pd.DataFrame]:
    """Append candles newer than the cache, walking forward from the last bar.

    `limit` is ignored on purpose. A fixed tail of 12 four-hour bars cannot
    fill a gap left by several missed runs. Each feed is asked for every bar
    from the cached candle through `now`.

    If every feed fails but the cache already contains the bar that should be
    closed, the cache is kept. If any coin is still older than that bar, this
    raises StalePriceError and the job must exit non-zero.
    """
    del limit  # callers used to pass 12; that truncated the catch-up
    now = _naive_utc(now)
    bar_hours = _bar_hours(timeframe)
    catalog = feeds if feeds is not None else default_feeds(timeframe)
    updated: dict[str, pd.DataFrame] = {}
    problems: list[str] = []
    for asset, raw_history in assets.items():
        history = _history_index(raw_history)
        last = pd.Timestamp(history.index.max()) if len(history) else None
        errors: list[str] = []
        chosen = None
        chosen_name = None
        for name, fetch in catalog[asset]:
            start = last if last is not None else now - pd.Timedelta(days=5)
            try:
                fresh = drop_open_bars(_rows(fetch(start, now)), bar_hours, now)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                print(f"{asset} {timeframe}: feed {name} failed: {exc}")
                continue
            if fresh.empty:
                errors.append(f"{name}: no closed candles")
                print(f"{asset} {timeframe}: feed {name} returned no closed candles")
                continue
            if _has_hole(last, fresh, bar_hours):
                errors.append(
                    f"{name}: gap between cached {last} and earliest {pd.Timestamp(fresh['date'].min())}"
                )
                print(
                    f"{asset} {timeframe}: feed {name} leaves a gap after {last}; "
                    f"earliest bar is {pd.Timestamp(fresh['date'].min())}"
                )
                continue
            latest = pd.Timestamp(fresh["date"].max())
            expected = expected_closed_open(now, bar_hours, grace_minutes)
            if latest < expected:
                errors.append(f"{name}: latest {latest} is older than expected {expected}")
                print(
                    f"{asset} {timeframe}: feed {name} is stale: latest {latest}, expected at least {expected}"
                )
                continue
            chosen = fresh
            chosen_name = name
            break
        if chosen is None:
            if _is_fresh(last, timeframe, now, grace_minutes):
                print(
                    f"{asset} {timeframe}: cache already fresh at {last}; "
                    f"live fetch failed, keeping it. {' | '.join(errors)}"
                )
                updated[asset] = history
                continue
            expected = expected_closed_open(now, bar_hours, grace_minutes)
            detail = "; ".join(errors) if errors else "no feeds configured"
            problems.append(
                f"{asset} {timeframe}: latest candle {last} is older than expected {expected}. {detail}"
            )
            continue
        merged = merge_recent(history, chosen, only_newer=True)
        new_last = pd.Timestamp(merged.index.max())
        if not _is_fresh(new_last, timeframe, now, grace_minutes):
            expected = expected_closed_open(now, bar_hours, grace_minutes)
            problems.append(
                f"{asset} {timeframe}: latest candle {new_last} is older than expected {expected} "
                f"after {chosen_name}"
            )
            continue
        print(f"{asset} {timeframe}: using {chosen_name}, latest closed bar {new_last}")
        updated[asset] = merged
    if problems:
        message = "stale price data; this job must fail:\n" + "\n".join(f"- {line}" for line in problems)
        print(message)
        raise StalePriceError(message)
    return updated
