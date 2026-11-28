"""Paper book replay of the fixed trend-score position, and the next-open fill."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.engine import run_backtest
from crypto_lab.research import backtest_window
from crypto_lab.strategies import STRATEGIES_BY_ID
from crypto_lab.timeframes import hold_daily_signal
from crypto_lab.weights import REBALANCE_BAND, run_weight_backtest, trend_vol_weight


def make_bars(closes, start="2020-01-01"):
    closes = np.asarray(closes, dtype=float)
    index = pd.date_range(start, periods=len(closes), freq="D")
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": closes,
        },
        index=index,
    )


def random_walk(n=400, seed=7, drift=0.001, vol=0.03):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


def start_index(bars, start):
    position = int(bars.index.searchsorted(pd.Timestamp(start)))
    position = min(position, len(bars) - 1)
    return max(position - 1, 0)


def four_hour_bars(daily: pd.DataFrame) -> pd.DataFrame:
    """Six bars per daily stamp. The 00:00 open is the daily open; the close is the daily close."""
    frames = []
    for stamp, row in daily.iterrows():
        index = pd.date_range(stamp, periods=6, freq="4h")
        close = np.linspace(float(row.open), float(row.close), 6)
        open_ = np.concatenate([[float(row.open)], close[:-1]])
        frames.append(
            pd.DataFrame(
                {
                    "open": open_,
                    "high": np.maximum(open_, close),
                    "low": np.minimum(open_, close),
                    "close": close,
                },
                index=index,
            )
        )
    return pd.concat(frames)


def test_half_position_fee_is_on_the_traded_slice_and_one_round_trip_counts_as_one_trade():
    """A round trip is flat, then invested, then flat again. Resizes inside it are not extra trades.

    The fee and the slippage are charged on the dollars that actually trade, here half the account.
    """
    bars = make_bars([100.0] * 6)
    weight = pd.Series([0.5, 0.5, 0.0, 0.0, 0.0, 0.0], index=bars.index)
    result = run_weight_backtest(bars, weight, fee_rate=0.001, slippage_rate=0.0005, band=0.10)

    spend = 0.5 * 10_000
    units = spend * (1.0 - 0.001) / (100.0 * (1.0 + 0.0005))
    proceeds = units * 100.0 * (1.0 - 0.0005) * (1.0 - 0.001)
    end = (10_000 - spend) + proceeds

    assert result.n_rebalances == 2
    assert result.equity.iloc[-1] == pytest.approx(end)
    assert end > 10_000 * (1.0 - 0.001 - 0.0005) ** 2
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["closed"] is True
    assert trade["return"] == pytest.approx(end / 10_000 - 1.0)
    assert trade["return"] < 0


def test_weight_known_on_bar_t_fills_at_the_next_open():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = pd.DataFrame(
        {
            "open": [100.0, 100.0, 130.0, 80.0],
            "high": [100.0, 400.0, 130.0, 80.0],
            "low": [100.0, 100.0, 130.0, 80.0],
            "close": [100.0, 400.0, 130.0, 80.0],
        },
        index=index,
    )
    weight = pd.Series([np.nan, 1.0, 1.0, 1.0], index=index)
    result = run_weight_backtest(bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10)

    # The target is known at the close of bar 1. That close is 400, and it is not the fill.
    assert result.equity.iloc[1] == pytest.approx(10_000.0)
    # Bought at the next open, 130, while that bar's close is also 130.
    assert result.equity.iloc[2] == pytest.approx(10_000.0)
    # Still holding, marked at the last close. No exit fee.
    assert result.final_units == pytest.approx(10_000.0 / 130.0)
    assert result.equity.iloc[3] == pytest.approx(10_000.0 * 80.0 / 130.0)
    assert len(result.trades) == 1
    assert result.trades[0]["closed"] is False
    assert result.trades[0]["entry_price"] == pytest.approx(130.0)


def test_paper_trend_vol_matches_the_weight_engine_on_the_same_daily_bars(tmp_path):
    from crypto_lab.db import connect
    from crypto_lab.paper import sync_paper

    bars = make_bars(random_walk(360, seed=11))
    start = "2020-08-01"
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start=start)

    start_i = start_index(bars, start)
    expected = run_weight_backtest(
        bars.iloc[start_i:],
        trend_vol_weight(bars).iloc[start_i:],
        band=REBALANCE_BAND,
    )
    rows = conn.execute(
        """
        SELECT date, equity FROM paper_equity
        WHERE asset = 'BTC' AND strategy = 'trend_vol' AND timeframe = '1d'
        ORDER BY date
        """
    ).fetchall()
    assert len(rows) == len(expected.equity)
    assert [row["equity"] for row in rows] == pytest.approx(list(expected.equity), rel=1e-9)

    clocks = {
        row["timeframe"]
        for row in conn.execute(
            "SELECT DISTINCT timeframe FROM paper_strategies WHERE strategy = 'trend_vol'"
        )
    }
    assert clocks == {"1d"}
    position = conn.execute(
        "SELECT units, cash, side FROM paper_positions WHERE asset = 'BTC' AND strategy = 'trend_vol'"
    ).fetchone()
    assert position["units"] == pytest.approx(expected.final_units)
    assert position["cash"] == pytest.approx(expected.final_cash)


def test_paper_trend_vol_on_the_4h_tape_matches_the_held_daily_weight(tmp_path):
    from crypto_lab.db import connect
    from crypto_lab.paper import sync_paper

    daily = make_bars(random_walk(90, seed=5))
    intra = four_hour_bars(daily)
    start = "2020-03-01"
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": daily, "ETH": daily.copy()}, start=start, intraday={"BTC": intra, "ETH": intra.copy()})

    start_i = start_index(intra, start)
    held = hold_daily_signal(trend_vol_weight(daily), intra.index).iloc[start_i:]
    expected = run_weight_backtest(intra.iloc[start_i:], held, band=REBALANCE_BAND)
    rows = conn.execute(
        """
        SELECT date, equity FROM paper_equity
        WHERE asset = 'ETH' AND strategy = 'trend_vol' AND timeframe = '1d'
        ORDER BY date
        """
    ).fetchall()
    assert [row["equity"] for row in rows] == pytest.approx(list(expected.equity), rel=1e-9)
    four_hour_native = conn.execute(
        "SELECT COUNT(*) FROM paper_equity WHERE strategy = 'trend_vol' AND timeframe = '4h'"
    ).fetchone()[0]
    assert four_hour_native == 0


def test_later_prices_do_not_change_past_paper_equity(tmp_path):
    from crypto_lab.db import connect
    from crypto_lab.paper import sync_paper

    closes = random_walk(340, seed=9)
    start = "2020-07-01"
    original = make_bars(closes)
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": original, "ETH": original.copy()}, start=start)
    before = conn.execute(
        """
        SELECT date, equity FROM paper_equity
        WHERE asset = 'BTC' AND strategy = 'trend_vol'
        ORDER BY date
        """
    ).fetchall()

    changed_close = closes.copy()
    changed_close[300:] *= 1.8
    changed = make_bars(changed_close)
    sync_paper(conn, {"BTC": changed, "ETH": changed.copy()}, start=start)
    after = conn.execute(
        """
        SELECT date, equity FROM paper_equity
        WHERE asset = 'BTC' AND strategy = 'trend_vol'
        ORDER BY date
        """
    ).fetchall()

    cut = original.index[300]
    kept = [(row["date"], row["equity"]) for row in before if pd.Timestamp(row["date"]) < cut]
    again = [(row["date"], row["equity"]) for row in after if pd.Timestamp(row["date"]) < cut]
    assert kept
    assert again == pytest.approx(kept, rel=1e-9)


def test_binary_paper_strategies_still_match_the_all_in_engine(tmp_path):
    from crypto_lab.db import connect
    from crypto_lab.paper import sync_paper

    bars = make_bars(random_walk(420, seed=4), start="2024-01-01")
    start = "2024-06-01"
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start=start)

    start_i = start_index(bars, start)
    expected, _benchmark = backtest_window(
        bars,
        STRATEGIES_BY_ID["sma_filter"],
        {"window": 200},
        start_i,
        len(bars),
    )
    rows = conn.execute(
        """
        SELECT equity FROM paper_equity
        WHERE asset = 'BTC' AND strategy = 'sma_filter' AND timeframe = '1d'
        ORDER BY date
        """
    ).fetchall()
    assert [row["equity"] for row in rows] == pytest.approx(list(expected.equity), rel=1e-9)
    position = conn.execute(
        "SELECT cash, side FROM paper_positions WHERE asset = 'BTC' AND strategy = 'sma_filter'"
    ).fetchone()
    assert position["side"] in {"long", "cash"}
    if position["side"] == "long":
        assert position["cash"] == pytest.approx(0.0, abs=1e-6)

    hold = run_backtest(bars.iloc[start_i:], pd.Series(1.0, index=bars.index[start_i:]))
    hold_rows = conn.execute(
        """
        SELECT equity FROM paper_equity
        WHERE asset = 'BTC' AND strategy = 'buy_and_hold' AND timeframe = '1d'
        ORDER BY date
        """
    ).fetchall()
    assert [row["equity"] for row in hold_rows] == pytest.approx(list(hold.equity), rel=1e-9)
