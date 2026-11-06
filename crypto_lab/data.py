"""Download daily prices from free public sources that do not need an API key.

Backtests use real OHLCV only:

* BTC-USD: Bitstamp daily candles, from the first day they printed (2011-08-18).
* ETH-USD: Bitfinex daily candles, from the first day they printed (2016-03-09).

Earlier history exists only as a single daily reference price (no high, low, or
volume). It is saved beside the candles and is not mixed into them. Inventing
high = low = close would make breakout strategies look at a fake wick.

Yahoo Finance is downloaded only to check that our closes are in the same
ballpark as a second public source. Kraken's public OHLC call, as of this
writing, returns only the most recent ~720 daily candles, so it is not used.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"
QUALITY_PATH = ROOT / "data" / "QUALITY.md"

BITSTAMP_START = {
    "btcusd": 1313625600,  # 2011-08-18
    "ethusd": 1438387200,  # 2015-08-01, used only to confirm the pair starts later
}
BITFINEX_ETH_START_MS = 1451606400000  # 2016-01-01, candles themselves begin in March

USER_AGENT = "crypto-research-lab/1.0 (educational backtest; no orders)"


def http_get_json(url: str, params: dict | None = None, retries: int = 4):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=60)
            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                last_error = RuntimeError(f"{response.status_code} from {url}")
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ดาวน์โหลดไม่สำเร็จ: {url}") from last_error


def _as_timestamp(raw_value, unit: str, align_midnight: bool) -> pd.Timestamp:
    stamp = pd.to_datetime(int(raw_value), unit=unit, utc=True).tz_convert(None)
    return stamp.normalize() if align_midnight else stamp


def parse_bitstamp(raw: list, source: str = "bitstamp", align_midnight: bool = True) -> pd.DataFrame:
    rows = []
    for candle in raw:
        rows.append(
            {
                "date": _as_timestamp(candle["timestamp"], "s", align_midnight),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle["volume"]),
                "source": source,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.set_index("date")


def parse_bitfinex(raw: list, source: str = "bitfinex", align_midnight: bool = True) -> pd.DataFrame:
    # Documented order is [MTS, OPEN, CLOSE, HIGH, LOW, VOLUME], not OHLCV.
    rows = []
    for candle in raw:
        mts, open_, close, high, low, volume = candle[:6]
        rows.append(
            {
                "date": _as_timestamp(mts, "ms", align_midnight),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "source": source,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.set_index("date")


def parse_coinbase(raw: list, source: str = "coinbase") -> pd.DataFrame:
    # [time, low, high, open, close, volume], time in seconds.
    rows = []
    for candle in raw:
        ts, low, high, open_, close, volume = candle[:6]
        rows.append(
            {
                "date": pd.to_datetime(int(ts), unit="s", utc=True).tz_convert(None).normalize(),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
                "source": source,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.set_index("date")


def normalize_ohlcv(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop bad candles, duplicate days, and today's unfinished candle.

    Missing calendar days are left missing. They are not forward-filled.
    """
    df = frame.copy()
    if "date" not in df.columns:
        df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(None).dt.normalize()
    notes = {"dropped_bad": 0, "dropped_duplicate": 0, "dropped_incomplete": 0}
    before = len(df)
    df = df.drop_duplicates(subset=["date"], keep="last")
    notes["dropped_duplicate"] = before - len(df)

    today = pd.Timestamp(datetime.now(timezone.utc).date())
    incomplete = df["date"] >= today
    notes["dropped_incomplete"] = int(incomplete.sum())
    df = df.loc[~incomplete].copy()

    numbers = ["open", "high", "low", "close"]
    for column in numbers:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    bad = (
        df[numbers].isna().any(axis=1)
        | (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
        | (df["close"] <= 0)
        | (df["open"] <= 0)
    )
    notes["dropped_bad"] = int(bad.sum())
    df = df.loc[~bad].sort_values("date")
    return df.reset_index(drop=True), notes


def calendar_gaps(dates) -> list[tuple]:
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values().unique()
    gaps = []
    for prev, nxt in zip(idx, idx[1:]):
        missing = pd.date_range(prev + pd.Timedelta(days=1), nxt - pd.Timedelta(days=1), freq="D")
        if len(missing):
            gaps.append((missing[0], missing[-1]))
    return gaps


def fetch_bitstamp_daily(pair: str, start_ts: int) -> pd.DataFrame:
    return fetch_bitstamp(pair, start_ts, step_seconds=86400, align_midnight=True)


def fetch_bitstamp(pair: str, start_ts: int, step_seconds: int, align_midnight: bool) -> pd.DataFrame:
    rows = []
    seen = set()
    cursor = start_ts
    end_ts = int(datetime.now(timezone.utc).timestamp())
    while cursor < end_ts:
        payload = http_get_json(
            f"https://www.bitstamp.net/api/v2/ohlc/{pair}/",
            {"step": step_seconds, "limit": 1000, "start": cursor},
        )
        batch = payload.get("data", {}).get("ohlc", [])
        fresh = []
        for candle in batch:
            stamp = int(candle["timestamp"])
            if stamp not in seen:
                seen.add(stamp)
                fresh.append(candle)
        if not fresh:
            break
        rows.extend(fresh)
        next_cursor = max(int(candle["timestamp"]) for candle in batch) + step_seconds
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(0.2)
    return parse_bitstamp(rows, source=f"bitstamp:{pair}", align_midnight=align_midnight)


def fetch_bitfinex_daily(symbol: str, start_ms: int) -> pd.DataFrame:
    return fetch_bitfinex(symbol, start_ms, interval="1D", step_ms=86_400_000, align_midnight=True)


def fetch_bitfinex(symbol: str, start_ms: int, interval: str, step_ms: int, align_midnight: bool) -> pd.DataFrame:
    rows = []
    seen = set()
    cursor = start_ms
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    while cursor < end_ms:
        payload = http_get_json(
            f"https://api-pub.bitfinex.com/v2/candles/trade:{interval}:{symbol}/hist",
            {"limit": 10000, "sort": 1, "start": cursor},
        )
        if not isinstance(payload, list) or not payload:
            break
        fresh = []
        for candle in payload:
            stamp = int(candle[0])
            if stamp not in seen:
                seen.add(stamp)
                fresh.append(candle)
        if not fresh:
            break
        rows.extend(fresh)
        next_cursor = max(int(candle[0]) for candle in payload) + step_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < 10000:
            break
        time.sleep(0.3)
    return parse_bitfinex(rows, source=f"bitfinex:{symbol}", align_midnight=align_midnight)


def fetch_yahoo_daily(symbol: str) -> pd.DataFrame:
    payload = http_get_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        {"period1": 0, "period2": 2000000000, "interval": "1d", "events": "history"},
    )
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_convert(None).normalize(),
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
            "source": f"yahoo:{symbol}",
        }
    )
    return frame.set_index("date")


def fetch_coinbase_daily(product: str, start: datetime, end: datetime) -> pd.DataFrame:
    rows = []
    seen = set()
    cursor = start
    while cursor < end:
        chunk_end = min(end, cursor + timedelta(days=290))
        try:
            payload = http_get_json(
                f"https://api.exchange.coinbase.com/products/{product}/candles",
                {
                    "granularity": 86400,
                    "start": cursor.strftime("%Y-%m-%dT00:00:00Z"),
                    "end": chunk_end.strftime("%Y-%m-%dT00:00:00Z"),
                },
            )
        except RuntimeError:
            break
        if not isinstance(payload, list):
            break
        for candle in payload:
            stamp = int(candle[0])
            if stamp not in seen:
                seen.add(stamp)
                rows.append(candle)
        cursor = chunk_end
        time.sleep(0.15)
    return parse_coinbase(rows, source=f"coinbase:{product}")


def fetch_coinmetrics_price(asset: str, start: str, end: str) -> pd.DataFrame:
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    params = {
        "assets": asset,
        "metrics": "PriceUSD",
        "frequency": "1d",
        "start_time": start,
        "end_time": end,
        "page_size": 10000,
    }
    rows = []
    while url:
        payload = http_get_json(url, params)
        rows.extend(payload.get("data", []))
        url = payload.get("next_page_url")
        params = None
        if url:
            time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["date", "price_usd", "source"])
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(None).dt.normalize()
    frame["price_usd"] = pd.to_numeric(frame["PriceUSD"], errors="coerce")
    frame["source"] = f"coinmetrics:{asset}"
    frame = frame.dropna(subset=["price_usd"])
    frame = frame.loc[frame["price_usd"] > 0, ["date", "price_usd", "source"]]
    return frame.drop_duplicates("date").sort_values("date")


def _prepare(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if isinstance(raw.index, pd.DatetimeIndex) and raw.index.name == "date":
        raw = raw.reset_index()
    clean, notes = normalize_ohlcv(raw)
    return clean, notes


def _overlap(primary: pd.DataFrame, other: pd.DataFrame) -> dict | None:
    if other is None or other.empty or primary.empty:
        return None
    left = primary.set_index("date")["close"]
    right_frame = other.reset_index() if "date" not in other.columns else other
    right = right_frame.set_index("date")["close"]
    joined = pd.concat([left.rename("primary"), right.rename("other")], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None
    gap = (joined["other"] / joined["primary"] - 1.0).abs()
    returns = joined.pct_change().dropna()
    return {
        "days": int(len(joined)),
        "start": joined.index.min().date().isoformat(),
        "end": joined.index.max().date().isoformat(),
        "median_abs_close_gap": float(gap.median()),
        "return_correlation": float(returns["primary"].corr(returns["other"])),
    }


def _fmt_gaps(dates) -> tuple[int, int, list[str]]:
    gaps = calendar_gaps(dates)
    one_day = [gap for gap in gaps if gap[0] == gap[1]]
    longer = [gap for gap in gaps if gap[0] != gap[1]]
    lines = []
    for start, end in longer[:12]:
        days = (end - start).days + 1
        lines.append(f"- {start.date().isoformat()} ถึง {end.date().isoformat()} ({days} วัน)")
    if len(longer) > 12:
        lines.append(f"- … และอีก {len(longer) - 12} ช่วง")
    return len(one_day), len(longer), lines


def _write_quality(btc, eth, btc_early, eth_early, checks: dict, clean_notes: dict) -> None:
    def block(name, frame, notes):
        one_day, longer, lines = _fmt_gaps(frame["date"])
        text = [
            f"### {name}",
            "",
            f"- จำนวนวัน: {len(frame)}",
            f"- วันแรก: {frame['date'].min().date().isoformat()}",
            f"- วันสุดท้าย: {frame['date'].max().date().isoformat()}",
            f"- แหล่งที่มา: {frame['source'].iloc[0]}",
            f"- แท่งที่ตัดเพราะราคาเป็นไปไม่ได้: {notes['dropped_bad']}",
            f"- วันที่ซ้ำที่ตัดทิ้ง: {notes['dropped_duplicate']}",
            f"- แท่งวันนี้ที่ยังไม่จบวัน (ตัดทิ้ง): {notes['dropped_incomplete']}",
            f"- วันที่ขาดหายไป 1 วัน: {one_day} วัน (ไม่ได้เติมราคาให้)",
            f"- ช่วงที่ขาดติดต่อกันมากกว่า 1 วัน: {longer} ช่วง",
        ]
        if lines:
            text.append("- ช่วงที่ขาดยาว:")
            text.extend(lines)
        else:
            text.append("- ไม่มีช่วงที่ขาดยาวกว่า 1 วัน")
        return "\n".join(text)

    def check_block(title, stats):
        if not stats:
            return f"### {title}\n\nไม่มีข้อมูลทับซ้อนมากพอให้เทียบ"
        warn = ""
        if stats["median_abs_close_gap"] > 0.03:
            warn = "\n\n**คำเตือน:** ราคาปิดสองแหล่งห่างกันเกิน 3% (ค่ามัธยฐาน) ควรตรวจก่อนเชื่อผลทดสอบ"
        return (
            f"### {title}\n\n"
            f"- วันที่ทับกัน: {stats['days']} วัน ({stats['start']} ถึง {stats['end']})\n"
            f"- ช่องว่างของราคาปิดแบบมัธยฐาน: {stats['median_abs_close_gap'] * 100:.3f}%\n"
            f"- สหสัมพันธ์ของผลตอบแทนรายวัน: {stats['return_correlation']:.4f}"
            f"{warn}"
        )

    early_btc = (
        f"- BTC ราคาอ้างอิงก่อนมี OHLCV: {btc_early['date'].min().date().isoformat()} "
        f"ถึง {btc_early['date'].max().date().isoformat()} "
        f"({len(btc_early)} วัน, {btc_early['source'].iloc[0]})"
        if len(btc_early)
        else "- ไม่พบราคา BTC ช่วงต้น"
    )
    early_eth = (
        f"- ETH ราคาอ้างอิงก่อนมี OHLCV: {eth_early['date'].min().date().isoformat()} "
        f"ถึง {eth_early['date'].max().date().isoformat()} "
        f"({len(eth_early)} วัน, {eth_early['source'].iloc[0]})"
        if len(eth_early)
        else "- ไม่พบราคา ETH ช่วงต้น"
    )
    body = f"""# คุณภาพข้อมูล

ไฟล์นี้ถูกเขียนใหม่ทุกครั้งที่รัน `python scripts/download_data.py` หรือ `python scripts/run_all.py`

แบ็กเทสต์ใช้เฉพาะไฟล์ OHLCV ด้านล่าง ไม่ได้ใช้ไฟล์ราคาเดี่ยวช่วงต้น และไม่ได้ต่อราคาจากคนละแหล่งเข้าด้วยกัน

## ทำไมไม่ต่อแท่งเทียนจากหลายแหล่ง

ช่วงที่แหล่งหนึ่งยังไม่มีแท่งเทียน เราเก็บราคาปิดอ้างอิงแยกไว้ แต่ไม่ใส่เข้าไปในไฟล์ OHLCV
เพราะกลยุทธ์ที่ดูจุดสูงสุดจุดต่ำสุด (เช่น ดอนเชียน) จะเห็นไส้เทียนปลอม ถ้ายัดให้ open = high = low = close

เราตรวจแหล่งสาธารณะเหล่านี้แล้วไม่ได้ใช้เป็นแท่งเทียนหลัก:

- Yahoo Finance chart API ไม่ต้องใช้กุญแจ: BTC-USD เริ่ม 2014-09-17, ETH-USD เริ่ม 2017-11-09 ใช้เป็นตัวเทียบเท่านั้น
- Kraken OHLC สาธารณะส่งกลับมาแค่ประมาณ 720 แท่งล่าสุด แม้จะใส่ `since` ย้อนไปปี 2013 จึงเอาไปครอบคลุมประวัติยาวไม่ได้
- Binance klines ถูกปฏิเสธจากเครือข่ายนี้ (HTTP 451)
- CryptoCompare, CoinGecko และ CoinPaprika ขอ API key หรือแผนเสียเงินสำหรับประวัตินี้
- Coinbase มี ETH-USD รายวันตั้งแต่ประมาณกลางปี 2016 ซึ่งช้ากว่า Bitfinex เล็กน้อย จึงใช้เป็นตัวเทียบ ไม่ใช้เป็นชุดหลัก

## OHLCV ที่ใช้ทดสอบ

{block("BTC-USD", btc, clean_notes["btc"])}

{block("ETH-USD", eth, clean_notes["eth"])}

## ราคาเดี่ยวช่วงที่ยังไม่มีแท่งเทียน (ไม่ได้ใช้ในแบ็กเทสต์)

{early_btc}

{early_eth}

ราคาเหล่านี้มาจาก Coin Metrics Community API เมตริก `PriceUSD` ความถี่รายวัน ไม่ใช่ราคาเปิด-สูง-ต่ำ-ปิด
ของตลาดใดตลาดหนึ่ง BTC เริ่มมีราคาในชุดนี้วันที่ 2010-07-18 ก่อนหน้านั้นมีแต่ราคาซื้อขายเล็ก ๆ
ที่ไม่มีชุดรายวันที่น่าเชื่อถือพอจะทดสอบกลยุทธ์ ETH เริ่มมีราคาในชุดนี้ช่วงต้นเดือนสิงหาคม 2015
หลังเครือข่ายเริ่มทำงานปลายเดือนกรกฎาคม 2015

ช่วงที่ ETH ขาดไป 7 วัน (2016-08-03 ถึง 2016-08-09) เป็นช่วงที่ Bitfinex หยุดซื้อขายหลังถูกแฮกวันที่ 2 สิงหาคม 2016
ไม่ได้เกิดจากตัวดาวน์โหลด และไม่ได้เติมราคาจากตลาดอื่นเข้าไปในช่องนั้น

## ตัวเทียบจากแหล่งที่สอง

{check_block("BTC Bitstamp เทียบ Yahoo BTC-USD", checks.get("btc_yahoo"))}

{check_block("ETH Bitfinex เทียบ Yahoo ETH-USD", checks.get("eth_yahoo"))}

{check_block("ETH Bitfinex เทียบ Coinbase ETH-USD", checks.get("eth_coinbase"))}
"""
    QUALITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_PATH.write_text(body, encoding="utf-8")


def _require_history(frame: pd.DataFrame, latest_allowed_start: str, minimum_rows: int, label: str) -> None:
    if frame.empty:
        raise RuntimeError(f"ไม่ได้ข้อมูล {label} เลย ตรวจอินเทอร์เน็ตแล้วรันใหม่")
    start = frame["date"].min()
    if start > pd.Timestamp(latest_allowed_start) or len(frame) < minimum_rows:
        raise RuntimeError(
            f"ประวัติ {label} สั้นผิดปกติ (เริ่ม {start.date().isoformat()}, {len(frame)} วัน) "
            "แหล่งข้อมูลอาจส่งมาไม่ครบ ยังไม่เขียนทับไฟล์แคช"
        )


def update_all(cache_dir: Path = CACHE_DIR) -> dict[str, pd.DataFrame]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    print("กำลังดาวน์โหลด BTC รายวันจาก Bitstamp (ไม่ใช้ API key) ...")
    btc_raw = fetch_bitstamp_daily("btcusd", BITSTAMP_START["btcusd"])
    btc, btc_notes = _prepare(btc_raw)
    _require_history(btc, "2012-01-01", 4000, "BTC")

    print("กำลังดาวน์โหลด ETH รายวันจาก Bitfinex ...")
    eth_raw = fetch_bitfinex_daily("tETHUSD", BITFINEX_ETH_START_MS)
    eth, eth_notes = _prepare(eth_raw)
    _require_history(eth, "2016-06-01", 3000, "ETH")

    print("กำลังดาวน์โหลดราคาอ้างอิงช่วงต้นจาก Coin Metrics ...")
    btc_early = fetch_coinmetrics_price("btc", "2009-01-01", btc["date"].min().date().isoformat())
    btc_early = btc_early.loc[btc_early["date"] < btc["date"].min()]
    eth_early = fetch_coinmetrics_price("eth", "2015-08-01", eth["date"].min().date().isoformat())
    eth_early = eth_early.loc[eth_early["date"] < eth["date"].min()]

    print("กำลังเทียบกับ Yahoo Finance และ Coinbase ...")
    btc_yahoo, _ = _prepare(fetch_yahoo_daily("BTC-USD"))
    eth_yahoo, _ = _prepare(fetch_yahoo_daily("ETH-USD"))
    now = datetime.now(timezone.utc)
    eth_coinbase_raw = fetch_coinbase_daily("ETH-USD", datetime(2016, 5, 1, tzinfo=timezone.utc), now)
    eth_coinbase, _ = _prepare(eth_coinbase_raw) if len(eth_coinbase_raw) else (pd.DataFrame(), {})

    checks = {
        "btc_yahoo": _overlap(btc, btc_yahoo),
        "eth_yahoo": _overlap(eth, eth_yahoo),
        "eth_coinbase": _overlap(eth, eth_coinbase) if len(eth_coinbase) else None,
    }
    btc.to_csv(cache_dir / "btc_usd_daily.csv", index=False)
    eth.to_csv(cache_dir / "eth_usd_daily.csv", index=False)
    btc_early.to_csv(cache_dir / "btc_usd_early_price.csv", index=False)
    eth_early.to_csv(cache_dir / "eth_usd_early_price.csv", index=False)
    _write_quality(
        btc,
        eth,
        btc_early,
        eth_early,
        checks,
        {"btc": btc_notes, "eth": eth_notes},
    )
    print(
        f"BTC {btc['date'].min().date()} → {btc['date'].max().date()} ({len(btc)} วัน)  "
        f"ETH {eth['date'].min().date()} → {eth['date'].max().date()} ({len(eth)} วัน)"
    )
    print(f"บันทึกคุณภาพข้อมูลไว้ที่ {QUALITY_PATH}")
    print("กำลังดาวน์โหลดแท่ง 4 ชั่วโมง (ไม่ดาวน์โหลดแท่ง 1 ชั่วโมง) ...")
    btc_4h = prepare_intraday(
        fetch_bitstamp("btcusd", BITSTAMP_START["btcusd"], step_seconds=14_400, align_midnight=False),
        bar_hours=4,
    )
    eth_4h = prepare_intraday(
        fetch_bitfinex(
            "tETHUSD",
            BITFINEX_ETH_START_MS,
            interval="4h",
            step_ms=14_400_000,
            align_midnight=False,
        ),
        bar_hours=4,
    )
    _require_history(btc_4h, "2012-01-01", 20_000, "BTC 4h")
    _require_history(eth_4h, "2016-06-01", 12_000, "ETH 4h")
    btc_4h.to_csv(cache_dir / "btc_usd_4h.csv", index=False)
    eth_4h.to_csv(cache_dir / "eth_usd_4h.csv", index=False)
    note = (
        "\n## แท่ง 4 ชั่วโมง\n\n"
        f"- BTC: {btc_4h['date'].min()} ถึง {btc_4h['date'].max()} จำนวน {len(btc_4h)} แท่ง จาก Bitstamp\n"
        f"- ETH: {eth_4h['date'].min()} ถึง {eth_4h['date'].max()} จำนวน {len(eth_4h)} แท่ง จาก Bitfinex\n"
        "- ไม่ได้ดาวน์โหลดแท่ง 1 ชั่วโมง เพราะสัญญาณหลอกถี่และค่าธรรมเนียมจะกินผลกำไร\n"
    )
    QUALITY_PATH.write_text(QUALITY_PATH.read_text(encoding="utf-8") + note, encoding="utf-8")
    print(
        f"BTC 4h {len(btc_4h)} แท่ง  ETH 4h {len(eth_4h)} แท่ง"
    )
    return {"BTC": load_ohlcv(cache_dir / "btc_usd_daily.csv"), "ETH": load_ohlcv(cache_dir / "eth_usd_daily.csv")}


def prepare_intraday(raw: pd.DataFrame, bar_hours: int) -> pd.DataFrame:
    """Keep only closed intraday bars. Do not snap timestamps to midnight."""
    frame = raw.reset_index() if "date" not in raw.columns else raw.copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_convert(None)
    frame = frame.drop_duplicates(subset=["date"], keep="last")
    now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    closed = frame["date"] + pd.Timedelta(hours=bar_hours) <= now
    frame = frame.loc[closed].copy()
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    good = (
        frame[["open", "high", "low", "close"]].notna().all(axis=1)
        & (frame["high"] >= frame["low"])
        & (frame["high"] >= frame["open"])
        & (frame["high"] >= frame["close"])
        & (frame["low"] <= frame["open"])
        & (frame["low"] <= frame["close"])
        & (frame["close"] > 0)
        & (frame["open"] > 0)
    )
    return frame.loc[good].sort_values("date").reset_index(drop=True)


def load_4h(cache_dir: Path = CACHE_DIR) -> dict[str, pd.DataFrame]:
    return {
        "BTC": load_ohlcv(cache_dir / "btc_usd_4h.csv"),
        "ETH": load_ohlcv(cache_dir / "eth_usd_4h.csv"),
    }


def load_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["date"])
    frame = frame.set_index("date").sort_index()
    missing = [column for column in ("open", "high", "low", "close") if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{path} ขาดคอลัมน์ {missing}")
    if frame.index.has_duplicates:
        raise RuntimeError(f"{path} มีวันที่ซ้ำ")
    return frame


def load_cached(cache_dir: Path = CACHE_DIR) -> dict[str, pd.DataFrame]:
    return {
        "BTC": load_ohlcv(cache_dir / "btc_usd_daily.csv"),
        "ETH": load_ohlcv(cache_dir / "eth_usd_daily.csv"),
    }
