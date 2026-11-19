"""Macro gates: publication lag, no lookahead, and the pre-declared keep rule.

These tests do not download anything and do not touch the paper book.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crypto_lab.macro import (
    FEDFUNDS_RELEASE_DAY,
    HALVING_DAYS_18M,
    HALVING_DAYS_2Y,
    RULES,
    WALCL_LAG_DAYS,
    apply_gate,
    asof_public,
    fedfunds_available_on,
    halving_allow,
    halving_days_since,
    m2_available_on,
    parse_fred_csv,
    period_change,
    rule_allow,
    walcl_available_on,
)
from crypto_lab.macro_research import (
    PREDECLARED_VARIANTS,
    evaluate_signal,
    keep_and_improve,
)
from crypto_lab.paper import PAPER_BOOK
from crypto_lab.research import split_point
from crypto_lab.strategies import STRATEGIES_BY_ID

ROOT = Path(__file__).resolve().parents[1]


def _month_ends(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="ME")


def test_publication_calendar_is_the_predeclared_lag():
    # January's M2, whether stamped on the 1st or the 31st, is usable on 1 March.
    assert m2_available_on("2020-01-01") == pd.Timestamp("2020-03-01")
    assert m2_available_on("2020-01-31") == pd.Timestamp("2020-03-01")
    assert m2_available_on("2020-12-31") == pd.Timestamp("2021-02-01")
    # Wednesday print is not usable on Thursday. H.4.1 can slip to Friday.
    assert walcl_available_on("2020-01-08") == pd.Timestamp("2020-01-08") + pd.Timedelta(days=WALCL_LAG_DAYS)
    assert walcl_available_on("2020-01-08") == pd.Timestamp("2020-01-11")
    # Monthly average is usable on the 7th of the next month, not on the 6th.
    assert fedfunds_available_on("2020-01-31") == pd.Timestamp("2020-02-07")
    assert fedfunds_available_on("2020-01-01") == pd.Timestamp("2020-02-07")
    assert FEDFUNDS_RELEASE_DAY == 7


def test_m2_yoy_stays_hidden_until_its_publication_date():
    index = _month_ends("2019-01-31", 20)
    series = pd.Series(np.arange(100, 120), index=index, dtype=float)
    public = period_change(
        series,
        periods=12,
        min_gap_days=330,
        max_gap_days=400,
        available_on=m2_available_on,
        mode="ratio",
    )
    january = public.loc[public["obs_date"] == pd.Timestamp("2020-01-31")].iloc[0]
    assert january["available"] == pd.Timestamp("2020-03-01")
    assert january["value"] == pytest.approx(112 / 100 - 1)

    bars = pd.date_range("2020-02-01", "2020-03-02", freq="D")
    seen = asof_public(public, bars)
    assert pd.isna(seen.loc["2020-02-28"])
    assert seen.loc["2020-03-01"] == pytest.approx(112 / 100 - 1)
    # A later revision of a future month must not change February.
    revised = series.copy()
    revised.iloc[-1] = 999
    public_revised = period_change(
        revised,
        periods=12,
        min_gap_days=330,
        max_gap_days=400,
        available_on=m2_available_on,
        mode="ratio",
    )
    seen_revised = asof_public(public_revised, bars)
    assert pd.isna(seen_revised.loc["2020-02-28"])
    assert seen_revised.loc["2020-03-01"] == pytest.approx(seen.loc["2020-03-01"])


def test_walcl_print_is_not_visible_on_the_release_thursday():
    index = pd.date_range("2018-01-03", periods=80, freq="W-WED")
    series = pd.Series(np.linspace(100, 180, len(index)), index=index)
    public = period_change(
        series,
        periods=52,
        min_gap_days=358,
        max_gap_days=372,
        available_on=walcl_available_on,
        mode="ratio",
    )
    row = public.dropna(subset=["value"]).iloc[0]
    day_before = row["available"] - pd.Timedelta(days=1)
    seen = asof_public(public, pd.DatetimeIndex([day_before, row["available"]]))
    assert pd.isna(seen.iloc[0])
    assert seen.iloc[1] == pytest.approx(row["value"])


def test_fed_funds_flat_is_not_falling_and_is_not_rising():
    index = _month_ends("2020-01-31", 8)
    # Four flat months, then a cut. shift(3) at April is 0; at July is negative.
    series = pd.Series([2, 2, 2, 2, 2, 2, 1, 1], index=index, dtype=float)
    public = period_change(
        series,
        periods=3,
        min_gap_days=80,
        max_gap_days=100,
        available_on=fedfunds_available_on,
        mode="diff",
    )
    april = public.loc[public["obs_date"] == index[3]].iloc[0]
    july = public.loc[public["obs_date"] == index[6]].iloc[0]
    assert april["value"] == pytest.approx(0.0)
    assert april["available"] == pd.Timestamp("2020-05-07")
    assert july["value"] == pytest.approx(-1.0)
    assert july["available"] == pd.Timestamp("2020-08-07")

    bars = pd.DatetimeIndex([pd.Timestamp("2020-05-06"), pd.Timestamp("2020-05-07"), pd.Timestamp("2020-08-07")])
    falling = rule_allow("fed_falling_3m", bars, {"FEDFUNDS": series})
    not_rising = rule_allow("fed_not_rising_6m", bars, {"FEDFUNDS": series})
    # A zero 3-month change is not "falling". The later cut is visible on 7 August.
    assert [bool(item) for item in falling.tolist()] == [False, False, True]
    # The same cut is also "not rising" once the 6-month change is public.
    assert [bool(item) for item in not_rising.tolist()] == [False, False, True]


def test_halving_phase_starts_the_day_after_the_block_and_not_before():
    stamps = pd.to_datetime(
        ["2012-11-28", "2012-11-29", "2020-05-11", "2020-05-11 20:00", "2020-05-12"],
        format="mixed",
    )
    days = halving_days_since(stamps)
    assert pd.isna(days.iloc[0])
    assert days.iloc[1] == 1
    # The halving day itself, including a later 4-hour bar, still uses the previous halving.
    assert days.iloc[2] == days.iloc[3]
    assert days.iloc[2] > HALVING_DAYS_2Y
    assert days.iloc[4] == 1

    window = pd.date_range("2020-05-12", periods=HALVING_DAYS_18M + 2, freq="D")
    allowed = halving_allow(window, HALVING_DAYS_18M)
    assert bool(allowed.iloc[0])
    assert bool(allowed.iloc[HALVING_DAYS_18M - 1])
    assert not bool(allowed.iloc[HALVING_DAYS_18M])
    assert HALVING_DAYS_18M == 548
    assert HALVING_DAYS_2Y == 730


def test_gate_blocks_longs_without_creating_them_or_erasing_warmup():
    index = pd.date_range("2020-01-01", periods=5, freq="D")
    signal = pd.Series([np.nan, np.nan, 1.0, 1.0, 0.0], index=index)
    allow = pd.Series([True, False, False, True, True], index=index)
    gated = apply_gate(signal, allow)
    assert pd.isna(gated.iloc[0]) and pd.isna(gated.iloc[1])
    assert gated.iloc[2] == 0.0
    assert gated.iloc[3] == 1.0
    assert gated.iloc[4] == 0.0


def test_gate_trades_on_the_next_bar_not_the_signal_bar():
    index = pd.date_range("2020-01-01", periods=4, freq="D")
    bars = pd.DataFrame(
        {"open": [10.0, 10.0, 10.0, 20.0], "high": 20.0, "low": 10.0, "close": [10.0, 10.0, 10.0, 20.0]},
        index=index,
    )
    signal = pd.Series(1.0, index=index)
    allow = pd.Series([False, False, True, True], index=index)
    from crypto_lab.engine import run_backtest

    result = run_backtest(bars, apply_gate(signal, allow), fee_rate=0.0, slippage_rate=0.0)
    assert result.held.tolist() == [0.0, 0.0, 0.0, 1.0]
    assert result.equity.iloc[2] == pytest.approx(10_000)


def test_parse_fred_csv_drops_missing_and_reads_either_header():
    text = "observation_date,M2SL\n2020-01-01,10\n2020-02-01,.\n2020-03-01,12\n"
    parsed = parse_fred_csv(text)
    assert list(parsed.index) == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-01")]
    assert parsed.iloc[1] == 12
    alt = parse_fred_csv("DATE,VALUE\n2020-01-31,1.5\n")
    assert alt.iloc[0] == pytest.approx(1.5)


def test_only_six_rules_and_forty_eight_variants_were_predeclared():
    assert [rule.id for rule in RULES] == [
        "halving_18m",
        "halving_2y",
        "m2_yoy_up",
        "walcl_yoy_up",
        "fed_falling_3m",
        "fed_not_rising_6m",
    ]
    assert len(PREDECLARED_VARIANTS) == 48
    indicators = {item["indicator"] for item in PREDECLARED_VARIANTS}
    assert indicators == {"macro_only", "sma_filter", "macd", "donchian"}
    clocks = {item["timeframe"] for item in PREDECLARED_VARIANTS}
    assert clocks == {"1d", "4h"}


def test_macro_rules_are_not_wired_into_the_paper_book_or_live_strategies():
    assert [item["id"] for item in PAPER_BOOK] == ["sma_filter", "macd", "donchian"]
    for rule in RULES:
        assert rule.id not in STRATEGIES_BY_ID
    for required in ("sma_filter", "sma_filter_weekly", "macd", "donchian"):
        assert required in STRATEGIES_BY_ID


def test_dashboard_schedule_is_unchanged():
    text = (ROOT / ".github" / "workflows" / "paper-dashboard.yml").read_text(encoding="utf-8")
    assert 'cron: "15 */4 * * *"' in text
    assert 'cron: "15 1,5,9,13,17,21 * * *"' in text


def test_cached_macro_files_match_the_upstream_series():
    folder = ROOT / "data" / "cache" / "fred"
    m2 = parse_fred_csv((folder / "M2SL.csv").read_text(encoding="utf-8"))
    walcl = parse_fred_csv((folder / "WALCL.csv").read_text(encoding="utf-8"))
    funds = parse_fred_csv((folder / "FEDFUNDS.csv").read_text(encoding="utf-8"))
    # FRED stamps months on the 1st. January 1959 M2 is the familiar 286.6 billion.
    assert m2.index.min() == pd.Timestamp("1959-01-01")
    assert m2.index.max() >= pd.Timestamp("2026-09-01")
    assert float(m2.iloc[0]) == pytest.approx(286.6)
    assert walcl.index.min() == pd.Timestamp("2002-12-18")
    assert walcl.index.max() >= pd.Timestamp("2026-11-11")
    assert float(walcl.iloc[0]) == pytest.approx(719542)
    assert funds.index.min() == pd.Timestamp("1954-07-01")
    assert funds.index.max() >= pd.Timestamp("2026-10-01")
    assert float(funds.iloc[0]) == pytest.approx(0.80)


def test_recorded_verdicts_keep_only_the_18_month_halving_rule():
    verdict = pd.read_csv(ROOT / "results" / "macro_verdicts.csv")
    assert len(verdict) == 48
    accepted = set(verdict.loc[verdict["accepted"], "variant"])
    assert accepted == {"halving_18m__macro_only__1d", "halving_18m__macro_only__4h"}
    assert set(verdict.loc[verdict["improved"], "variant"]) == accepted


def _rising_bars(n=40):
    index = pd.date_range("2021-01-01", periods=n, freq="D")
    close = np.linspace(100, 180, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 1,
            "low": np.minimum(open_, close) - 1,
            "close": close,
        },
        index=index,
    )


def test_evaluate_uses_last_30_percent_and_a_fixed_walk_forward():
    bars = _rising_bars(40)
    signal = pd.Series(1.0, index=bars.index)
    stats = evaluate_signal(bars, signal, "1d", train_bars=10, test_bars=10)
    assert stats["oos_start"] == bars.index[split_point(len(bars))]
    assert stats["wf_start"] == bars.index[10]
    assert stats["oos_return"] > 0

    off = apply_gate(signal, pd.Series(False, index=bars.index))
    flat = evaluate_signal(bars, off, "1d", train_bars=10, test_bars=10)
    assert flat["oos_return"] == pytest.approx(0.0)
    assert flat["wf_return"] == pytest.approx(0.0)
    assert flat["oos_max_drawdown"] == pytest.approx(0.0)


def test_keep_rule_needs_both_coins_on_oos_and_walk_forward():
    rows = pd.DataFrame(
        [
            {"variant": "a", "asset": "BTC", "oos_beat_bh": True, "wf_beat_bh": True, "oos_beat_base": True, "wf_beat_base": False},
            {"variant": "a", "asset": "ETH", "oos_beat_bh": True, "wf_beat_bh": False, "oos_beat_base": True, "wf_beat_base": True},
            {"variant": "b", "asset": "BTC", "oos_beat_bh": True, "wf_beat_bh": True, "oos_beat_base": True, "wf_beat_base": True},
            {"variant": "b", "asset": "ETH", "oos_beat_bh": True, "wf_beat_bh": True, "oos_beat_base": True, "wf_beat_base": True},
        ]
    )
    verdict = keep_and_improve(rows).set_index("variant")
    assert bool(verdict.loc["a", "accepted"]) is False
    assert bool(verdict.loc["b", "accepted"]) is True
    assert bool(verdict.loc["b", "improved"]) is True
    assert bool(verdict.loc["a", "improved"]) is False
