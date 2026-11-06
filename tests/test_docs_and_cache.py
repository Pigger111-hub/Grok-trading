"""The beginner docs and the cached candles stay aligned with the lab."""

from pathlib import Path

import pandas as pd

from crypto_lab.data import load_ohlcv

ROOT = Path(__file__).resolve().parents[1]


def test_readme_tells_a_beginner_the_one_command_and_the_fee():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python scripts/run_all.py" in text
    assert "0.10%" in text
    assert "JOURNAL.md" in text


def test_journal_has_a_next_step_a_future_run_can_find():
    text = (ROOT / "JOURNAL.md").read_text(encoding="utf-8")
    assert "## NEXT_STEPS" in text
    assert "sma_filter" in text
    assert "<!-- RESULTS_START -->" in text
    assert "<!-- COSTS_START -->" in text


def test_cached_ohlcv_covers_the_documented_years():
    btc = load_ohlcv(ROOT / "data" / "cache" / "btc_usd_daily.csv")
    eth = load_ohlcv(ROOT / "data" / "cache" / "eth_usd_daily.csv")
    assert btc.index.min() == pd.Timestamp("2011-08-18")
    assert btc.index.max() >= pd.Timestamp("2026-11-05")
    assert len(btc) > 5000
    assert eth.index.min() == pd.Timestamp("2016-03-09")
    assert eth.index.max() >= pd.Timestamp("2026-11-05")
    assert len(eth) > 3000
    for frame in (btc, eth):
        assert (frame["high"] >= frame["low"]).all()
        assert (frame["close"] > 0).all()
