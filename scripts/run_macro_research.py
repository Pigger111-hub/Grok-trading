#!/usr/bin/env python3
"""Score the pre-declared macro gates. Does not touch the paper book or dashboard.

Prices stay on the lab's public candles. ETH daily rows that are not Bitfinex
are dropped, then Bitfinex is asked for any newer closed days. Macro series
come from FRED's CSV when that host answers, otherwise from the Federal
Reserve release files named in crypto_lab/macro_data.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from crypto_lab.data import (  # noqa: E402
    fetch_bitfinex,
    fetch_bitfinex_daily,
    fetch_bitstamp,
    fetch_bitstamp_daily,
    load_4h,
    load_cached,
    prepare_intraday,
)
from crypto_lab.data import _prepare  # noqa: E402
from crypto_lab.macro_data import load_macro_series  # noqa: E402
from crypto_lab.macro_research import (  # noqa: E402
    PREDECLARED_VARIANTS,
    keep_and_improve,
    render_detail_table,
    render_verdict_table,
    run_macro_study,
)

RESULTS = ROOT / "results"


def _combine(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if fresh is None or fresh.empty:
        return existing
    if "date" in fresh.columns:
        fresh = fresh.set_index("date")
    combined = pd.concat([existing, fresh])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    return combined


def _extend(existing: pd.DataFrame, fetch, prepare) -> pd.DataFrame:
    last = pd.Timestamp(existing.index.max())
    try:
        raw = fetch(last)
        fresh = prepare(raw)
    except Exception as exc:  # noqa: BLE001 - a missed refresh must not fake prices
        print(f"  ต่อราคาไม่ได้ ใช้แคชต่อ: {exc}")
        return existing
    combined = _combine(existing, fresh)
    if combined.index.tz is not None:
        combined.index = combined.index.tz_convert(None)
    return combined


def _prepare_daily(raw: pd.DataFrame) -> pd.DataFrame:
    clean, _notes = _prepare(raw)
    return clean


def load_research_prices() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Lab candles, plus any newer closed bars. The shared cache is not rewritten."""
    daily = load_cached()
    intra = load_4h()
    eth = daily["ETH"]
    if "source" in eth.columns:
        bitfinex = eth["source"].astype(str).str.startswith("bitfinex")
        if int((~bitfinex).sum()):
            print(f"ตัด ETH รายวันที่ไม่ใช่ Bitfinex {int((~bitfinex).sum())} แท่ง")
            daily["ETH"] = eth.loc[bitfinex]

    print("ต่อแท่งที่ปิดแล้วหลังแคช ถ้าแหล่งเดิมตอบ ...")
    daily["BTC"] = _extend(
        daily["BTC"],
        lambda last: fetch_bitstamp_daily("btcusd", int(last.timestamp())),
        _prepare_daily,
    )
    daily["ETH"] = _extend(
        daily["ETH"],
        lambda last: fetch_bitfinex_daily("tETHUSD", int(last.timestamp() * 1000)),
        _prepare_daily,
    )
    intra["BTC"] = _extend(
        intra["BTC"],
        lambda last: fetch_bitstamp(
            "btcusd", int(last.timestamp()), step_seconds=14_400, align_midnight=False
        ),
        lambda raw: prepare_intraday(raw, bar_hours=4),
    )
    intra["ETH"] = _extend(
        intra["ETH"],
        lambda last: fetch_bitfinex(
            "tETHUSD",
            int(last.timestamp() * 1000),
            interval="4h",
            step_ms=14_400_000,
            align_midnight=False,
        ),
        lambda raw: prepare_intraday(raw, bar_hours=4),
    )
    return daily, intra


def _range_line(name: str, frame: pd.DataFrame) -> str:
    return (
        f"- {name}: {frame.index.min()} ถึง {frame.index.max()} จำนวน {len(frame)} แท่ง"
    )


def main() -> None:
    print(f"กติกาที่ประกาศไว้ล่วงหน้า {len(PREDECLARED_VARIANTS)} แบบ ไม่มีการไล่พารามิเตอร์")
    macros = load_macro_series(refresh=True)
    for series_id, series in macros.items():
        print(
            f"  {series_id}: {series.index.min().date()} → {series.index.max().date()} ({len(series)} จุด)"
        )
    daily, intra = load_research_prices()
    for asset, frame in daily.items():
        print(_range_line(f"{asset} 1d", frame))
    for asset, frame in intra.items():
        print(_range_line(f"{asset} 4h", frame))

    frame = run_macro_study(daily, intra, macros, verbose=True)
    verdict = keep_and_improve(frame)
    RESULTS.mkdir(parents=True, exist_ok=True)
    frame.to_csv(RESULTS / "macro_factors.csv", index=False)
    verdict.to_csv(RESULTS / "macro_verdicts.csv", index=False)
    accepted = int(verdict["accepted"].sum())
    improved = int(verdict["improved"].sum())
    header = "\n".join(
        [
            "# ตัวกรองแมโคร",
            "",
            f"ลอง {len(PREDECLARED_VARIANTS)} แบบที่ประกาศไว้ก่อนเห็นตัวเลข "
            "(6 กติกา × 8 ช่อง คือตัวกรองอย่างเดียว 2 กรอบเวลากับกติกาเดิม 6 แบบ)",
            f"ผ่านเกณฑ์เก็บ {accepted} แบบ ดีกว่ากติกาเดิมพร้อมชนะซื้อแล้วถือ {improved} แบบ",
            "",
            "## ช่วงราคาที่ใช้",
            "",
            _range_line("BTC รายวัน", daily["BTC"]),
            _range_line("ETH รายวัน", daily["ETH"]),
            _range_line("BTC 4 ชั่วโมง", intra["BTC"]),
            _range_line("ETH 4 ชั่วโมง", intra["ETH"]),
            "",
            "## สรุปทั้งสองเหรียญ",
            "",
            render_verdict_table(frame, verdict),
            "",
            "## รายเหรียญ",
            "",
            render_detail_table(frame),
            "",
        ]
    )
    (RESULTS / "macro_factors.md").write_text(header, encoding="utf-8")
    print(f"ผ่านเกณฑ์เก็บ {accepted} จาก {len(verdict)}  ดีกว่ากติกาเดิมด้วย {improved}")
    print(f"เขียน {RESULTS / 'macro_factors.md'}")


if __name__ == "__main__":
    main()
