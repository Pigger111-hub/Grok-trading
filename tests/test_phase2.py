"""Paper book, public-candle merge, sweep rows, and the static dashboard."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.dashboard import write_dashboard
from crypto_lab.db import connect, set_meta
from crypto_lab.indicators import sma
from crypto_lab.market import drop_unfinished_day, merge_recent, parse_ccxt_ohlcv
from crypto_lab.paper import sync_paper
from crypto_lab.strategies import Strategy, sma_filter_signal
from crypto_lab.sweep import sweep_asset, vectorbt_end_values
from crypto_lab.ta_bridge import sma_pandas_ta
from crypto_lab.engine import run_backtest


def _market(n=800, start="2023-01-01"):
    idx = pd.date_range(start, periods=n, freq="D")
    close = np.linspace(100, 220, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close), "low": np.minimum(open_, close), "close": close, "volume": 1.0},
        index=idx,
    )


def test_ccxt_parser_and_unfinished_day_are_removed():
    frame = parse_ccxt_ohlcv([[1_609_459_200_000, 10, 13, 9, 12, 5]], "ccxt:bitstamp:BTC/USD")
    assert frame.iloc[0]["close"] == 12
    assert frame.iloc[0]["date"] == pd.Timestamp("2021-01-01")
    both = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-11-05"), pd.Timestamp("2026-11-06")],
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
            "volume": [1, 1],
            "source": ["x", "x"],
        }
    )
    kept = drop_unfinished_day(both, today=pd.Timestamp("2026-11-06"))
    assert list(kept["date"]) == [pd.Timestamp("2026-11-05")]


def test_merge_recent_keeps_old_history():
    history = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0], "source": ["old"]},
        index=pd.to_datetime(["2020-01-01"]),
    )
    history.index.name = "date"
    fresh = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02"]),
            "open": [2.0],
            "high": [2.0],
            "low": [2.0],
            "close": [2.0],
            "volume": [3.0],
            "source": ["ccxt:bitstamp:BTC/USD"],
        }
    )
    merged = merge_recent(history, fresh)
    assert len(merged) == 2
    assert merged.loc[pd.Timestamp("2020-01-01"), "source"] == "old"
    assert merged.loc[pd.Timestamp("2020-01-02"), "close"] == 2
    replaced = fresh.copy()
    replaced["date"] = pd.to_datetime(["2020-01-01"])
    replaced["close"] = 99.0
    kept = merge_recent(history, replaced, only_newer=True)
    assert kept.loc[pd.Timestamp("2020-01-01"), "close"] == 1.0
    assert len(kept) == 1


def test_pandas_ta_sma_matches_ours():
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    pd.testing.assert_series_equal(sma_pandas_ta(close, 3), sma(close, 3), check_names=False, atol=1e-6)


def test_vectorbt_next_open_matches_the_engine():
    bars = _market(30, start="2021-01-01")
    signal = pd.Series(1.0, index=bars.index)
    ours = run_backtest(bars, signal)
    ends = vectorbt_end_values(bars, {"hold": signal})
    assert ends is not None
    assert ends["hold"] == pytest.approx(ours.metrics["end_value"], rel=0.002)


def test_sweep_scores_the_same_grid_in_and_out_of_sample():
    tiny = Strategy(
        id="sma_filter",
        kind="signal",
        name_en="filter",
        name_th="ตัวกรอง",
        claim_th="",
        source_th="",
        default_params={"window": 3},
        grid=({"window": 3}, {"window": 5}),
        generate=sma_filter_signal,
    )
    rows = sweep_asset(_market(80, start="2022-01-01"), [tiny])
    by_exp = {}
    for row in rows:
        by_exp.setdefault(row["experiment"], set()).add(row["params"])
    assert by_exp["sweep_is"] == by_exp["sweep_oos"] == by_exp["sweep_full"]
    assert any(row["vectorbt_end_value"] is not None for row in rows)


def test_paper_book_is_idempotent(tmp_path):
    bars = _market()
    assets = {"BTC": bars, "ETH": bars.copy()}
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, assets, start="2024-06-01")
    trades = conn.execute("SELECT * FROM paper_trades ORDER BY asset, strategy, entry_date").fetchall()
    equity_sum = conn.execute("SELECT SUM(equity) FROM paper_equity").fetchone()[0]
    assert len(trades) > 0
    sync_paper(conn, assets, start="2024-06-01")
    trades_again = conn.execute("SELECT * FROM paper_trades ORDER BY asset, strategy, entry_date").fetchall()
    equity_again = conn.execute("SELECT SUM(equity) FROM paper_equity").fetchone()[0]
    assert [tuple(row) for row in trades_again] == [tuple(row) for row in trades]
    assert equity_again == pytest.approx(equity_sum)
    count = conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
    distinct = conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT asset, strategy FROM paper_positions)").fetchone()[0]
    assert count == distinct


def test_dashboard_mentions_simulation_and_bangkok(tmp_path):
    conn = connect(tmp_path / "lab.sqlite")
    bars = _market(40, start="2025-01-01")
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start="2025-01-10")
    set_meta(conn, "price_as_of", "2025-02-09")
    path = write_dashboard(conn, {"BTC": bars, "ETH": bars.copy()}, folder=tmp_path / "docs")
    text = path.read_text(encoding="utf-8")
    assert "สมุดวิจัย" in text
    assert "Asia/Bangkok" in text
    assert "ไม่ใช้ API key" in text
    assert "lightweight-charts@4.2.1" in text
