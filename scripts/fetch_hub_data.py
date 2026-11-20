#!/usr/bin/env python3
"""Download public macro series and headlines into docs/hub/data.

No API key and no secret. FRED is the public CSV endpoint
(https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES). Bitcoin is the
Bitstamp public daily candle, with Kraken's public OHLC as a fallback.
Headlines come from Google News RSS. If a feed is down, Palantir falls back
to Yahoo Finance, macro to BBC Business, and SpaceX to SpaceNews items that
mention SpaceX. CNBC and Reuters RSS answered 403/401 without a key, so they
are not used.

A failed source keeps the previous points or headlines and sets "error".
The page then shows the last good numbers plus a muted failure note.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "docs" / "hub" / "data"
USER_AGENT = "GrokTradingHub/1.0 (+https://github.com/Pigger111-hub/Grok-trading; personal dashboard)"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
BITSTAMP_URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=86400&limit=450"
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1440"
MAX_BYTES = 5_000_000
NEWS_LIMIT = 5

SERIES = (
    {
        "id": "DFF",
        "kind": "fred",
        "keep": 450,
        "title_th": "ดอกเบี้ย Fed Funds",
        "title_en": "Effective Federal Funds Rate",
        "unit": "percent",
        "frequency": "daily",
        "frequency_th": "รายวัน",
        "source": "FRED DFF",
        "source_url": "https://fred.stlouisfed.org/series/DFF",
    },
    {
        "id": "M2SL",
        "kind": "fred",
        "keep": 120,
        "title_th": "ปริมาณเงิน M2",
        "title_en": "M2 money supply",
        "unit": "billions_usd",
        "frequency": "monthly",
        "frequency_th": "รายเดือน",
        "source": "FRED M2SL",
        "source_url": "https://fred.stlouisfed.org/series/M2SL",
    },
    {
        "id": "WALCL",
        "kind": "fred",
        "keep": 160,
        "title_th": "งบดุลเฟด",
        "title_en": "Fed total assets",
        "unit": "millions_usd",
        "frequency": "weekly",
        "frequency_th": "รายสัปดาห์",
        "source": "FRED WALCL",
        "source_url": "https://fred.stlouisfed.org/series/WALCL",
    },
    {
        "id": "BTC",
        "kind": "btc",
        "keep": 450,
        "title_th": "ราคาบิตคอยน์",
        "title_en": "Bitcoin",
        "unit": "usd",
        "frequency": "daily",
        "frequency_th": "รายวัน",
        "source": "Bitstamp BTC/USD",
        "source_url": "https://www.bitstamp.net/markets/btc/usd",
    },
)

TOPICS = (
    {
        "id": "spacex",
        "title_th": "SpaceX",
        "ticker": "SPCX",
        "feeds": (
            {"url": "https://news.google.com/rss/search?q=SpaceX&hl=en-US&gl=US&ceid=US:en"},
            {"url": "https://spacenews.com/feed/", "source": "SpaceNews", "require": "spacex"},
        ),
    },
    {
        "id": "pltr",
        "title_th": "Palantir",
        "ticker": "PLTR",
        "feeds": (
            {"url": "https://news.google.com/rss/search?q=Palantir+OR+PLTR&hl=en-US&gl=US&ceid=US:en"},
            {
                "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=PLTR&region=US&lang=en-US",
                "source": "Yahoo Finance",
            },
        ),
    },
    {
        "id": "macro",
        "title_th": "เศรษฐกิจมหภาค",
        "ticker": "MACRO",
        "feeds": (
            {
                "url": "https://news.google.com/rss/search?q=%22Federal+Reserve%22+OR+inflation+OR+%22interest+rates%22&hl=en-US&gl=US&ceid=US:en",
            },
            {"url": "https://feeds.bbci.co.uk/news/business/rss.xml", "source": "BBC Business"},
        ),
    },
)


class HubFetchError(RuntimeError):
    """A public source did not return usable data. Callers keep the last file."""


def bangkok_now() -> str:
    return datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="minutes")


def http_get(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            data = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HubFetchError(str(exc)) from exc
    if len(data) > MAX_BYTES:
        raise HubFetchError("response too large")
    return data


def clean_number(raw) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text in {"", "."}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value:
        return None
    return round(value, 6)


def parse_fred_csv(text: str, series_id: str) -> list[dict]:
    rows = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    points = []
    for row in rows:
        if not row:
            continue
        day = (row.get("observation_date") or row.get("DATE") or "").strip()
        raw = row.get(series_id)
        if raw is None:
            for key, value in row.items():
                if key and key not in {"observation_date", "DATE"}:
                    raw = value
                    break
        value = clean_number(raw)
        if not day or value is None:
            continue
        points.append({"date": day, "value": value})
    points.sort(key=lambda item: item["date"])
    return points


def dedupe_points(points: list[dict]) -> list[dict]:
    by_day = {}
    for point in points:
        by_day[point["date"]] = point
    return [by_day[day] for day in sorted(by_day)]


def parse_bitstamp_ohlc(payload: dict) -> list[dict]:
    rows = ((payload or {}).get("data") or {}).get("ohlc") or []
    points = []
    for row in rows:
        day = datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).date().isoformat()
        value = clean_number(row.get("close"))
        if value is None:
            continue
        points.append({"date": day, "value": value})
    return dedupe_points(points)


def parse_kraken_ohlc(payload: dict) -> list[dict]:
    result = (payload or {}).get("result") or {}
    rows = []
    for key, value in result.items():
        if key == "last" or not isinstance(value, list):
            continue
        rows = value
        break
    points = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        day = datetime.fromtimestamp(int(float(row[0])), timezone.utc).date().isoformat()
        value = clean_number(row[4])
        if value is None:
            continue
        points.append({"date": day, "value": value})
    return dedupe_points(points)


def fetch_btc_points(fetch, keep: int) -> tuple[list[dict], str]:
    bitstamp_error = None
    try:
        payload = json.loads(fetch(BITSTAMP_URL).decode("utf-8"))
        points = parse_bitstamp_ohlc(payload)
        if points:
            return points[-keep:], "Bitstamp BTC/USD"
        bitstamp_error = "empty bitstamp book"
    except (HubFetchError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        bitstamp_error = str(exc)
    try:
        payload = json.loads(fetch(KRAKEN_URL).decode("utf-8"))
        points = parse_kraken_ohlc(payload)
    except (HubFetchError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HubFetchError(bitstamp_error or str(exc)) from exc
    if not points:
        raise HubFetchError(bitstamp_error or "empty btc book")
    return points[-keep:], "Kraken XBT/USD"


def fetch_fred_points(series_id: str, keep: int, fetch) -> list[dict]:
    text = fetch(FRED_URL.format(series_id=series_id)).decode("utf-8")
    points = parse_fred_csv(text, series_id)
    if not points:
        raise HubFetchError("empty " + series_id)
    return points[-keep:]


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def parse_rss(raw: bytes, default_source: str | None = None) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HubFetchError("rss is not xml") from exc
    items = []
    for node in root.iter():
        if _local_name(node.tag) != "item":
            continue
        fields = {}
        for child in list(node):
            fields.setdefault(_local_name(child.tag), child)
        title = " ".join((fields.get("title").text if fields.get("title") is not None and fields.get("title").text else "").split())
        link_node = fields.get("link")
        link = (link_node.text or "").strip() if link_node is not None and link_node.text else ""
        if link and not (link.startswith("https://") or link.startswith("http://")):
            link = ""
        source_node = fields.get("source")
        source = ""
        if source_node is not None and source_node.text:
            source = " ".join(source_node.text.split())
        if not source and default_source:
            source = default_source
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        pub_node = fields.get("pubDate")
        if pub_node is None:
            pub_node = fields.get("date")
        published = None
        if pub_node is not None and pub_node.text:
            try:
                stamp = parsedate_to_datetime(pub_node.text.strip())
            except (TypeError, ValueError, IndexError):
                stamp = None
            if stamp is not None:
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                published = stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if not title:
            continue
        items.append(
            {
                "title": title[:240],
                "source": source[:80],
                "time": published,
                "link": link,
            }
        )
    return items


def latest_items(items: list[dict], limit: int = NEWS_LIMIT) -> list[dict]:
    ordered = sorted(
        items,
        key=lambda item: (item.get("time") or "", item.get("title") or ""),
        reverse=True,
    )
    chosen = []
    seen = set()
    for item in ordered:
        key = (item.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def pull_topic(topic: dict, fetch) -> tuple[list[dict] | None, str | None]:
    saw_error = False
    for feed in topic["feeds"]:
        try:
            items = parse_rss(fetch(feed["url"]), feed.get("source"))
        except HubFetchError:
            saw_error = True
            continue
        needle = (feed.get("require") or "").lower()
        if needle:
            items = [item for item in items if needle in item["title"].lower()]
        items = latest_items(items, NEWS_LIMIT)
        if items:
            return items, None
        saw_error = True
    return None, "fetch failed" if saw_error else "fetch failed"


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_json(path: Path, payload: dict) -> bool:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def with_stamp(previous: dict, payload: dict, now_iso: str) -> dict:
    draft = dict(payload)
    draft["fetched_at"] = now_iso
    old = {key: value for key, value in (previous or {}).items() if key != "fetched_at"}
    new = {key: value for key, value in draft.items() if key != "fetched_at"}
    if old == new and previous.get("fetched_at"):
        draft["fetched_at"] = previous["fetched_at"]
    return draft


def series_shell(spec: dict, points: list[dict], error: str | None) -> dict:
    return {
        "id": spec["id"],
        "title_th": spec["title_th"],
        "title_en": spec["title_en"],
        "unit": spec["unit"],
        "frequency": spec["frequency"],
        "frequency_th": spec["frequency_th"],
        "source": spec["source"],
        "source_url": spec["source_url"],
        "points": points,
        "error": error,
    }


def refresh_macro(previous: dict, fetch, now_iso: str) -> dict:
    prior = (previous or {}).get("series") or {}
    series = {}
    for spec in SERIES:
        old = prior.get(spec["id"]) if isinstance(prior.get(spec["id"]), dict) else {}
        old_points = old.get("points") if isinstance(old.get("points"), list) else []
        try:
            source = spec["source"]
            if spec["kind"] == "btc":
                points, source = fetch_btc_points(fetch, spec["keep"])
            else:
                points = fetch_fred_points(spec["id"], spec["keep"], fetch)
            row = series_shell(spec, points, None)
            row["source"] = source
            series[spec["id"]] = row
        except HubFetchError:
            series[spec["id"]] = series_shell(spec, old_points, "fetch failed")
    payload = {
        "ok": all(not row["error"] for row in series.values()),
        "series": series,
    }
    return with_stamp(previous, payload, now_iso)


def refresh_news(previous: dict, fetch, now_iso: str) -> dict:
    prior_topics = (previous or {}).get("topics") or {}
    topics = {}
    for topic in TOPICS:
        old = prior_topics.get(topic["id"]) if isinstance(prior_topics.get(topic["id"]), dict) else {}
        old_items = old.get("items") if isinstance(old.get("items"), list) else []
        items, error = pull_topic(topic, fetch)
        if items:
            stored = items
            error = None
        else:
            stored = old_items
            error = error or "fetch failed"
        topics[topic["id"]] = {
            "id": topic["id"],
            "title_th": topic["title_th"],
            "ticker": topic["ticker"],
            "items": stored,
            "error": error,
        }
    payload = {
        "ok": all(not row["error"] for row in topics.values()),
        "topics": topics,
    }
    return with_stamp(previous, payload, now_iso)


def update_hub(folder: Path, fetch=http_get, now_iso: str | None = None) -> dict:
    """Refresh macro.json and news.json. goals.json is never touched."""
    stamp = now_iso or bangkok_now()
    macro_path = folder / "macro.json"
    news_path = folder / "news.json"
    macro = refresh_macro(load_json(macro_path), fetch, stamp)
    news = refresh_news(load_json(news_path), fetch, stamp)
    save_json(macro_path, macro)
    save_json(news_path, news)
    return {"macro": macro, "news": news}


def main() -> int:
    result = update_hub(DATA_DIR)
    for spec in SERIES:
        row = result["macro"]["series"][spec["id"]]
        state = "FAIL" if row["error"] else "ok"
        last = row["points"][-1]["date"] if row["points"] else "none"
        print(f"macro {spec['id']} {state} {len(row['points'])} points last {last}")
    for topic in TOPICS:
        row = result["news"]["topics"][topic["id"]]
        state = "FAIL" if row["error"] else "ok"
        print(f"news {topic['id']} {state} {len(row['items'])} items")
    if not result["macro"]["ok"] or not result["news"]["ok"]:
        print("บางแหล่งอัปเดตไม่ได้ ไฟล์เก่ายังอยู่")
    return 0


if __name__ == "__main__":
    sys.exit(main())
