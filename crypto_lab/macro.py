"""Pre-declared macro gates. No parameter search lives in this file.

A gate is True only when the macro fact was already public on that bar's
timestamp. The backtest engine still fills the order on the next bar.

Rules (fixed before any score was read):

* halving_18m: long is allowed on calendar day D only when the previous
  halving is strictly before D and the day count is 1 through 548.
* halving_2y: the same, through day 730.
* m2_yoy_up: year-over-year change in M2 is positive.
* walcl_yoy_up: year-over-year change in the Fed balance sheet is positive.
* fed_falling_3m: the federal funds rate is below its level 3 months earlier.
* fed_not_rising_6m: the federal funds rate is not above its level 6 months earlier.

Halving dates are the reward halvings at blocks 210000, 420000, 630000, and
840000. The new phase starts the next calendar day, including for 4-hour bars.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import pandas as pd

# About 18 months and about 2 years. Not searched.
HALVING_DAYS_18M = 548
HALVING_DAYS_2Y = 730

# H.6 for month M is released on the fourth Tuesday of month M+1, which is
# never later than the 28th. The print is usable on the 1st of month M+2.
M2_LAG_MONTHS = 2

# H.4.1 is dated Wednesday and published Thursday 4:30 p.m. Eastern, or Friday
# when Thursday is a holiday. Usable on Saturday: observation date plus 3 days.
WALCL_LAG_DAYS = 3

# The monthly effective-funds average can be finished only after the last
# business day of the month is published. Usable on the 7th of the next month.
FEDFUNDS_RELEASE_DAY = 7

HALVING_DATES = (
    pd.Timestamp("2012-11-28"),
    pd.Timestamp("2016-07-09"),
    pd.Timestamp("2020-05-11"),
    pd.Timestamp("2024-04-20"),
)


@dataclass(frozen=True)
class MacroRule:
    id: str
    factor: str
    name_th: str
    name_en: str


RULES = (
    MacroRule("halving_18m", "halving", "18 เดือนหลัง halving", "First 18 months after a halving"),
    MacroRule("halving_2y", "halving", "2 ปีหลัง halving", "First 2 years after a halving"),
    MacroRule("m2_yoy_up", "liquidity", "M2 โตจากปีก่อน", "M2 year-over-year growth is positive"),
    MacroRule("walcl_yoy_up", "liquidity", "งบดุลเฟดโตจากปีก่อน", "Fed balance sheet year-over-year growth is positive"),
    MacroRule("fed_falling_3m", "rates", "ดอกเบี้ยเฟดลดลงใน 3 เดือน", "Fed funds below its level 3 months earlier"),
    MacroRule("fed_not_rising_6m", "rates", "ดอกเบี้ยเฟดไม่ขึ้นใน 6 เดือน", "Fed funds not above its level 6 months earlier"),
)

RULES_BY_ID = {rule.id: rule for rule in RULES}


def _as_timestamp(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(None)
    return stamp.normalize()


def _month_start(value) -> pd.Timestamp:
    stamp = _as_timestamp(value)
    return pd.Timestamp(year=int(stamp.year), month=int(stamp.month), day=1)


def m2_available_on(observation_date) -> pd.Timestamp:
    return _month_start(observation_date) + pd.DateOffset(months=M2_LAG_MONTHS)


def walcl_available_on(observation_date) -> pd.Timestamp:
    return _as_timestamp(observation_date) + pd.Timedelta(days=WALCL_LAG_DAYS)


def fedfunds_available_on(observation_date) -> pd.Timestamp:
    nxt = _month_start(observation_date) + pd.DateOffset(months=1)
    return pd.Timestamp(year=int(nxt.year), month=int(nxt.month), day=FEDFUNDS_RELEASE_DAY)


def parse_fred_csv(text: str) -> pd.Series:
    """Read a FRED-style CSV. Missing values ('.') are dropped."""
    frame = pd.read_csv(io.StringIO(text))
    if frame.shape[1] < 2:
        raise ValueError("FRED CSV needs a date column and a value column")
    dates = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(dates))
    series = series[series.index.notna()].dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series.index = pd.DatetimeIndex(series.index).tz_localize(None)
    series.index.name = "observation_date"
    return series


def period_change(
    observations: pd.Series,
    periods: int,
    min_gap_days: int,
    max_gap_days: int,
    available_on,
    mode: str,
) -> pd.DataFrame:
    """Change versus `periods` earlier observations.

    The change is dated on the newer observation and becomes public on that
    observation's own publication date. A gap outside the expected spacing
    (a missing month or week) makes that change missing instead of borrowing
    a more distant print.
    """
    series = pd.Series(observations).dropna().astype(float)
    series.index = pd.DatetimeIndex(pd.to_datetime(series.index))
    if series.index.tz is not None:
        series.index = series.index.tz_convert(None)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    prior = series.shift(periods)
    prior_dates = pd.Series(series.index, index=series.index).shift(periods)
    gap_days = (pd.Series(series.index, index=series.index) - prior_dates).dt.days
    ok = prior.notna() & gap_days.between(min_gap_days, max_gap_days)
    if mode == "ratio":
        changed = series / prior - 1.0
    elif mode == "diff":
        changed = series - prior
    else:
        raise ValueError(f"unknown change mode: {mode}")
    changed = changed.where(ok).replace([np.inf, -np.inf], np.nan).dropna()
    frame = changed.rename("value").reset_index()
    frame.columns = ["obs_date", "value"]
    frame["obs_date"] = pd.to_datetime(frame["obs_date"])
    frame["available"] = frame["obs_date"].map(lambda stamp: _as_timestamp(available_on(stamp)))
    return frame.loc[:, ["obs_date", "available", "value"]]


def asof_public(public: pd.DataFrame, index) -> pd.Series:
    """Last published value whose available date is on or before each bar."""
    index = pd.DatetimeIndex(index)
    if index.tz is not None:
        index = index.tz_convert(None)
    if public.empty:
        return pd.Series(np.nan, index=index, dtype=float)
    right = public.dropna(subset=["available", "value"]).sort_values("available").copy()
    right["available"] = pd.to_datetime(right["available"])
    left = pd.DataFrame({"bar": pd.to_datetime(index)}).sort_values("bar")
    merged = pd.merge_asof(
        left,
        right[["available", "value"]],
        left_on="bar",
        right_on="available",
        direction="backward",
    )
    out = pd.Series(merged["value"].to_numpy(), index=pd.DatetimeIndex(merged["bar"]))
    return out.reindex(index)


def halving_days_since(index) -> pd.Series:
    """Days since the latest halving strictly before this bar's calendar date."""
    raw = pd.DatetimeIndex(index)
    if raw.tz is not None:
        raw = raw.tz_convert(None)
    calendar = raw.normalize()
    halvings = np.array([np.datetime64(stamp.to_datetime64()) for stamp in HALVING_DATES], dtype="datetime64[ns]")
    calendar_np = calendar.to_numpy(dtype="datetime64[ns]")
    position = np.searchsorted(halvings, calendar_np, side="left")
    out = np.full(len(calendar), np.nan)
    has_prior = position > 0
    previous = halvings[np.clip(position - 1, 0, len(halvings) - 1)]
    delta_days = (calendar_np - previous) / np.timedelta64(1, "D")
    out[has_prior] = delta_days[has_prior]
    return pd.Series(out, index=index)


def halving_allow(index, window: int) -> pd.Series:
    days = halving_days_since(index)
    allow = (days > 0) & (days <= int(window))
    return allow.fillna(False).astype(bool)


def apply_gate(signal: pd.Series, allow: pd.Series) -> pd.Series:
    """Let an indicator stay long only where the gate is already on.

    Warmup gaps stay missing, which the engine treats as cash. A closed gate
    forces cash. An open gate does not invent a long the indicator did not want.
    """
    allowed = pd.Series(allow).reindex(signal.index).fillna(False).astype(bool)
    out = signal.copy()
    out = out.mask(signal.notna() & ~allowed, 0.0)
    return out


def _bool_from(values: pd.Series, predicate) -> pd.Series:
    flagged = predicate(values)
    return flagged.fillna(False).astype(bool)


def rule_allow(rule_id: str, index, macros: dict[str, pd.Series]) -> pd.Series:
    if rule_id == "halving_18m":
        return halving_allow(index, HALVING_DAYS_18M)
    if rule_id == "halving_2y":
        return halving_allow(index, HALVING_DAYS_2Y)
    if rule_id == "m2_yoy_up":
        public = period_change(macros["M2SL"], 12, 330, 400, m2_available_on, "ratio")
        return _bool_from(asof_public(public, index), lambda values: values > 0)
    if rule_id == "walcl_yoy_up":
        public = period_change(macros["WALCL"], 52, 358, 372, walcl_available_on, "ratio")
        return _bool_from(asof_public(public, index), lambda values: values > 0)
    if rule_id == "fed_falling_3m":
        public = period_change(macros["FEDFUNDS"], 3, 80, 100, fedfunds_available_on, "diff")
        return _bool_from(asof_public(public, index), lambda values: values < 0)
    if rule_id == "fed_not_rising_6m":
        public = period_change(macros["FEDFUNDS"], 6, 160, 200, fedfunds_available_on, "diff")
        return _bool_from(asof_public(public, index), lambda values: values <= 0)
    raise KeyError(rule_id)
