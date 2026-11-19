"""Score pre-declared macro gates on the existing indicators.

The gate does not choose indicator parameters. Walk-forward here is the lab's
calendar (skip 2 years, then test the following years) with the published
indicator settings held fixed. Nothing in this module is registered on the
paper book.
"""

from __future__ import annotations

import json

import pandas as pd

from crypto_lab.assumptions import BARS_PER_DAY, WALK_FORWARD_TEST_DAYS, WALK_FORWARD_TRAIN_DAYS
from crypto_lab.engine import run_backtest
from crypto_lab.macro import RULES, apply_gate, rule_allow
from crypto_lab.research import split_point
from crypto_lab.strategies import STRATEGIES_BY_ID
from crypto_lab.walkforward import _fold_bounds

# The indicators named for this round. Parameters are the published defaults,
# including the 200-bar average on the 4-hour clock (not 200 calendar days).
PREDECLARED_INDICATORS = (
    {
        "indicator": "sma_filter",
        "timeframe": "1d",
        "params": {"window": 200},
        "label_th": "เส้น 200 วัน",
    },
    {
        "indicator": "sma_filter",
        "timeframe": "4h",
        "params": {"window": 200},
        "label_th": "เส้น 200 แท่ง 4 ชั่วโมง",
    },
    {
        "indicator": "macd",
        "timeframe": "1d",
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "label_th": "MACD 12/26/9 รายวัน",
    },
    {
        "indicator": "macd",
        "timeframe": "4h",
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "label_th": "MACD 12/26/9 แท่ง 4 ชั่วโมง",
    },
    {
        "indicator": "donchian",
        "timeframe": "1d",
        "params": {"entry": 20, "exit": 10},
        "label_th": "ดอนเชียน 20/10 รายวัน",
    },
    {
        "indicator": "donchian",
        "timeframe": "4h",
        "params": {"entry": 20, "exit": 10},
        "label_th": "ดอนเชียน 20/10 แท่ง 4 ชั่วโมง",
    },
)


def _variants() -> tuple[dict, ...]:
    rows = []
    for rule in RULES:
        for timeframe in ("1d", "4h"):
            rows.append(
                {
                    "variant": f"{rule.id}__macro_only__{timeframe}",
                    "rule": rule.id,
                    "factor": rule.factor,
                    "rule_th": rule.name_th,
                    "indicator": "macro_only",
                    "timeframe": timeframe,
                    "params": {},
                    "label_th": "ตัวกรองอย่างเดียว",
                }
            )
        for spec in PREDECLARED_INDICATORS:
            rows.append(
                {
                    "variant": f"{rule.id}__{spec['indicator']}__{spec['timeframe']}",
                    "rule": rule.id,
                    "factor": rule.factor,
                    "rule_th": rule.name_th,
                    "indicator": spec["indicator"],
                    "timeframe": spec["timeframe"],
                    "params": dict(spec["params"]),
                    "label_th": spec["label_th"],
                }
            )
    return tuple(rows)


PREDECLARED_VARIANTS = _variants()


def indicator_signal(spec: dict, bars: pd.DataFrame) -> pd.Series:
    if spec["indicator"] == "macro_only":
        return pd.Series(1.0, index=bars.index)
    strategy = STRATEGIES_BY_ID[spec["indicator"]]
    return strategy.generate(bars, **spec["params"])


def _beats(left, right) -> bool:
    if left is None or right is None or pd.isna(left) or pd.isna(right):
        return False
    return float(left) > float(right)


def evaluate_signal(
    bars: pd.DataFrame,
    signal: pd.Series,
    timeframe: str,
    train_bars: int | None = None,
    test_bars: int | None = None,
) -> dict:
    """Out-of-sample last 30% and a fixed-parameter walk-forward.

    Both windows start in cash. The signal may use prices from before the
    window. The engine buys or sells at the next bar's open.
    """
    scale = BARS_PER_DAY[timeframe]
    if train_bars is None:
        train_bars = WALK_FORWARD_TRAIN_DAYS * scale
    if test_bars is None:
        test_bars = WALK_FORWARD_TEST_DAYS * scale
    signal = pd.Series(signal).reindex(bars.index)
    cut = split_point(len(bars))
    oos_bars = bars.iloc[cut:]
    oos = run_backtest(oos_bars, signal.iloc[cut:])

    stitched = pd.Series(float("nan"), index=bars.index)
    folds = list(_fold_bounds(len(bars), int(train_bars), int(test_bars)))
    if not folds:
        raise RuntimeError("walk-forward ไม่มีช่วงทดสอบ")
    for start, end in folds:
        stitched.iloc[start:end] = signal.iloc[start:end].to_numpy()
    wf_start = stitched.first_valid_index()
    wf_bars = bars.loc[wf_start:]
    wf = run_backtest(wf_bars, stitched.loc[wf_start:])
    return {
        "oos_return": oos.metrics["total_return"],
        "oos_max_drawdown": oos.metrics["max_drawdown"],
        "oos_sharpe": oos.metrics["sharpe"],
        "oos_trades": oos.metrics["n_trades"],
        "oos_exposure": oos.metrics["exposure"],
        "oos_start": oos_bars.index[0],
        "oos_end": oos_bars.index[-1],
        "wf_return": wf.metrics["total_return"],
        "wf_max_drawdown": wf.metrics["max_drawdown"],
        "wf_sharpe": wf.metrics["sharpe"],
        "wf_trades": wf.metrics["n_trades"],
        "wf_start": wf_bars.index[0],
        "wf_end": wf_bars.index[-1],
    }


def run_macro_study(
    daily: dict[str, pd.DataFrame],
    intra: dict[str, pd.DataFrame],
    macros: dict[str, pd.Series],
    train_bars: int | None = None,
    test_bars: int | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    prices = {"1d": daily, "4h": intra}
    cache: dict[tuple, tuple] = {}
    rows = []
    for spec in PREDECLARED_VARIANTS:
        if verbose:
            print(f"  {spec['variant']}", flush=True)
        for asset, bars in prices[spec["timeframe"]].items():
            key = (
                asset,
                spec["indicator"],
                spec["timeframe"],
                json.dumps(spec["params"], sort_keys=True),
            )
            if key not in cache:
                base_signal = indicator_signal(spec, bars)
                base_stats = evaluate_signal(bars, base_signal, spec["timeframe"], train_bars, test_bars)
                bh_stats = evaluate_signal(
                    bars,
                    pd.Series(1.0, index=bars.index),
                    spec["timeframe"],
                    train_bars,
                    test_bars,
                )
                cache[key] = (base_signal, base_stats, bh_stats)
            base_signal, base_stats, bh_stats = cache[key]
            allow = rule_allow(spec["rule"], bars.index, macros)
            gated = apply_gate(base_signal, allow)
            stats = evaluate_signal(bars, gated, spec["timeframe"], train_bars, test_bars)
            rows.append(
                {
                    "variant": spec["variant"],
                    "asset": asset,
                    "timeframe": spec["timeframe"],
                    "factor": spec["factor"],
                    "rule": spec["rule"],
                    "rule_th": spec["rule_th"],
                    "indicator": spec["indicator"],
                    "label_th": spec["label_th"],
                    "params": json.dumps(spec["params"], sort_keys=True),
                    "filter_on": float(pd.Series(allow).reindex(bars.index).fillna(False).astype(bool).mean()),
                    "oos_return": stats["oos_return"],
                    "oos_max_drawdown": stats["oos_max_drawdown"],
                    "oos_trades": stats["oos_trades"],
                    "oos_exposure": stats["oos_exposure"],
                    "oos_start": pd.Timestamp(stats["oos_start"]).isoformat(),
                    "oos_end": pd.Timestamp(stats["oos_end"]).isoformat(),
                    "base_oos_return": base_stats["oos_return"],
                    "base_oos_max_drawdown": base_stats["oos_max_drawdown"],
                    "bh_oos_return": bh_stats["oos_return"],
                    "bh_oos_max_drawdown": bh_stats["oos_max_drawdown"],
                    "wf_return": stats["wf_return"],
                    "wf_max_drawdown": stats["wf_max_drawdown"],
                    "wf_trades": stats["wf_trades"],
                    "wf_start": pd.Timestamp(stats["wf_start"]).isoformat(),
                    "wf_end": pd.Timestamp(stats["wf_end"]).isoformat(),
                    "base_wf_return": base_stats["wf_return"],
                    "base_wf_max_drawdown": base_stats["wf_max_drawdown"],
                    "bh_wf_return": bh_stats["wf_return"],
                    "bh_wf_max_drawdown": bh_stats["wf_max_drawdown"],
                    "oos_beat_bh": _beats(stats["oos_return"], bh_stats["oos_return"]),
                    "wf_beat_bh": _beats(stats["wf_return"], bh_stats["wf_return"]),
                    "oos_beat_base": _beats(stats["oos_return"], base_stats["oos_return"]),
                    "wf_beat_base": _beats(stats["wf_return"], base_stats["wf_return"]),
                }
            )
    return pd.DataFrame(rows)


def keep_and_improve(frame: pd.DataFrame) -> pd.DataFrame:
    """Accept a variant only when both coins beat buy-and-hold on both checks.

    `improved` also requires beating the ungated indicator on both checks.
    For the macro-only rows the ungated indicator is buy-and-hold, so the two
    flags match.
    """
    rows = []
    for variant, group in frame.groupby("variant", sort=False):
        coins = set(group["asset"])
        accepted = coins == {"BTC", "ETH"} and bool(group["oos_beat_bh"].all() and group["wf_beat_bh"].all())
        beat_base = coins == {"BTC", "ETH"} and bool(group["oos_beat_base"].all() and group["wf_beat_base"].all())
        rows.append(
            {
                "variant": variant,
                "accepted": accepted,
                "beat_base_both": beat_base,
                "improved": accepted and beat_base,
            }
        )
    return pd.DataFrame(rows)


def _pct(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.1f}%"


def _yn(flag) -> str:
    return "ใช่" if bool(flag) else "ไม่"


def render_detail_table(frame: pd.DataFrame) -> str:
    lines = [
        "| เหรียญ | กรอบ | กติกาเดิม | ตัวกรอง | OOS กรอง | OOS กติกาเดิม | OOS ซื้อถือ | WF กรอง | WF กติกาเดิม | WF ซื้อถือ | MDD OOS | MDD WF | ชนะซื้อถือทั้งสองช่อง | ชนะกติกาเดิมทั้งสองช่อง |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    ordered = frame.sort_values(["factor", "rule", "timeframe", "indicator", "asset"])
    for row in ordered.itertuples(index=False):
        lines.append(
            "| {asset} | {clock} | {label} | {rule} | {oos} | {base} | {bh} | {wf} | {base_wf} | {bh_wf} | {dd} | {wfdd} | {keep} | {better} |".format(
                asset=row.asset,
                clock=row.timeframe,
                label=row.label_th,
                rule=row.rule_th,
                oos=_pct(row.oos_return),
                base=_pct(row.base_oos_return),
                bh=_pct(row.bh_oos_return),
                wf=_pct(row.wf_return),
                base_wf=_pct(row.base_wf_return),
                bh_wf=_pct(row.bh_wf_return),
                dd=_pct(row.oos_max_drawdown),
                wfdd=_pct(row.wf_max_drawdown),
                keep=_yn(row.oos_beat_bh and row.wf_beat_bh),
                better=_yn(row.oos_beat_base and row.wf_beat_base),
            )
        )
    return "\n".join(lines)


def render_verdict_table(frame: pd.DataFrame, verdict: pd.DataFrame) -> str:
    merged = frame.drop_duplicates("variant").merge(verdict, on="variant", how="left")
    lines = [
        "| ปัจจัย | ตัวกรอง | กติกาเดิม | กรอบ | ผ่านเกณฑ์เก็บ (ชนะซื้อถือทั้ง OOS และ walk-forward ทั้งสองเหรียญ) | ผ่านเกณฑ์เก็บและดีกว่ากติกาเดิม |",
        "|---|---|---|---|---|---|",
    ]
    ordered = merged.sort_values(["factor", "rule", "timeframe", "indicator"])
    for row in ordered.itertuples(index=False):
        lines.append(
            f"| {row.factor} | {row.rule_th} | {row.label_th} | {row.timeframe} | {_yn(row.accepted)} | {_yn(row.improved)} |"
        )
    return "\n".join(lines)
