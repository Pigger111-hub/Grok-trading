"""Assumed cash yield in the paper book. It is not a bank rate.

The research engine still defaults to 0%. The paper book turns on 4% a year,
and only on cash that is actually held after the next-open fill. Buy-and-hold
stays at 0%. A weight known today cannot change today's yield.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crypto_lab.assumptions import FEE_RATE, SLIPPAGE_RATE
from crypto_lab.weights import run_weight_backtest

ROOT = Path(__file__).resolve().parents[1]
DAILY = (1.04) ** (1.0 / 365.0)


def _flat(index, price=100.0) -> pd.DataFrame:
    n = len(index)
    return pd.DataFrame(
        {
            "open": np.full(n, price),
            "high": np.full(n, price),
            "low": np.full(n, price),
            "close": np.full(n, price),
        },
        index=index,
    )


def test_paper_yield_is_four_percent_and_trading_costs_are_unchanged():
    from crypto_lab import assumptions

    assert assumptions.PAPER_CASH_ANNUAL_YIELD == 0.04
    assert FEE_RATE == 0.001
    assert SLIPPAGE_RATE == 0.0005


def test_partial_weight_compounds_only_cash_held_after_the_fill():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = _flat(index)
    weight = pd.Series(0.5, index=index)
    plain = run_weight_backtest(bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10)
    rich = run_weight_backtest(
        bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )

    assert plain.equity.iloc[0] == pytest.approx(10_000)
    # Day 0 has no fill. The whole account is cash, so it earns one day.
    assert rich.equity.iloc[0] == pytest.approx(10_000 * DAILY)
    grown = 10_000 * DAILY
    coin = 0.5 * grown
    cash_after_fill = 0.5 * grown * DAILY
    assert rich.n_rebalances == 1
    assert rich.final_units == pytest.approx(coin / 100.0)
    assert rich.equity.iloc[1] == pytest.approx(coin + cash_after_fill)
    # The held share stays inside the 10% band, so later days only compound cash.
    assert rich.equity.iloc[2] == pytest.approx(coin + cash_after_fill * DAILY)
    assert rich.equity.iloc[3] == pytest.approx(coin + cash_after_fill * DAILY**2)
    assert rich.final_cash == pytest.approx(cash_after_fill * DAILY**2)
    assert rich.equity.iloc[-1] > plain.equity.iloc[-1]
    assert rich.equity.iloc[-1] < 10_000 * DAILY**4


def test_fully_invested_weight_earns_nothing_after_the_cash_is_spent():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = _flat(index, price=50.0)
    weight = pd.Series(1.0, index=index)
    plain = run_weight_backtest(bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10)
    rich = run_weight_backtest(
        bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    assert rich.equity.iloc[0] == pytest.approx(10_000 * DAILY)
    assert rich.final_cash == pytest.approx(0.0)
    for i in range(1, len(bars)):
        assert rich.equity.iloc[i] == pytest.approx(plain.equity.iloc[i] * DAILY)


def test_weight_yield_uses_the_calendar_gap_and_ignores_the_close():
    index = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-12"])
    bars = _flat(index)
    bars.loc[index[2], ["open", "high", "low", "close"]] = 500.0
    weight = pd.Series(0.0, index=index)
    rich = run_weight_backtest(
        bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    assert rich.n_rebalances == 0
    assert rich.equity.iloc[0] == pytest.approx(10_000 * DAILY)
    assert rich.equity.iloc[1] == pytest.approx(10_000 * DAILY**2)
    assert rich.equity.iloc[2] == pytest.approx(10_000 * DAILY**12)


def test_sell_day_yield_is_booked_after_the_round_trip_return():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = _flat(index)
    weight = pd.Series([1.0, 0.0, 0.0, 0.0], index=index)
    plain = run_weight_backtest(bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10)
    rich = run_weight_backtest(
        bars, weight, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    assert rich.trades[0]["return"] == pytest.approx(plain.trades[0]["return"])
    assert rich.trades[0]["closed"] is True
    # Buy at the day-1 open after one cash day. Day 1 is fully invested.
    # The flat weight on day 1 sells at the day-2 open, then that cash earns yield.
    assert rich.equity.iloc[1] == pytest.approx(plain.equity.iloc[1] * DAILY)
    assert rich.equity.iloc[2] == pytest.approx(plain.equity.iloc[2] * DAILY**2)
    assert rich.equity.iloc[3] == pytest.approx(plain.equity.iloc[3] * DAILY**3)


def test_same_day_weight_does_not_turn_cash_yield_on_or_off():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = _flat(index)
    bars.loc[index[-1], "close"] = 50.0
    flat = pd.Series(0.0, index=index)
    late = pd.Series([0.0, 0.0, 0.0, 1.0], index=index)
    flat_result = run_weight_backtest(
        bars, flat, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    late_result = run_weight_backtest(
        bars, late, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    pd.testing.assert_series_equal(flat_result.equity, late_result.equity)
    assert late_result.n_rebalances == 0


def test_future_prices_and_dates_do_not_change_weight_yield_already_accrued():
    index = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"])
    bars = _flat(index, price=10.0)
    weight = pd.Series(0.0, index=index)
    base = run_weight_backtest(
        bars, weight, initial_cash=1_000, fee_rate=0.0, slippage_rate=0.0, band=0.10, cash_annual_yield=0.04
    )
    shocked = bars.copy()
    shocked.loc[shocked.index[2]:, ["open", "high", "low", "close"]] = 1_000.0
    shocked.index = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-20", "2020-02-01"])
    shocked_weight = pd.Series([0.0, 0.0, 1.0, 1.0], index=shocked.index)
    alt = run_weight_backtest(
        shocked,
        shocked_weight,
        initial_cash=1_000,
        fee_rate=0.0,
        slippage_rate=0.0,
        band=0.10,
        cash_annual_yield=0.04,
    )
    assert alt.equity.iloc[0] == pytest.approx(base.equity.iloc[0])
    assert alt.equity.iloc[1] == pytest.approx(base.equity.iloc[1])
    # Still flat on day 2: the long weight is on day 2, so the buy would be day 3.
    assert alt.equity.iloc[2] == pytest.approx(1_000 * DAILY ** (1 + 1 + 18))


def test_default_weight_yield_is_zero():
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    bars = _flat(index)
    weight = pd.Series([0.0, 1.0, 0.0], index=index)
    default = run_weight_backtest(bars, weight, fee_rate=0.001, slippage_rate=0.0005, band=0.10)
    explicit = run_weight_backtest(
        bars, weight, fee_rate=0.001, slippage_rate=0.0005, band=0.10, cash_annual_yield=0.0
    )
    pd.testing.assert_series_equal(default.equity, explicit.equity)
    assert default.final_cash == pytest.approx(explicit.final_cash)


def test_paper_book_pays_assumed_yield_on_idle_cash_and_not_on_buy_and_hold(tmp_path):
    from crypto_lab.db import connect
    from crypto_lab.engine import run_backtest
    from crypto_lab.paper import sync_paper

    index = pd.date_range("2025-01-01", periods=5, freq="D")
    bars = _flat(index)
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start="2025-01-01")

    def equity(strategy: str) -> list[float]:
        rows = conn.execute(
            """
            SELECT equity FROM paper_equity
            WHERE asset = 'BTC' AND strategy = ? AND timeframe = '1d'
            ORDER BY date
            """,
            (strategy,),
        ).fetchall()
        return [row["equity"] for row in rows]

    # Five bars, no signal yet, so the whole account stays cash.
    assert equity("sma_filter")[-1] == pytest.approx(10_000 * DAILY**5)
    assert equity("trend_vol")[-1] == pytest.approx(10_000 * DAILY**5)
    assert equity("macd")[-1] == pytest.approx(10_000 * DAILY**5)
    assert equity("donchian")[-1] == pytest.approx(10_000 * DAILY**5)

    hold = run_backtest(bars, pd.Series(1.0, index=index))
    assert equity("buy_and_hold") == pytest.approx(list(hold.equity))
    assert equity("buy_and_hold")[0] == pytest.approx(10_000)
    assert hold.final_cash == pytest.approx(0.0)


def test_dashboard_labels_the_assumed_yield_as_not_real_interest(tmp_path):
    from crypto_lab.dashboard import write_dashboard
    from crypto_lab.db import connect, set_meta
    from crypto_lab.paper import sync_paper

    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "ดอกเบี้ยสมมติ 4%" in html
    assert "ไม่ใช่ดอกเบี้ยจริง" in html
    assert 'id="cash-yield-note"' in html

    index = pd.date_range("2025-01-01", periods=5, freq="D")
    bars = _flat(index)
    conn = connect(tmp_path / "lab.sqlite")
    sync_paper(conn, {"BTC": bars, "ETH": bars.copy()}, start="2025-01-01")
    set_meta(conn, "price_as_of", "2025-01-05")
    write_dashboard(conn, {"BTC": bars, "ETH": bars.copy()}, folder=tmp_path / "docs")
    payload = json.loads((tmp_path / "docs" / "data" / "dashboard.json").read_text(encoding="utf-8"))
    note = payload["cash_yield_note"]
    assert "ดอกเบี้ยสมมติ 4%" in note
    assert "ไม่ใช่ดอกเบี้ยจริง" in note
    text = (ROOT / ".github" / "workflows" / "paper-dashboard.yml").read_text(encoding="utf-8")
    assert "python scripts/update_lab.py" in text
