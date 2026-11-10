"""Round three: partial positions, luck checks, and stock entry timing.

Writes three plain-Thai reports under results/. It does not touch the paper
book, the dashboard, or the tables inside JOURNAL.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from crypto_lab.assumptions import PAPER_START, PERIODS_PER_YEAR
from crypto_lab.engine import run_backtest
from crypto_lab.overfit import annualise, deflated_sharpe, pbo_cscv, per_bar_sharpes, rolling_starts
from crypto_lab.research import split_point
from crypto_lab.stocks import (
    BARS_PER_MONTH,
    STOCK_PERIODS_PER_YEAR,
    STOCKS,
    filter_vs_hold,
    forward_by_state,
    lump_vs_dca,
    status_today,
    wait_for_dip,
)
from crypto_lab.strategies import STRATEGIES, sma_filter_signal
from crypto_lab.weights import REBALANCE_BAND, TARGET_VOL, VOL_LOOKBACK, run_weight_backtest, trend_score, trend_vol_weight

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

VOL_TARGETS = (0.20, 0.30, 0.40, 0.50)
HORIZON_YEARS = (1, 2, 4)


def _pct(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.{digits}f}%"


def _num(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.2f}"


def _money(value) -> str:
    return f"{value:,.0f}"


# ---------------------------------------------------------------- sizing


def sizing_variants(bars: pd.DataFrame) -> dict[str, pd.Series]:
    """Target weights for every variant, on the full history (all causal)."""
    variants = {
        "ซื้อแล้วถือ": pd.Series(1.0, index=bars.index),
        "เส้น 200 วัน เข้าเต็มออกหมด": sma_filter_signal(bars),
        "คะแนนเทรนด์ 5 กติกา ไม่ปรับตามความแกว่ง": trend_score(bars),
    }
    for target in VOL_TARGETS:
        variants[f"คะแนนเทรนด์ + เป้าความแกว่ง {target * 100:.0f}%"] = trend_vol_weight(bars, target_vol=target)
    return variants


MAIN_VARIANT = f"คะแนนเทรนด์ + เป้าความแกว่ง {TARGET_VOL * 100:.0f}%"


def _run_variant(name: str, window: pd.DataFrame, weight: pd.Series):
    """Binary rules go through the original engine so they match round one."""
    if name in ("ซื้อแล้วถือ", "เส้น 200 วัน เข้าเต็มออกหมด"):
        result = run_backtest(window, weight)
        return result.equity, result.metrics
    result = run_weight_backtest(window, weight)
    return result.equity, result.metrics


def run_sizing(assets: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows = []
    start_rows = []
    returns = {}
    for asset, bars in assets.items():
        variants = sizing_variants(bars)
        first = trend_score(bars).first_valid_index()
        first_row = bars.index.get_loc(first)
        cut = split_point(len(bars))
        paper_row = int(bars.index.searchsorted(pd.Timestamp(PAPER_START)))
        windows = {
            "ทั้งช่วง": (first_row, len(bars)),
            "30% ท้าย": (cut, len(bars)),
            f"ตั้งแต่ {PAPER_START}": (paper_row, len(bars)),
        }
        for label, (start, end) in windows.items():
            window = bars.iloc[start:end]
            for name, weight in variants.items():
                equity, metrics = _run_variant(name, window, weight.iloc[start:end])
                cagr, drawdown = metrics["cagr"], metrics["max_drawdown"]
                rows.append(
                    {
                        "asset": asset,
                        "window": label,
                        "start": window.index[0].date().isoformat(),
                        "variant": name,
                        "end_value": metrics["end_value"],
                        "total_return": metrics["total_return"],
                        "cagr": cagr,
                        "max_drawdown": drawdown,
                        "sharpe": metrics["sharpe"],
                        "return_per_drawdown": cagr / abs(drawdown) if drawdown else float("nan"),
                        "exposure": metrics["exposure"],
                        "n_trades": metrics["n_trades"],
                    }
                )
                if label == "ทั้งช่วง":
                    returns[(asset, name)] = equity.pct_change().dropna()
        hold = returns[(asset, "ซื้อแล้วถือ")]
        for name in ("เส้น 200 วัน เข้าเต็มออกหมด", MAIN_VARIANT):
            for years in HORIZON_YEARS:
                stats = rolling_starts(returns[(asset, name)], hold, horizon_bars=years * PERIODS_PER_YEAR)
                start_rows.append({"asset": asset, "variant": name, "years": years, **stats})
    return pd.DataFrame(rows), pd.DataFrame(start_rows), returns


def render_sizing(table: pd.DataFrame, starts: pd.DataFrame) -> str:
    lines = [
        "# ถือบางส่วน และลดขนาดเมื่อราคาแกว่งแรง",
        "",
        "สร้างโดย `python scripts/run_phase3.py` เงินเริ่ม 10,000 ดอลลาร์สมมติ ค่าธรรมเนียม 0.10% และ slippage 0.05% เหมือนรอบแรก ไม่มีการซื้อขายจริง",
        "",
        "## กติกา",
        "",
        "- **คะแนนเทรนด์** คือสัดส่วนของ 5 กติกาที่บอกให้ถือ: ราคาปิดเหนือเส้น 50, 100, 200 วัน และช่องดอนเชียน 20/10 กับ 55/20 ได้ค่า 0%, 20%, ... ถึง 100%",
        f"- **เป้าความแกว่ง** คือถ้าราคาแกว่งแรงกว่าเป้า ให้ถือน้อยลงตามสัดส่วน วัดจากความแกว่ง {VOL_LOOKBACK} วันล่าสุด คิดเป็นต่อปี ถือได้ไม่เกิน 100% ไม่มีการกู้",
        f"- ปรับสัดส่วนเฉพาะเมื่อของที่ถืออยู่ห่างจากเป้าอย่างน้อย {REBALANCE_BAND * 100:.0f}% ของพอร์ต จะได้ไม่เสียค่าธรรมเนียมกับการขยับเล็ก ๆ",
        f"- ค่าที่ตั้งไว้ก่อนดูผลคือเป้า {TARGET_VOL * 100:.0f}% ตารางพิมพ์ค่าข้างเคียงไว้ด้วยเพื่อให้เห็นว่าผลไม่ได้ขึ้นกับตัวเลขเดียว ไม่ได้เลือกค่าที่ดีที่สุดมาใช้",
        "- สัญญาณใช้ราคาปิดวันนี้ ซื้อขายที่ราคาเปิดวันถัดไป เหมือนเครื่องหลัก",
        "",
        "\"กำไรต่อความเจ็บ\" คือผลตอบแทนทบต้นต่อปี หารด้วยขาดทุนสูงสุด ยิ่งสูงยิ่งคุ้มกับความเจ็บที่ต้องทน",
        "",
    ]
    for (asset, window), part in table.groupby(["asset", "window"], sort=False):
        lines += [
            f"## {asset} — {window} (เริ่ม {part['start'].iloc[0]})",
            "",
            "| วิธี | เงินปลายทาง | ผลตอบแทนรวม | ทบต้นต่อปี | ขาดทุนสูงสุด | Sharpe | กำไรต่อความเจ็บ | ถือเฉลี่ย | จำนวนครั้งที่ซื้อขาย |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in part.itertuples(index=False):
            lines.append(
                f"| {row.variant} | {_money(row.end_value)} | {_pct(row.total_return)} | {_pct(row.cagr)} | "
                f"{_pct(row.max_drawdown)} | {_num(row.sharpe)} | {_num(row.return_per_drawdown)} | "
                f"{_pct(row.exposure, 0)} | {int(row.n_trades)} |"
            )
        lines.append("")
    lines += [
        "## ถ้าเริ่มวันอื่น ผลยังเหมือนเดิมไหม",
        "",
        "เริ่มใหม่ทุก 30 วันตลอดประวัติ ถือตามจำนวนปีที่ระบุ แล้วนับว่ากี่ครั้งที่วิธีนั้นดีกว่าซื้อแล้วถือ",
        "",
        "| เหรียญ | วิธี | ถือกี่ปี | จำนวนวันเริ่ม | กำไรมากกว่าซื้อแล้วถือ | ขาดทุนสูงสุดน้อยกว่า | ส่วนต่างเงินปลายทาง (ค่ากลาง) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in starts.itertuples(index=False):
        lines.append(
            f"| {row.asset} | {row.variant} | {row.years} | {row.n_starts} | {_pct(row.win_return, 0)} | "
            f"{_pct(row.win_drawdown, 0)} | {_pct(row.median_gap)} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------- overfit


def trial_matrix(bars: pd.DataFrame) -> pd.DataFrame:
    """Per-bar returns of every signal setting the lab has in its grids."""
    columns = {}
    for strategy in STRATEGIES:
        if strategy.kind != "signal":
            continue
        for params in strategy.grid:
            label = strategy.id + ":" + ",".join(f"{key}={value}" for key, value in sorted(params.items()))
            equity = run_backtest(bars, strategy.generate(bars, **params)).equity
            columns[label] = equity.pct_change()
    matrix = pd.DataFrame(columns)
    # Skip the stretch where the slowest rule is still warming up.
    return matrix.iloc[260:].dropna(how="any")


def run_overfit(assets: dict[str, pd.DataFrame], sizing_returns: dict) -> pd.DataFrame:
    rows = []
    for asset, bars in assets.items():
        matrix = trial_matrix(bars)
        sharpes = per_bar_sharpes(matrix)
        spread = float(sharpes.std(ddof=1))
        # The sizing variants were also looked at, so they count as tries.
        trials = matrix.shape[1] + 1 + len(VOL_TARGETS)
        pbo = pbo_cscv(matrix)
        best = sharpes.idxmax()
        checks = {
            f"ค่าที่ Sharpe สูงสุดในกริด ({best})": matrix[best],
            "เส้น 200 วัน ค่าตามตำรา": matrix["sma_filter:window=200"],
            MAIN_VARIANT: sizing_returns[(asset, MAIN_VARIANT)].reindex(matrix.index).dropna(),
            "ซื้อแล้วถือ": sizing_returns[(asset, "ซื้อแล้วถือ")].reindex(matrix.index).dropna(),
        }
        for name, series in checks.items():
            stats = deflated_sharpe(series, n_trials=trials, sharpe_std=spread)
            rows.append(
                {
                    "asset": asset,
                    "what": name,
                    "n_trials": trials,
                    "sharpe_year": annualise(stats["sharpe"]),
                    "luck_hurdle_year": annualise(stats["hurdle"]),
                    "dsr": stats["dsr"],
                    "pbo": pbo["pbo"],
                    "median_rank": pbo["median_rank"],
                    "n_splits": pbo["n_splits"],
                    "start": matrix.index[0].date().isoformat(),
                }
            )
    return pd.DataFrame(rows)


def render_overfit(table: pd.DataFrame) -> str:
    lines = [
        "# ผลดีเพราะฝีมือ หรือเพราะลองหลายแบบแล้วเลือกตัวที่สวย",
        "",
        "สร้างโดย `python scripts/run_phase3.py` ใช้ทุกค่าพารามิเตอร์ในกริดของกลยุทธ์แบบสัญญาณ 6 ตัว บนกรอบรายวัน",
        "",
        "## อ่านยังไง",
        "",
        "- **เส้นโชค** คือ Sharpe ที่คาดว่าจะเห็นจากตัวที่ดีที่สุด ถ้าลองกติกาที่ไม่มีประโยชน์เลยจำนวนเท่านี้ ยิ่งลองมาก เส้นนี้ยิ่งสูง",
        "- **DSR** (Deflated Sharpe Ratio ของ Bailey กับ López de Prado, 2014) คือโอกาสที่ Sharpe จริงสูงกว่าเส้นโชค เกณฑ์ที่ใช้กันคือ 95% ขึ้นไป ต่ำกว่านั้นยังแยกจากโชคไม่ได้",
        "- **PBO** (Probability of Backtest Overfitting ของ Bailey, Borwein, López de Prado, Zhu, 2015) แบ่งประวัติเป็น 16 ท่อน เลือกตัวที่ดีที่สุดจาก 8 ท่อน แล้วดูว่าอีก 8 ท่อนที่เหลือมันอยู่อันดับไหน ทำครบทุกวิธีแบ่ง PBO คือสัดส่วนครั้งที่ตัวชนะตกไปอยู่ครึ่งล่าง ยิ่งใกล้ 0% ยิ่งดี ตั้งแต่ 50% ขึ้นไปแปลว่าการเลือกตัวที่ดีที่สุดไม่ช่วยอะไรเลย",
        "- DSR ถามว่า Sharpe สูงกว่าศูนย์จริงไหม ไม่ได้ถามว่าชนะซื้อแล้วถือไหม คำถามหลังดูที่ตาราง \"ถ้าเริ่มวันอื่น\" ใน `results/trend_sizing.md`",
        "- PBO ต่ำบอกแค่ว่าอันดับในกริดค่อนข้างคงที่ เช่น กลยุทธ์ตามเทรนด์อยู่เหนือกลยุทธ์ซื้อถูกขายแพงเกือบทุกท่อน ไม่ได้บอกว่าตัวชนะจะทำกำไร",
        "",
    ]
    for asset, part in table.groupby("asset", sort=False):
        first = part.iloc[0]
        lines += [
            f"## {asset} (เริ่ม {first['start']})",
            "",
            f"- นับการลองทั้งหมด {int(first['n_trials'])} แบบ (กริดเดิมของห้องนี้ บวกวิธีถือบางส่วนอีก {1 + len(VOL_TARGETS)} แบบ) PBO คิดจากกริดเดิม",
            f"- PBO = {_pct(first['pbo'], 0)} จากการแบ่ง {int(first['n_splits']):,} วิธี",
            f"- ตัวที่ชนะในครึ่งที่ใช้เลือก ได้อันดับค่ากลางในครึ่งที่เหลือ = {_pct(first['median_rank'], 0)} (100% คือดีที่สุด 50% คือกลางตาราง)",
            "",
            "| สิ่งที่ตรวจ | Sharpe ต่อปี | เส้นโชค | DSR | ผ่านเกณฑ์ 95%? |",
            "|---|---:|---:|---:|---|",
        ]
        for row in part.itertuples(index=False):
            passed = "ผ่าน" if row.dsr >= 0.95 else "ไม่ผ่าน"
            lines.append(
                f"| {row.what} | {_num(row.sharpe_year)} | {_num(row.luck_hurdle_year)} | {_pct(row.dsr, 0)} | {passed} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- stocks


def run_stocks(stocks: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for symbol, bars in stocks.items():
        filtered = filter_vs_hold(bars)
        out[symbol] = {
            "bars": bars,
            "status": status_today(bars),
            "lump": lump_vs_dca(bars),
            "dip_10": wait_for_dip(bars, dip=0.10),
            "dip_20": wait_for_dip(bars, dip=0.20),
            "forward": forward_by_state(bars),
            "filter": filtered,
            "filter_starts": rolling_starts(
                filtered["rule_returns"],
                filtered["hold_returns"],
                horizon_bars=5 * STOCK_PERIODS_PER_YEAR,
                step_bars=BARS_PER_MONTH,
            ),
        }
    return out


def render_stocks(found: dict) -> str:
    lines = [
        "# จังหวะเข้าซื้อหุ้น",
        "",
        "สร้างโดย `python scripts/run_phase3.py` ราคาจาก Yahoo Finance ปรับเงินปันผลและการแตกหุ้นแล้ว ผลตอบแทนจึงรวมปันผล ค่าธรรมเนียมสมมติ 0.15% ต่อครั้งและ slippage 0.05% เงินที่รอซื้อได้ดอกเบี้ย 0%",
        "",
        "ใช้กองทุนดัชนีแทนหุ้นรายตัว เพราะหุ้นตัวเดียวล้มละลายได้ ผลของดัชนีจึงเอาไปใช้กับหุ้นรายตัวตรง ๆ ไม่ได้ นี่คือผลจากราคาในอดีต ไม่ใช่คำแนะนำให้ซื้อหรือขาย",
        "",
        "## วันนี้ราคาอยู่ตรงไหน",
        "",
        "| กองทุน | คืออะไร | ข้อมูลถึงวันที่ | ราคาปิด | เทียบเส้น 200 วัน | ต่ำกว่าจุดสูงสุดเดิม |",
        "|---|---|---|---:|---:|---:|",
    ]
    for symbol, data in found.items():
        status = data["status"]
        side = "เหนือ" if status["above_sma200"] else "ใต้"
        lines.append(
            f"| {symbol} | {STOCKS[symbol]} | {status['date']} | {status['price']:,.2f} | "
            f"{side}เส้น {_pct(abs(status['vs_sma200']))} | {_pct(status['drawdown'])} |"
        )
    lines += [
        "",
        "## 1. มีเงินก้อน ซื้อทีเดียวหรือทยอยซื้อ 12 เดือน",
        "",
        "เริ่มใหม่ทุกเดือนตลอดประวัติ เทียบซื้อทั้งก้อนวันแรก กับแบ่งซื้อ 12 งวดเท่ากันเดือนละครั้ง วัดผลตอนซื้องวดสุดท้ายครบ หลังจากนั้นทั้งสองฝั่งถือกองทุนเดียวกัน ส่วนต่างเป็นเปอร์เซ็นต์จึงไม่เปลี่ยนอีก",
        "",
        "| กองทุน | จำนวนเดือนที่เริ่ม | ซื้อทีเดียวชนะ | ส่วนต่างค่ากลาง | ตอนซื้อทีเดียวพลาดหนัก (10% ที่แย่สุด) | ตอนซื้อทีเดียวได้เปรียบมาก (10% ที่ดีสุด) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for symbol, data in found.items():
        stats = data["lump"]
        lines.append(
            f"| {symbol} | {stats['n_starts']} | {_pct(stats['lump_wins'], 0)} | "
            f"{_pct(stats['median_gap'])} | {_pct(stats['worst_decile_gap'])} | {_pct(stats['best_decile_gap'])} |"
        )
    lines += [
        "",
        "ส่วนต่างเป็นบวกแปลว่าซื้อทีเดียวได้เงินปลายทางมากกว่า เงินที่รอซื้อในการทดลองนี้ได้ดอกเบี้ย 0% ถ้าฝากได้ดอกเบี้ย การทยอยซื้อจะดีขึ้นเล็กน้อย",
        "",
        "## 2. รอให้ราคาย่อก่อนค่อยซื้อ ดีกว่าซื้อเลยไหม",
        "",
        "ถือเงินสดรอจนราคาปิดต่ำกว่าจุดสูงสุดเดิมตามที่กำหนด แล้วซื้อทั้งก้อนและถือ เทียบกับซื้อเลยวันแรก วัดผลหลัง 5 ปี นับเฉพาะเดือนที่ราคายังไม่ย่อถึงเกณฑ์ เพราะถ้าย่อถึงแล้วทั้งสองฝั่งซื้อวันเดียวกัน",
        "",
        "| กองทุน | รอให้ย่อ | จำนวนเดือนที่ต้องรอจริง | เดือนที่ย่อถึงเกณฑ์อยู่แล้ว | การรอชนะ | ส่วนต่างค่ากลาง | รอจนครบ 5 ปีแล้วยังไม่ได้ซื้อ |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for symbol, data in found.items():
        for label, key in (("10%", "dip_10"), ("20%", "dip_20")):
            stats = data[key]
            lines.append(
                f"| {symbol} | {label} | {stats['n_starts']} | {stats['already_down']} | {_pct(stats['waiting_wins'], 0)} | "
                f"{_pct(stats['median_gap'])} | {_pct(stats['never_bought'], 0)} |"
            )
    lines += [
        "",
        "ส่วนต่างเป็นลบแปลว่าการรอได้เงินปลายทางน้อยกว่าซื้อเลย",
        "",
        "## 3. ถือเฉพาะตอนราคาเหนือเส้น 200 วัน",
        "",
        "ทั้งสองวิธีเริ่มวันเดียวกัน คือวันแรกที่เส้น 200 วันคำนวณได้ วันเริ่มมีผลกับตัวเลขมาก เช่น TDEX.BK เริ่มนับใกล้จุดต่ำสุดของปี 2008 ให้ดูตารางเริ่มทุกเดือนด้านล่างประกอบ",
        "",
        "| กองทุน | เริ่ม | วิธี | ผลตอบแทนรวม | ทบต้นต่อปี | ขาดทุนสูงสุด | Sharpe | จำนวนเทรด | สัดส่วนวันที่ถือ |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol, data in found.items():
        for label, key in (("เส้น 200 วัน", "rule"), ("ซื้อแล้วถือ", "hold")):
            metrics = data["filter"][key]
            lines.append(
                f"| {symbol} | {data['filter']['start']} | {label} | {_pct(metrics['total_return'], 0)} | {_pct(metrics['cagr'])} | "
                f"{_pct(metrics['max_drawdown'])} | {_num(metrics['sharpe'])} | {int(metrics['n_trades'])} | "
                f"{_pct(metrics['exposure'], 0)} |"
            )
    lines += [
        "",
        "เริ่มใหม่ทุกเดือน ถือ 5 ปี เส้น 200 วันดีกว่าซื้อแล้วถือกี่ครั้ง",
        "",
        "| กองทุน | จำนวนเดือนที่เริ่ม | กำไรมากกว่า | ขาดทุนสูงสุดน้อยกว่า | ส่วนต่างเงินปลายทาง (ค่ากลาง) |",
        "|---|---:|---:|---:|---:|",
    ]
    for symbol, data in found.items():
        stats = data["filter_starts"]
        lines.append(
            f"| {symbol} | {stats['n_starts']} | {_pct(stats['win_return'], 0)} | "
            f"{_pct(stats['win_drawdown'], 0)} | {_pct(stats['median_gap'])} |"
        )
    lines += [
        "",
        "## 4. หลังวันที่ราคาอยู่ในสภาพแบบนี้ อีก 1 ปีต่อมาเป็นยังไง",
        "",
        "นับทุกวันในอดีต แบ่งตามสภาพราคาของวันนั้น แล้วดูผลตอบแทนใน 1 ปีถัดไป วันที่ติดกันใช้ปีถัดไปเกือบชุดเดียวกัน จำนวนตัวอย่างที่เป็นอิสระต่อกันจริงจึงน้อยกว่าจำนวนวันมาก แถวที่มีเครื่องหมาย ◀ คือสภาพของวันล่าสุด",
        "",
    ]
    for symbol, data in found.items():
        status = data["status"]
        current = {status["bucket"], "ราคาเหนือเส้น 200 วัน" if status["above_sma200"] else "ราคาใต้เส้น 200 วัน"}
        lines += [
            f"### {symbol}",
            "",
            "| สภาพราคาของวันนั้น | จำนวนวัน | ผลตอบแทนเฉลี่ย 1 ปีถัดไป | ค่ากลาง | สัดส่วนที่ได้กำไร | กรณีแย่ที่สุด |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in data["forward"].itertuples(index=False):
            mark = " ◀" if row.state in current else ""
            lines.append(
                f"| {row.state}{mark} | {row.days:,} | {_pct(row.mean)} | {_pct(row.median)} | "
                f"{_pct(row.positive, 0)} | {_pct(row.worst)} |"
            )
        lines.append("")
    return "\n".join(lines)


def run_phase3(crypto: dict[str, pd.DataFrame], stocks: dict[str, pd.DataFrame]) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    sizing, starts, returns = run_sizing(crypto)
    sizing.to_csv(RESULTS / "trend_sizing.csv", index=False)
    starts.to_csv(RESULTS / "trend_sizing_starts.csv", index=False)
    (RESULTS / "trend_sizing.md").write_text(render_sizing(sizing, starts), encoding="utf-8")

    overfit = run_overfit(crypto, returns)
    overfit.to_csv(RESULTS / "overfit.csv", index=False)
    (RESULTS / "overfit.md").write_text(render_overfit(overfit), encoding="utf-8")

    found = run_stocks(stocks) if stocks else {}
    if found:
        (RESULTS / "stocks.md").write_text(render_stocks(found), encoding="utf-8")
    return {"sizing": sizing, "starts": starts, "overfit": overfit, "stocks": found}
