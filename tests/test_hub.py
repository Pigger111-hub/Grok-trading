"""The personal hub page and its public-data fetch stay separate from the paper book."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_fetch():
    path = ROOT / "scripts" / "fetch_hub_data.py"
    spec = importlib.util.spec_from_file_location("fetch_hub_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hub_page_links_both_ways_and_keeps_the_white_shell():
    page = (ROOT / "docs" / "hub" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "docs" / "hub" / "hub.css").read_text(encoding="utf-8")
    js = (ROOT / "docs" / "hub" / "hub.js").read_text(encoding="utf-8")
    home = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    goals = json.loads((ROOT / "docs" / "hub" / "data" / "goals.json").read_text(encoding="utf-8"))
    assert 'href="hub/"' in home
    assert 'href="../"' in page
    assert "เงินสมมติเท่านั้น ไม่มีการซื้อขายจริง" in page
    assert "สมุดวิจัย" in page
    assert "#F3F4F6" in css
    assert "14px" in css
    assert "760px" in css
    assert ".tabbar" in css
    assert "prefers-reduced-motion" in css
    for phrase in (
        "สวัสดีตอนเช้า",
        "สวัสดีตอนบ่าย",
        "สวัสดีตอนเย็น",
        "ข้อมูลเก่า",
        "ไม่สามารถอัปเดตได้",
        "ตั้งวันสอบ",
        "ถือเหรียญ",
        "ถือเงินสด",
        "localStorage",
        "Asia/Bangkok",
        "DFF",
        "M2SL",
        "WALCL",
    ):
        assert phrase in js, phrase
    titles = [goal["title"] for goal in goals["goals"]]
    assert "ทุน ก.พ. ปริญญาโท-เอก ปี 2570 ปิดรับสมัคร" in titles
    assert "วันสอบ IELTS (ยังไม่กำหนด)" in titles
    exam = next(goal for goal in goals["goals"] if goal["date"] is None)
    assert exam["title"].startswith("วันสอบ IELTS")
    scholarship = next(goal for goal in goals["goals"] if goal["date"])
    assert scholarship["date"] == "2026-12-29"
    assert scholarship["link"] == "https://scholar.ocsc.go.th"
    labels = [item["label"] for item in goals["checklist"]]
    assert labels == ["Reading", "Listening", "Writing", "Speaking"]


def test_hub_workflow_is_daily_and_has_no_secret():
    text = (ROOT / ".github" / "workflows" / "hub-data.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "fetch_hub_data.py").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "30 0 * * *" in text
    assert "secrets." not in text
    assert "API_KEY" not in script
    assert "os.environ" not in script
    assert "fredgraph.csv?id=" in script
    assert "docs/hub/data/goals.json" not in text


def test_fetch_parses_fred_and_keeps_the_last_good_file(tmp_path):
    hub = load_fetch()
    parsed = hub.parse_fred_csv(
        "observation_date,DFF\n2026-11-17,3.75\n2026-11-18,.\n2026-11-19,3.88\n",
        "DFF",
    )
    assert parsed == [
        {"date": "2026-11-17", "value": 3.75},
        {"date": "2026-11-19", "value": 3.88},
    ]
    rss = b"""<?xml version="1.0"?><rss><channel>
      <item>
        <title>SpaceX Starship flies - SpaceNews</title>
        <link>https://example.com/starship</link>
        <pubDate>Fri, 20 Nov 2026 01:00:00 GMT</pubDate>
        <source>SpaceNews</source>
      </item>
      <item>
        <title>Unrelated satellite launch</title>
        <link>https://example.com/other</link>
        <pubDate>Fri, 20 Nov 2026 02:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    items = hub.parse_rss(rss, "SpaceNews")
    assert items[0]["title"] == "SpaceX Starship flies"
    assert items[0]["source"] == "SpaceNews"
    assert items[0]["link"] == "https://example.com/starship"
    assert items[0]["time"].startswith("2026-11-20")

    previous = {
        "fetched_at": "2026-11-19T07:30+07:00",
        "ok": True,
        "series": {
            "DFF": {"points": [{"date": "2026-11-18", "value": 3.88}]},
        },
    }
    (tmp_path / "goals.json").write_text('{"keep": true}\n', encoding="utf-8")

    def fake_fetch(url):
        if "id=DFF" in url:
            raise hub.HubFetchError("down")
        if "id=M2SL" in url:
            return b"observation_date,M2SL\n2026-09-01,23413.9\n"
        if "id=WALCL" in url:
            return b"observation_date,WALCL\n2026-11-18,6741452\n"
        if "bitstamp" in url:
            raise hub.HubFetchError("bitstamp down")
        if "kraken" in url:
            return json.dumps({"result": {"XXBTZUSD": [[1795132800, "1", "2", "3", "62000", "0", "0", "1"]]}}).encode()
        if "Palantir" in url:
            raise hub.HubFetchError("google down")
        if "yahoo" in url:
            return b"""<?xml version="1.0"?><rss><channel><item>
              <title>Palantir update</title>
              <link>https://finance.yahoo.com/pltr</link>
              <pubDate>Thu, 19 Nov 2026 20:00:00 GMT</pubDate>
            </item></channel></rss>"""
        if "SpaceX" in url:
            raise hub.HubFetchError("google down")
        if "spacenews" in url:
            return rss
        if "Federal" in url:
            raise hub.HubFetchError("google down")
        if "bbci.co.uk" in url:
            return b"""<?xml version="1.0"?><rss><channel><item>
              <title>Bank holds rates</title>
              <link>https://www.bbc.com/news/business</link>
              <pubDate>Fri, 20 Nov 2026 06:00:00 GMT</pubDate>
            </item></channel></rss>"""
        raise AssertionError(url)

    (tmp_path / "macro.json").write_text(json.dumps(previous), encoding="utf-8")
    result = hub.update_hub(tmp_path, fetch=fake_fetch, now_iso="2026-11-20T14:00+07:00")
    dff = result["macro"]["series"]["DFF"]
    assert dff["error"] == "fetch failed"
    assert dff["points"] == [{"date": "2026-11-18", "value": 3.88}]
    assert result["macro"]["series"]["M2SL"]["points"][-1]["value"] == 23413.9
    assert result["macro"]["series"]["BTC"]["points"][-1]["value"] == 62000
    assert result["macro"]["ok"] is False
    assert result["news"]["topics"]["pltr"]["items"][0]["source"] == "Yahoo Finance"
    assert result["news"]["topics"]["spacex"]["items"][0]["title"] == "SpaceX Starship flies"
    assert result["macro"]["series"]["BTC"]["source"] == "Kraken XBT/USD"
    assert all("Unrelated" not in item["title"] for item in result["news"]["topics"]["spacex"]["items"])
    assert result["news"]["topics"]["macro"]["items"][0]["source"] == "BBC Business"
    assert json.loads((tmp_path / "goals.json").read_text(encoding="utf-8")) == {"keep": True}
    again = hub.refresh_macro(result["macro"], fake_fetch, "2026-11-21T14:00+07:00")
    assert again["series"]["M2SL"]["points"] == result["macro"]["series"]["M2SL"]["points"]
    assert again["fetched_at"] == result["macro"]["fetched_at"]


def test_hub_helpers_match_the_paper_book():
    node = shutil.which("node")
    assert node, "node is required to check the hub helpers"
    script = r"""
const path = require("path");
const hub = require(path.resolve("docs/hub/hub.js"));
const dash = require(path.resolve("docs/data/dashboard.json"));
if (hub.START_DOLLARS !== 10000) process.exit(2);
if (Math.abs(hub.equityDollars(85.6996) - 8569.96) > 0.02) process.exit(3);
const eight = 8 * 60 * 60 * 1000;
const t = 1795104000;
if (hub.isStale(t, t * 1000 + eight)) process.exit(4);
if (!hub.isStale(t, t * 1000 + eight + 1)) process.exit(5);
if (!hub.isStale(null, Date.now())) process.exit(6);
const morning = Date.parse("2026-11-20T04:00:00Z");
const noon = Date.parse("2026-11-20T05:00:00Z");
const evening = Date.parse("2026-11-20T10:00:00Z");
if (hub.greeting(morning) !== "สวัสดีตอนเช้า") process.exit(7);
if (hub.greeting(noon) !== "สวัสดีตอนบ่าย") process.exit(8);
if (hub.greeting(evening) !== "สวัสดีตอนเย็น") process.exit(9);
const today = hub.formatToday(Date.parse("2026-11-20T00:00:00Z"));
if (today.indexOf("2569") === -1 || today.indexOf("พฤศจิกายน") === -1) process.exit(10);
if (hub.daysUntil("2026-12-29", Date.parse("2026-11-20T00:00:00Z")) !== 39) process.exit(11);
if (hub.daysUntil(null, Date.now()) !== null) process.exit(12);
const weekA = hub.isoWeekKey(Date.parse("2026-11-16T06:00:00Z"));
const weekB = hub.isoWeekKey(Date.parse("2026-11-20T06:00:00Z"));
const weekC = hub.isoWeekKey(Date.parse("2026-11-23T06:00:00Z"));
if (weekA !== weekB || weekA === weekC) process.exit(13);
if (hub.checklistKey(morning).indexOf("ielts-") !== 0) process.exit(14);
const cycle = hub.halvingStatus(Date.parse("2026-11-20T00:00:00Z"));
if (cycle.daysSince !== 944) process.exit(15);
if (new Date(cycle.nextMs).toISOString().indexOf("2028-04-17") !== 0) process.exit(16);
if (cycle.progress < 0.64 || cycle.progress > 0.66) process.exit(17);
const day = 86400000;
const points = [0,1,2,3,4,5,6,7,8,9].map((i) => ({t: i * day, value: i}));
const sliced = hub.slicePoints(points, "week");
if (sliced.length !== 8 || sliced[0].value !== 2) process.exit(18);
const change = hub.changeOver(points, "week");
if (change.diff !== 7 || Math.abs(change.pct - 350) > 1e-9) process.exit(19);
const sparse = hub.slicePoints([{t: 0, value: 1}, {t: 40 * day, value: 2}], "day");
if (sparse.length !== 2) process.exit(20);
const up = hub.formatTrend({diff: 0.13, pct: 3}, "points", "week");
if (up.tone !== "up" || up.text.indexOf("0.13") === -1) process.exit(21);
const down = hub.formatTrend({diff: -100, pct: -1.2}, "percent", "day");
if (down.tone !== "down" || down.text.indexOf("1.2") === -1) process.exit(22);
const flat = hub.formatTrend({diff: 0, pct: 0}, "percent", "month");
if (flat.tone !== "flat" || flat.text.indexOf("ทรงตัว") === -1) process.exit(23);
const coarse = hub.formatTrend({diff: 100, pct: 0.5, spanDays: 31}, "percent", "week");
if (coarse.text.indexOf("จากจุดก่อนหน้า") === -1) process.exit(39);
if (hub.formatMacro("M2SL", 23413.9).headline !== "$23.41") process.exit(24);
if (hub.formatMacro("WALCL", 6741452).headline !== "$6.74") process.exit(25);
if (hub.formatMacro("DFF", 3.88).headline !== "3.88%") process.exit(26);
if (hub.formatMacro("BTC", 61914.05).headline !== "$61,914") process.exit(27);
const loss = hub.pnlLabel(8569.96);
if (loss.tone !== "down" || loss.text.indexOf("ขาดทุน") === -1) process.exit(28);
const gain = hub.pnlLabel(16027);
if (gain.tone !== "up" || gain.text.indexOf("กำไร") === -1) process.exit(29);
const gap = hub.gapLabel(9658, 8051);
if (gap.tone !== "up" || gap.text.indexOf("มากกว่าซื้อแล้วถือ") === -1) process.exit(30);
if (hub.holdingBadge("long").text !== "ถือเหรียญ") process.exit(31);
if (hub.holdingBadge("cash").tone !== "warn") process.exit(32);
const cards = hub.paperModels(dash);
if (cards.length !== 12) process.exit(33);
if (cards.some((card) => card.strategy === "buy_and_hold")) process.exit(34);
if (cards.filter((card) => card.asset === "BTC").length !== 6) process.exit(35);
if (cards.some((card) => !Number.isFinite(card.value) || !Number.isFinite(card.bench))) process.exit(36);
const best = hub.bestBook(cards);
const max = Math.max.apply(null, cards.map((card) => card.value));
if (!best || best.value !== max) process.exit(37);
const unix = hub.latestDataUnix(dash);
if (!Number.isFinite(unix)) process.exit(38);
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout or completed.returncode
