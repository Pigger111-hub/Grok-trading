"""Round three: partial positions, luck checks, stock entry timing."""

import numpy as np
import pandas as pd
import pytest

from crypto_lab.engine import run_backtest
from crypto_lab.overfit import deflated_sharpe, expected_max_sharpe, pbo_cscv, rolling_starts
from crypto_lab.stocks import (
    BARS_PER_MONTH,
    drawdown_from_high,
    forward_by_state,
    lump_vs_dca,
    parse_yahoo_chart,
    status_today,
    wait_for_dip,
)
from crypto_lab.weights import run_weight_backtest, trend_score, trend_vol_weight, vol_scale


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


def random_walk(n=900, seed=7, drift=0.001, vol=0.03):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


# ------------------------------------------------------------- weights


def test_weights_never_use_later_prices():
    closes = random_walk()
    bars = make_bars(closes)
    changed = closes.copy()
    changed[600:] *= 3.0
    before = trend_vol_weight(bars).iloc[:600]
    after = trend_vol_weight(make_bars(changed)).iloc[:600]
    pd.testing.assert_series_equal(before, after)


def test_weights_stay_between_zero_and_one_and_wait_for_the_slow_average():
    bars = make_bars(random_walk())
    weight = trend_vol_weight(bars)
    assert weight.iloc[:199].isna().all()
    known = weight.dropna()
    assert (known >= 0).all() and (known <= 1).all()
    score = trend_score(bars).dropna()
    assert set(np.round(score.unique(), 6)) <= {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}


def test_wild_prices_get_a_smaller_position_than_calm_prices():
    calm = pd.Series(random_walk(vol=0.005))
    wild = pd.Series(random_walk(vol=0.06))
    assert vol_scale(calm, target_vol=0.40).iloc[-1] == 1.0
    assert vol_scale(wild, target_vol=0.40).iloc[-1] < 0.6


def test_weight_order_fills_at_the_next_open_not_todays_close():
    bars = make_bars([100, 100, 100, 200, 200])
    weight = pd.Series([np.nan, 1.0, 1.0, 1.0, 1.0], index=bars.index)
    result = run_weight_backtest(bars, weight, fee_rate=0.0, slippage_rate=0.0)
    # Weight known at the close of day 1, bought at the open of day 2 (price 100).
    assert result.equity.iloc[1] == pytest.approx(10_000.0)
    assert result.equity.iloc[-1] == pytest.approx(20_000.0)


def test_full_weight_matches_the_all_in_engine():
    bars = make_bars(random_walk(300))
    ones = pd.Series(1.0, index=bars.index)
    partial = run_weight_backtest(bars, ones)
    all_in = run_backtest(bars, ones)
    assert partial.equity.iloc[-1] == pytest.approx(all_in.equity.iloc[-1], rel=1e-9)
    assert partial.n_rebalances == 1


def test_half_weight_holds_about_half_and_small_drifts_do_not_trade():
    bars = make_bars(100.0 * (1.001 ** np.arange(200)))
    half = pd.Series(0.5, index=bars.index)
    result = run_weight_backtest(bars, half, band=0.10)
    assert result.n_rebalances == 1
    assert 0.45 < result.weights.iloc[5] < 0.55


def test_zero_target_sells_everything_and_fees_cost_money():
    bars = make_bars([100.0] * 10)
    weight = pd.Series([1.0] * 4 + [0.0] * 6, index=bars.index)
    result = run_weight_backtest(bars, weight)
    assert result.weights.iloc[-1] == 0.0
    assert result.n_rebalances == 2
    assert result.equity.iloc[-1] < 10_000.0


# ------------------------------------------------------------- overfit


def test_more_tries_raise_the_luck_hurdle_and_lower_the_score():
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.001, 0.02, 2000))
    assert expected_max_sharpe(100, 0.02) > expected_max_sharpe(10, 0.02) > 0
    few = deflated_sharpe(returns, n_trials=2, sharpe_std=0.02)
    many = deflated_sharpe(returns, n_trials=500, sharpe_std=0.02)
    assert 0.0 <= many["dsr"] < few["dsr"] <= 1.0


def test_pbo_is_a_coin_flip_or_worse_for_noise_and_low_for_a_real_winner():
    rng = np.random.default_rng(3)
    noise = pd.DataFrame(rng.normal(0.0, 0.02, (1600, 20)))
    # With no skill, a column that was lucky in one half has less luck left in
    # the other half, so noise scores at or above one half, not below it.
    assert pbo_cscv(noise, n_blocks=10)["pbo"] > 0.4
    real = noise.copy()
    real[0] = real[0] + 0.01
    found = pbo_cscv(real, n_blocks=10)
    assert found["pbo"] < 0.05
    assert found["n_splits"] == 252


def test_rolling_starts_counts_wins_on_every_start_date():
    index = pd.date_range("2020-01-01", periods=400, freq="D")
    up = pd.Series(0.01, index=index)
    flat = pd.Series(0.0, index=index)
    stats = rolling_starts(up, flat, horizon_bars=100, step_bars=50)
    assert stats["n_starts"] == 7
    assert stats["win_return"] == 1.0
    assert rolling_starts(flat, up, horizon_bars=100, step_bars=50)["win_return"] == 0.0


# -------------------------------------------------------------- stocks


def test_yahoo_prices_are_adjusted_for_dividends_and_empty_rows_are_dropped():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1704153600, 1704240000, 1704326400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, None, 110.0],
                                "high": [101.0, None, 112.0],
                                "low": [99.0, None, 109.0],
                                "close": [100.0, None, 110.0],
                                "volume": [10, None, 12],
                            }
                        ],
                        "adjclose": [{"adjclose": [90.0, None, 110.0]}],
                    },
                }
            ]
        }
    }
    frame = parse_yahoo_chart(payload, "TEST")
    assert len(frame) == 2
    assert frame["close"].iloc[0] == pytest.approx(90.0)
    assert frame["open"].iloc[0] == pytest.approx(90.0)
    assert frame["raw_close"].iloc[0] == pytest.approx(100.0)
    assert frame["source"].iloc[0] == "yahoo:TEST"


def test_lump_sum_wins_when_prices_only_rise_and_loses_when_they_only_fall():
    months = 30 * BARS_PER_MONTH
    rising = make_bars(100.0 * (1.001 ** np.arange(months)))
    falling = make_bars(100.0 * (0.999 ** np.arange(months)))
    assert lump_vs_dca(rising)["lump_wins"] == 1.0
    assert lump_vs_dca(rising)["median_gap"] > 0
    assert lump_vs_dca(falling)["lump_wins"] == 0.0


def test_waiting_for_a_dip_that_never_comes_leaves_the_money_in_cash():
    rising = make_bars(100.0 * (1.001 ** np.arange(700)))
    stats = wait_for_dip(rising, dip=0.10, horizon_bars=252)
    assert stats["never_bought"] == 1.0
    assert stats["waiting_wins"] == 0.0
    assert stats["already_down"] == 0


def test_waiting_wins_when_a_crash_comes_right_after_the_start():
    closes = np.concatenate([np.full(30, 100.0), np.full(600, 70.0)])
    stats = wait_for_dip(make_bars(closes), dip=0.10, horizon_bars=252)
    # Only the first start date is before the crash. Later ones are already down.
    assert stats["n_starts"] == 2
    assert stats["waiting_wins"] == 1.0
    assert stats["already_down"] > 0


def test_status_and_forward_table_describe_the_latest_day():
    closes = np.concatenate([100.0 * (1.002 ** np.arange(600)), [200.0]])
    bars = make_bars(closes)
    bars["raw_close"] = bars["close"]
    assert drawdown_from_high(bars["close"]).iloc[10] == 0.0
    status = status_today(bars)
    assert status["drawdown"] > 0.20
    assert status["bucket"] == "ต่ำกว่าจุดสูงสุดเกิน 20%"
    table = forward_by_state(bars, horizon_bars=100)
    every_day = table[table["state"] == "ทุกวัน"].iloc[0]
    # The last 100 days have no "next 100 days" yet, and the first 199 have no average.
    assert every_day["days"] == len(bars) - 100 - 199
