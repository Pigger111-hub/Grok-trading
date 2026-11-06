"""Run every textbook strategy, the in-sample / out-of-sample split, and walk-forward."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from crypto_lab.assumptions import BARS_PER_DAY, FEE_RATE, IN_SAMPLE_FRACTION, SLIPPAGE_RATE, WALK_FORWARD_TEST_DAYS, WALK_FORWARD_TRAIN_DAYS
from crypto_lab.data import CACHE_DIR, load_cached
from crypto_lab.engine import run_backtest
from crypto_lab.plots import plot_comparison, plot_overview
from crypto_lab.strategies import STRATEGIES
from crypto_lab.walkforward import choose_params, walk_forward

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
CHARTS = RESULTS / "charts"
JOURNAL = ROOT / "JOURNAL.md"

EXPERIMENT_TH = {
    "full_default": "ทั้งช่วง ด้วยค่ามาตรฐานจากตำรา",
    "is_default": "ในตัวอย่าง 70% แรก ด้วยค่ามาตรฐาน",
    "oos_default": "นอกตัวอย่าง 30% ท้าย ด้วยค่ามาตรฐาน",
    "is_tuned": "ในตัวอย่าง ที่เลือกพารามิเตอร์จากข้อมูลชุดเดียวกัน (ตัวเลขนี้มองคำตอบแล้ว ห้ามถือเป็นผลจริง)",
    "oos_tuned": "นอกตัวอย่าง ด้วยพารามิเตอร์ที่เลือกจาก 70% แรกเท่านั้น",
    "walk_forward": "walk-forward เลือกจาก 2 ปีที่ผ่านมา แล้วทดสอบปีถัดไป ต่อกันทั้งเส้น",
    "cost_fee_0": "ทั้งช่วง ค่าธรรมเนียม 0% (ยังมี slippage 0.05%)",
    "cost_fee_0.50pct": "ทั้งช่วง ค่าธรรมเนียม 0.50% บวก slippage 0.05%",
}

SELECTION = {
    "full_default": "published_defaults",
    "is_default": "published_defaults",
    "oos_default": "published_defaults",
    "is_tuned": "tuned_on_this_same_sample",
    "oos_tuned": "tuned_on_earlier_data_only",
    "walk_forward": "tuned_on_earlier_data_only",
    "cost_fee_0": "published_defaults",
    "cost_fee_0.50pct": "published_defaults",
}


def split_point(n_rows: int, fraction: float = IN_SAMPLE_FRACTION) -> int:
    cut = int(n_rows * fraction)
    return min(max(cut, 1), n_rows - 1)


def backtest_window(bars, strategy, params, start: int, end: int, fee_rate: float = FEE_RATE, step_bars: int | None = None):
    """Test bars[start:end]. Signal strategies may read prices before `start`."""
    from crypto_lab.engine import run_dca

    window = bars.iloc[start:end]
    if strategy.kind == "dca":
        strategy_result = run_dca(
            window,
            weeks=int(params["weeks"]),
            step_days=step_bars,
            fee_rate=fee_rate,
            slippage_rate=SLIPPAGE_RATE,
        )
    else:
        signal = strategy.generate(bars.iloc[:end], **params).iloc[start:end]
        strategy_result = run_backtest(
            window,
            signal,
            fee_rate=fee_rate,
            slippage_rate=SLIPPAGE_RATE,
        )
    benchmark = run_backtest(
        window,
        pd.Series(1.0, index=window.index),
        fee_rate=fee_rate,
        slippage_rate=SLIPPAGE_RATE,
    )
    return strategy_result, benchmark


def _beats(left, right) -> bool:
    if left is None or right is None:
        return False
    if pd.isna(left) or pd.isna(right):
        return False
    return float(left) > float(right)


def _row(asset, strategy, experiment, params, strategy_result, benchmark, timeframe: str = "1d") -> dict:
    sm = strategy_result.metrics
    bm = benchmark.metrics
    return {
        "asset": asset,
        "timeframe": timeframe,
        "strategy": strategy.id,
        "strategy_th": strategy.name_th,
        "experiment": experiment,
        "experiment_th": EXPERIMENT_TH[experiment],
        "selection": SELECTION[experiment],
        "start": strategy_result.equity.index[0].date().isoformat(),
        "end": strategy_result.equity.index[-1].date().isoformat(),
        "total_return": sm["total_return"],
        "cagr": sm["cagr"],
        "max_drawdown": sm["max_drawdown"],
        "sharpe": sm["sharpe"],
        "win_rate": sm["win_rate"],
        "n_trades": sm["n_trades"],
        "exposure": sm["exposure"],
        "end_value": sm["end_value"],
        "bh_total_return": bm["total_return"],
        "bh_cagr": bm["cagr"],
        "bh_max_drawdown": bm["max_drawdown"],
        "bh_sharpe": bm["sharpe"],
        "bh_end_value": bm["end_value"],
        "beat_bh_return": _beats(sm["total_return"], bm["total_return"]),
        "beat_bh_sharpe": _beats(sm["sharpe"], bm["sharpe"]),
        "beat_bh_drawdown": _beats(sm["max_drawdown"], bm["max_drawdown"]),
        "params": json.dumps(params, sort_keys=True, ensure_ascii=False),
    }


def _pct(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.1f}%"


def _num(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.2f}"


def _markdown_table(frame: pd.DataFrame) -> str:
    show = frame[
        frame["experiment"].isin(
            ["full_default", "is_default", "oos_default", "is_tuned", "oos_tuned", "walk_forward"]
        )
    ]
    lines = [
        "| เหรียญ | กรอบ | กลยุทธ์ | การทดลอง | ผลตอบแทนรวม | ทบต้นต่อปี | ขาดทุนสูงสุด | Sharpe | อัตราชนะ | จำนวนเทรด | สัดส่วนวันที่ถือ | ซื้อแล้วถือ | Sharpe ซื้อแล้วถือ | กำไรสูงกว่าซื้อแล้วถือ? | Sharpe สูงกว่าซื้อแล้วถือ? |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in show.itertuples(index=False):
        lines.append(
            "| {asset} | {clock} | {name} | {exp} | {ret} | {cagr} | {dd} | {sh} | {win} | {trades} | {expo} | {bh} | {bhs} | {br} | {bs} |".format(
                asset=row.asset,
                clock=getattr(row, "timeframe", "1d"),
                name=row.strategy_th,
                exp=row.experiment_th,
                ret=_pct(row.total_return),
                cagr=_pct(row.cagr),
                dd=_pct(row.max_drawdown),
                sh=_num(row.sharpe),
                win=_pct(row.win_rate),
                trades=int(row.n_trades),
                expo=_pct(row.exposure),
                bh=_pct(row.bh_total_return),
                bhs=_num(row.bh_sharpe),
                br="ใช่" if row.beat_bh_return else "ไม่",
                bs="ใช่" if row.beat_bh_sharpe else "ไม่",
            )
        )
    return "\n".join(lines)


def _cost_table(frame: pd.DataFrame) -> str:
    show = frame[frame["experiment"].isin(["cost_fee_0", "full_default", "cost_fee_0.50pct"])]
    lines = [
        "| เหรียญ | กลยุทธ์ | ค่าธรรมเนียม | ผลตอบแทนรวม | Sharpe | ขาดทุนสูงสุด | ซื้อแล้วถือ |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    order = {"cost_fee_0": "0%", "full_default": "0.10% (ค่าที่ใช้ในรายงาน)", "cost_fee_0.50pct": "0.50%"}
    for row in show.itertuples(index=False):
        lines.append(
            f"| {row.asset} | {row.strategy_th} | {order[row.experiment]} | {_pct(row.total_return)} | {_num(row.sharpe)} | {_pct(row.max_drawdown)} | {_pct(row.bh_total_return)} |"
        )
    return "\n".join(lines)


def upsert_journal_results(table: str, cost_table: str, journal_path: Path = JOURNAL) -> None:
    if not journal_path.exists():
        return
    text = journal_path.read_text(encoding="utf-8")
    block = f"<!-- RESULTS_START -->\n{table}\n<!-- RESULTS_END -->"
    cost = f"<!-- COSTS_START -->\n{cost_table}\n<!-- COSTS_END -->"
    if "<!-- RESULTS_START -->" in text:
        text = re.sub(r"<!-- RESULTS_START -->.*?<!-- RESULTS_END -->", block, text, flags=re.S)
    if "<!-- COSTS_START -->" in text:
        text = re.sub(r"<!-- COSTS_START -->.*?<!-- COSTS_END -->", cost, text, flags=re.S)
    journal_path.write_text(text, encoding="utf-8")


def run_research(
    assets: dict[str, pd.DataFrame] | None = None,
    timeframe: str = "1d",
    write_summary: bool = True,
) -> pd.DataFrame:
    if assets is None:
        assets = load_cached(CACHE_DIR)
    RESULTS.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)
    rows = []
    fold_rows = []

    bar_scale = BARS_PER_DAY[timeframe]
    step_bars = 7 * bar_scale
    for asset, bars in assets.items():
        print(
            f"\n=== {asset} {timeframe}: {bars.index.min()} ถึง {bars.index.max()} ({len(bars)} แท่ง) ==="
        )
        cut = split_point(len(bars))
        overview = {}
        overview_bh = None
        wf_overview = {}
        wf_bh = None
        for strategy in STRATEGIES:
            print(f"  {strategy.id} ...")
            runs = {
                "full_default": (0, len(bars), strategy.default_params, FEE_RATE),
                "is_default": (0, cut, strategy.default_params, FEE_RATE),
                "oos_default": (cut, len(bars), strategy.default_params, FEE_RATE),
                "cost_fee_0": (0, len(bars), strategy.default_params, 0.0),
                "cost_fee_0.50pct": (0, len(bars), strategy.default_params, 0.005),
            }
            stored = {}
            for experiment, (start, end, params, fee) in runs.items():
                strategy_result, benchmark = backtest_window(
                    bars, strategy, params, start, end, fee_rate=fee, step_bars=step_bars
                )
                stored[experiment] = (strategy_result, benchmark, params)
                rows.append(_row(asset, strategy, experiment, params, strategy_result, benchmark, timeframe))

            tuned, _score = choose_params(bars.iloc[:cut], strategy, train_days=cut)
            for experiment, start, end in (
                ("is_tuned", 0, cut),
                ("oos_tuned", cut, len(bars)),
            ):
                strategy_result, benchmark = backtest_window(
                    bars, strategy, tuned, start, end, step_bars=step_bars
                )
                stored[experiment] = (strategy_result, benchmark, tuned)
                rows.append(_row(asset, strategy, experiment, tuned, strategy_result, benchmark, timeframe))

            wf = walk_forward(
                bars,
                strategy,
                train_days=WALK_FORWARD_TRAIN_DAYS * bar_scale,
                test_days=WALK_FORWARD_TEST_DAYS * bar_scale,
            )
            rows.append(
                _row(
                    asset,
                    strategy,
                    "walk_forward",
                    {"note": "พารามิเตอร์เปลี่ยนทุกช่วง ดู results/folds.csv"},
                    wf.result,
                    wf.benchmark,
                    timeframe,
                )
            )
            for fold_number, fold in enumerate(wf.folds, start=1):
                fold_rows.append(
                    {
                        "asset": asset,
                        "timeframe": timeframe,
                        "strategy": strategy.id,
                        "fold": fold_number,
                        "test_start": pd.Timestamp(fold["test_start"]).date().isoformat(),
                        "test_end": pd.Timestamp(fold["test_end"]).date().isoformat(),
                        "train_sharpe": fold["train_sharpe"],
                        "params": json.dumps(fold["params"], sort_keys=True),
                    }
                )

            tag = "" if timeframe == "1d" else f"_{timeframe}"
            plot_comparison(
                stored["full_default"][0].equity,
                stored["full_default"][1].equity,
                CHARTS / f"{asset.lower()}_{strategy.id}{tag}_full.png",
                f"{asset} {timeframe} {strategy.name_en} vs buy-and-hold (full sample, textbook settings)",
            )
            plot_comparison(
                stored["oos_default"][0].equity,
                stored["oos_default"][1].equity,
                CHARTS / f"{asset.lower()}_{strategy.id}{tag}_oos.png",
                f"{asset} {timeframe} {strategy.name_en} vs buy-and-hold (last 30%, textbook settings)",
            )
            plot_comparison(
                wf.result.equity,
                wf.benchmark.equity,
                CHARTS / f"{asset.lower()}_{strategy.id}{tag}_walkforward.png",
                f"{asset} {timeframe} {strategy.name_en} walk-forward vs buy-and-hold",
            )
            overview[strategy.name_en] = stored["full_default"][0].equity
            overview_bh = stored["full_default"][1].equity
            wf_overview[strategy.name_en] = wf.result.equity
            wf_bh = wf.benchmark.equity

        tag = "" if timeframe == "1d" else f"_{timeframe}"
        plot_overview(
            overview,
            overview_bh,
            CHARTS / f"{asset.lower()}{tag}_overview_full.png",
            f"{asset} {timeframe} textbook strategies vs buy-and-hold (full sample, log scale)",
        )
        plot_overview(
            wf_overview,
            wf_bh,
            CHARTS / f"{asset.lower()}{tag}_overview_walkforward.png",
            f"{asset} {timeframe} walk-forward strategies vs buy-and-hold (log scale)",
        )

    frame = pd.DataFrame(rows)
    folds = pd.DataFrame(fold_rows)
    folds.to_csv(RESULTS / f"folds_{timeframe}.csv", index=False)
    if write_summary:
        persist_summary(frame, folds)
    return frame


def persist_summary(frame: pd.DataFrame, folds: pd.DataFrame | None = None) -> None:
    frame.to_csv(RESULTS / "summary.csv", index=False)
    if folds is not None:
        folds.to_csv(RESULTS / "folds.csv", index=False)
    table = _markdown_table(frame)
    costs = _cost_table(frame)
    (RESULTS / "summary.md").write_text(
        "# ตารางผลแบ็กเทสต์\n\n"
        "ตัวเลขนี้สร้างโดย `python scripts/run_backtests.py` "
        "เงินเริ่มต้น 10,000 ดอลลาร์ สมมติ ค่าธรรมเนียม 0.10% ต่อครั้งและ slippage 0.05% "
        "เว้นแต่แถวที่เขียนไว้เป็นอย่างอื่น ซื้อแล้วถือใช้ช่วงวันและต้นทุนชุดเดียวกัน\n\n"
        "คอลัมน์ \"กำไรสูงกว่าซื้อแล้วถือ?\" ดูผลตอบแทนรวมเท่านั้น "
        "คอลัมน์ Sharpe เป็นคนละคำถาม (กำไรเทียบกับความแกว่ง)\n\n"
        + table
        + "\n\n## ถ้าค่าธรรมเนียมเปลี่ยน\n\n"
        + costs
        + "\n",
        encoding="utf-8",
    )
    upsert_journal_results(table, costs)
    winners = frame[(frame["experiment"] == "oos_default") & (frame["beat_bh_return"])]
    print("\nกลยุทธ์ค่ามาตรฐานที่ผลตอบแทนรวมนอกตัวอย่างสูงกว่าซื้อแล้วถือ:")
    if winners.empty:
        print("  ไม่มี")
    else:
        for row in winners.itertuples(index=False):
            print(f"  {row.asset} {row.strategy}: {_pct(row.total_return)} เทียบกับ {_pct(row.bh_total_return)}")
    print(f"บันทึกตารางที่ {RESULTS / 'summary.md'}")
