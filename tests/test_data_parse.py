"""Parsers for public candle payloads. No network."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from crypto_lab.data import calendar_gaps, normalize_ohlcv, parse_bitfinex, parse_bitstamp


def test_bitfinex_column_order_is_open_close_high_low_volume():
    # Bitfinex documents [MTS, OPEN, CLOSE, HIGH, LOW, VOLUME], not OHLCV.
    raw = [[1_609_459_200_000, 10.0, 12.0, 13.0, 9.0, 5.0]]
    df = parse_bitfinex(raw, source="bitfinex")
    row = df.iloc[0]
    assert row["open"] == 10
    assert row["close"] == 12
    assert row["high"] == 13
    assert row["low"] == 9
    assert row["volume"] == 5
    assert df.index[0] == pd.Timestamp("2021-01-01")


def test_bitstamp_parser_reads_strings():
    raw = [
        {
            "timestamp": "1609459200",
            "open": "10",
            "high": "13",
            "low": "9",
            "close": "12",
            "volume": "5",
        }
    ]
    df = parse_bitstamp(raw, source="bitstamp")
    assert df.iloc[0]["close"] == 12
    assert df.index[0] == pd.Timestamp("2021-01-01")


def test_normalize_drops_bad_bars_duplicates_and_todays_candle():
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    yesterday = today - pd.Timedelta(days=1)
    older = today - pd.Timedelta(days=3)
    frame = pd.DataFrame(
        [
            {"date": older, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "source": "a"},
            # Duplicate of the same day: keep the later copy.
            {"date": older, "open": 2, "high": 3, "low": 1, "close": 2, "volume": 1, "source": "a"},
            # Impossible candle.
            {"date": yesterday, "open": 1, "high": 1, "low": 2, "close": 1, "volume": 1, "source": "a"},
            # Today's candle is still forming.
            {"date": today, "open": 5, "high": 6, "low": 4, "close": 5, "volume": 1, "source": "a"},
        ]
    )
    clean, notes = normalize_ohlcv(frame)
    assert list(clean["close"]) == [2]
    assert notes["dropped_bad"] == 1
    assert notes["dropped_duplicate"] == 1
    assert notes["dropped_incomplete"] == 1


def test_calendar_gaps_lists_missing_days_and_does_not_invent_prices():
    idx = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-05"])
    gaps = calendar_gaps(idx)
    assert gaps == [(pd.Timestamp("2020-01-03"), pd.Timestamp("2020-01-04"))]
