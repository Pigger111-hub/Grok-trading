"""Stale candles must fail the job, and a blocked feed must not hide that."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.db import connect
from crypto_lab.market import (
    StalePriceError,
    default_feeds,
    expected_closed_open,
    fetch_binance_vision,
    parse_binance_klines,
    refresh_cached_prices,
)
from crypto_lab.paper import sync_paper


def _candles(start, periods, freq, source="feed", close=100.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq=freq)
    close = np.full(periods, close)
    return pd.DataFrame(
        {
            "date": idx,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1.0,
            "source": source,
        }
    )


def _history(frame: pd.DataFrame) -> pd.DataFrame:
    history = frame.set_index("date").sort_index()
    history.index.name = "date"
    return history


def _book(n=260, start="2023-01-01"):
    daily_idx = pd.date_range(start, periods=n, freq="D")
    close = np.linspace(100, 220, n)
    open_ = np.r_[close[0], close[:-1]]
    daily = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1,
            "low": np.minimum(open_, close) - 1,
            "close": close,
            "volume": 1.0,
        },
        index=daily_idx,
    )
    intra_idx = pd.date_range(start, periods=n * 6, freq="4h")
    intra_close = np.linspace(100, 220, len(intra_idx))
    intra_open = np.r_[intra_close[0], intra_close[:-1]]
    intra = pd.DataFrame(
        {
            "open": intra_open,
            "high": np.maximum(intra_open, intra_close) + 1,
            "low": np.minimum(intra_open, intra_close) - 1,
            "close": intra_close,
            "volume": 1.0,
        },
        index=intra_idx,
    )
    return daily, intra


def test_expected_closed_bar_is_the_last_one_that_has_finished():
    # 04:20 UTC, 10 minutes of grace: the 00:00 bar closed at 04:00 and is required.
    assert expected_closed_open(pd.Timestamp("2026-11-10 04:20"), 4) == pd.Timestamp("2026-11-10 00:00")
    # Five minutes after a close is still inside the grace window.
    assert expected_closed_open(pd.Timestamp("2026-11-10 04:05"), 4) == pd.Timestamp("2026-11-09 20:00")
    # A run delayed to 02:43 cannot yet require the 00:00 bar (it closes at 04:00).
    assert expected_closed_open(pd.Timestamp("2026-11-10 02:43"), 4) == pd.Timestamp("2026-11-09 20:00")
    # Daily bar stamped at midnight is due once that day has closed.
    assert expected_closed_open(pd.Timestamp("2026-11-10 02:43"), 24) == pd.Timestamp("2026-11-09")


def test_binance_vision_klines_use_open_time_and_ohlcv_order():
    raw = [[1_609_459_200_000, "10", "13", "9", "12", "5", 0]]
    frame = parse_binance_klines(raw, source="binance.vision:BTCUSDT:4h")
    assert frame.iloc[0]["open"] == 10
    assert frame.iloc[0]["high"] == 13
    assert frame.iloc[0]["low"] == 9
    assert frame.iloc[0]["close"] == 12
    assert frame.iloc[0]["date"] == pd.Timestamp("2021-01-01")


def test_binance_fallback_uses_the_vision_host_not_the_restricted_api(monkeypatch):
    captured = {}

    def fake_get(url, params=None, retries=4):
        captured["url"] = url
        captured["params"] = params
        return [[1_794_268_800_000, "10", "13", "9", "12", "5"]]

    monkeypatch.setattr("crypto_lab.market.http_get_json", fake_get)
    frame = fetch_binance_vision(
        "ETHUSDT",
        "4h",
        pd.Timestamp("2026-11-10 00:00"),
        pd.Timestamp("2026-11-10 04:20"),
    )
    assert captured["url"].startswith("https://data-api.binance.vision/")
    assert "api.binance.com" not in captured["url"]
    assert captured["params"]["symbol"] == "ETHUSDT"
    assert captured["params"]["interval"] == "4h"
    assert frame.iloc[0]["close"] == 12
    assert frame.iloc[0]["high"] == 13
    assert frame.iloc[0]["low"] == 9


def test_eth_4h_does_not_ask_coinbase_and_has_a_public_fallback():
    names = [name for name, _fetch in default_feeds("4h")["ETH"]]
    assert names[0].startswith("bitfinex")
    assert any("binance.vision" in name for name in names)
    assert not any(name.startswith("coinbase") for name in names)
    btc = [name for name, _fetch in default_feeds("4h")["BTC"]]
    assert btc[0].startswith("bitstamp")
    assert any("binance.vision" in name for name in btc)


def test_primary_failure_falls_back_and_appends_the_fresh_bar():
    cached = _history(_candles("2026-11-09 12:00", 3, "4h", source="old"))
    now = pd.Timestamp("2026-11-10 04:20")

    def coinbase_4h(_start, _end):
        raise RuntimeError("Unsupported granularity")

    def bitfinex(_start, _end):
        return _candles("2026-11-09 12:00", 4, "4h", source="bitfinex:tETHUSD:4h")

    def bitstamp(_start, _end):
        return _candles("2026-11-09 20:00", 2, "4h", source="bitstamp:btcusd:4h")

    updated = refresh_cached_prices(
        {"BTC": cached, "ETH": cached.copy()},
        timeframe="4h",
        now=now,
        feeds={
            "BTC": [("bitstamp:btcusd:4h", bitstamp)],
            "ETH": [("coinbase:ETH-USD:4h", coinbase_4h), ("bitfinex:tETHUSD:4h", bitfinex)],
        },
    )
    assert updated["ETH"].index.max() == pd.Timestamp("2026-11-10 00:00")
    assert updated["ETH"].loc[pd.Timestamp("2026-11-10 00:00"), "source"] == "bitfinex:tETHUSD:4h"
    assert updated["ETH"].loc[pd.Timestamp("2026-11-09 12:00"), "source"] == "old"
    assert updated["BTC"].index.max() == pd.Timestamp("2026-11-10 00:00")


def test_a_short_tail_with_a_hole_is_rejected_for_a_complete_fallback():
    cached = _history(_candles("2026-11-06 00:00", 4, "4h", source="old"))
    assert cached.index.max() == pd.Timestamp("2026-11-06 12:00")
    now = pd.Timestamp("2026-11-10 04:20")
    asked = []

    def short_tail(start, _end):
        asked.append(pd.Timestamp(start))
        # Latest bar only. Twelve of these would still leave the days in between blank.
        return _candles("2026-11-10 00:00", 1, "4h", source="short")

    def full(start, _end):
        asked.append(pd.Timestamp(start))
        return _candles("2026-11-06 12:00", 22, "4h", source="bitfinex:tETHUSD:4h")

    updated = refresh_cached_prices(
        {"BTC": cached, "ETH": cached.copy()},
        timeframe="4h",
        now=now,
        limit=12,
        feeds={
            "BTC": [("full", full)],
            "ETH": [("short", short_tail), ("full", full)],
        },
    )
    eth = updated["ETH"]
    assert eth.index.max() == pd.Timestamp("2026-11-10 00:00")
    assert pd.Timestamp("2026-11-06 16:00") in eth.index
    assert eth.loc[pd.Timestamp("2026-11-10 00:00"), "source"] == "bitfinex:tETHUSD:4h"
    assert asked[0] <= pd.Timestamp("2026-11-06 12:00")


def test_stale_coin_fails_and_names_the_coin():
    cached = _history(_candles("2026-11-06 00:00", 4, "4h", source="old"))
    now = pd.Timestamp("2026-11-10 04:20")

    def ancient(_start, _end):
        return _candles("2026-11-06 00:00", 4, "4h", source="ancient")

    def fresh(_start, _end):
        # Continuous from the cached bar, so only ETH is the stale coin.
        return _candles("2026-11-06 12:00", 22, "4h", source="bitstamp:btcusd:4h")

    with pytest.raises(StalePriceError, match=r"ETH") as raised:
        refresh_cached_prices(
            {"BTC": cached, "ETH": cached.copy()},
            timeframe="4h",
            now=now,
            feeds={
                "BTC": [("bitstamp:btcusd:4h", fresh)],
                "ETH": [("bitfinex:tETHUSD:4h", ancient), ("binance.vision:ETHUSDT:4h", ancient)],
            },
        )
    message = str(raised.value)
    assert "4h" in message
    assert "2026-11-06" in message
    assert "BTC" not in message


def test_every_feed_failing_on_a_stale_cache_names_the_coin():
    cached = _history(_candles("2026-11-09 00:00", 2, "4h", source="old"))

    def blocked(_start, _end):
        raise RuntimeError("HTTP 451 from api.binance.com")

    with pytest.raises(StalePriceError, match=r"ETH") as raised:
        refresh_cached_prices(
            {"BTC": cached, "ETH": cached.copy()},
            timeframe="4h",
            now=pd.Timestamp("2026-11-10 04:20"),
            feeds={
                "BTC": [("bitstamp:btcusd:4h", lambda s, e: _candles("2026-11-09 00:00", 7, "4h"))],
                "ETH": [("binance.vision:ETHUSDT:4h", blocked)],
            },
        )
    assert "451" in str(raised.value)


def test_a_fresh_cache_survives_a_blip_but_a_stale_one_does_not():
    fresh_cache = _history(_candles("2026-11-09 20:00", 2, "4h", source="old"))

    def down(_start, _end):
        raise RuntimeError("timeout")

    kept = refresh_cached_prices(
        {"BTC": fresh_cache, "ETH": fresh_cache.copy()},
        timeframe="4h",
        now=pd.Timestamp("2026-11-10 04:20"),
        feeds={"BTC": [("bitstamp", down)], "ETH": [("bitfinex", down)]},
    )
    assert kept["BTC"].index.max() == pd.Timestamp("2026-11-10 00:00")

    stale_cache = _history(_candles("2026-11-06 12:00", 1, "4h", source="old"))
    with pytest.raises(StalePriceError, match=r"BTC"):
        refresh_cached_prices(
            {"BTC": stale_cache, "ETH": fresh_cache},
            timeframe="4h",
            now=pd.Timestamp("2026-11-10 04:20"),
            feeds={"BTC": [("bitstamp", down)], "ETH": [("bitfinex", down)]},
        )


def _trade_rows(conn):
    return [
        tuple(row)
        for row in conn.execute(
            """
            SELECT asset, timeframe, strategy, entry_date, exit_date, entry_price, exit_price, closed
            FROM paper_trades
            ORDER BY asset, timeframe, strategy, entry_date
            """
        )
    ]


def test_missed_bars_are_replayed_in_order_without_duplicate_trades(tmp_path):
    daily, intra = _book()
    early_daily = daily.iloc[:-2]
    early_intra = intra.iloc[:-8]
    assets_early = {"BTC": early_daily, "ETH": early_daily.copy()}
    intra_early = {"BTC": early_intra, "ETH": early_intra.copy()}
    assets_full = {"BTC": daily, "ETH": daily.copy()}
    intra_full = {"BTC": intra, "ETH": intra.copy()}

    caught_up = connect(tmp_path / "gap.sqlite")
    sync_paper(caught_up, assets_early, start="2023-06-01", intraday=intra_early)
    sync_paper(caught_up, assets_full, start="2023-06-01", intraday=intra_full)
    once = connect(tmp_path / "once.sqlite")
    sync_paper(once, assets_full, start="2023-06-01", intraday=intra_full)

    gap_trades = _trade_rows(caught_up)
    once_trades = _trade_rows(once)
    assert gap_trades == once_trades
    assert len(gap_trades) == len(set(gap_trades))
    last_equity = caught_up.execute("SELECT MAX(date) FROM paper_equity WHERE timeframe = '4h'").fetchone()[0]
    assert last_equity == intra.index[-1].strftime("%Y-%m-%dT%H:%M:%S")
    # A second pass on the same candles must not add trades.
    sync_paper(caught_up, assets_full, start="2023-06-01", intraday=intra_full)
    assert _trade_rows(caught_up) == once_trades
