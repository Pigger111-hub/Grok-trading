"""Load M2, the Fed balance sheet, and the federal funds rate.

FRED's public CSV is tried first. In this environment that host accepts the
TLS handshake and then never sends the file, so the fallback is the Board of
Governors release that FRED republishes:

* M2SL is H.6 series M2.M (seasonally adjusted M2, billions of dollars).
* WALCL is H.4.1 series RESPPMA_N.WW (total assets less consolidating
  eliminations, Wednesday level, millions of dollars).
* FEDFUNDS is H.15 series RIFSPFF_N.M (effective federal funds rate, monthly).

The saved files use FRED's two-column CSV shape so the parser is the same
either way. Latest vintage only: revisions after the first print can still
change a sign that was close to zero. ALFRED vintages are not used.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import requests

from crypto_lab.data import USER_AGENT
from crypto_lab.macro import parse_fred_csv

ROOT = Path(__file__).resolve().parents[1]
FRED_DIR = ROOT / "data" / "cache" / "fred"

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# (zip url, inner xml, SERIES_NAME, minimum rows that means the file is whole)
FED_SOURCES = {
    "M2SL": (
        "https://www.federalreserve.gov/releases/h6/data/FRB_h6_xml.zip",
        "H6_data.xml",
        "M2.M",
        700,
    ),
    "WALCL": (
        "https://www.federalreserve.gov/releases/h41/data/FRB_h41_xml.zip",
        "H41_data.xml",
        "RESPPMA_N.WW",
        1000,
    ),
    "FEDFUNDS": (
        "https://www.federalreserve.gov/releases/h15/data/FRB_H15_xml.zip",
        "H15_data.xml",
        "RIFSPFF_N.M",
        800,
    ),
}


def series_from_sdmx(xml_bytes: bytes, series_name: str) -> pd.Series:
    rows: list[tuple[str, float]] = []
    keep = False
    for event, elem in ElementTree.iterparse(io.BytesIO(xml_bytes), events=("start", "end")):
        tag = elem.tag.rsplit("}", 1)[-1]
        if event == "start" and tag == "Series":
            keep = elem.attrib.get("SERIES_NAME") == series_name
        elif event == "end" and tag == "Obs" and keep:
            raw = elem.attrib.get("OBS_VALUE")
            when = elem.attrib.get("TIME_PERIOD")
            if when and raw not in (None, "", "."):
                try:
                    rows.append((when, float(raw)))
                except ValueError:
                    pass
            elem.clear()
        elif event == "end" and tag == "Series":
            keep = False
            elem.clear()
    if not rows:
        raise RuntimeError(f"ไม่พบชุด {series_name} ในไฟล์ของเฟด")
    series = pd.Series({pd.Timestamp(when): value for when, value in rows}, dtype=float)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    series.index.name = "observation_date"
    return series


def _fred_csv(series_id: str) -> pd.Series | None:
    url = FRED_CSV.format(series_id=series_id)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"},
            timeout=(5, 12),
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    head = response.text[:300]
    if "observation_date" not in head and "DATE" not in head:
        return None
    return parse_fred_csv(response.text)


def _fed_series(series_id: str) -> pd.Series:
    url, inner, name, _minimum = FED_SOURCES[series_id]
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 120))
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_bytes = archive.read(inner)
    return series_from_sdmx(xml_bytes, name)


def fetch_macro_series() -> dict[str, tuple[pd.Series, str]]:
    """Return series id -> (values, source url that actually delivered them)."""
    loaded: dict[str, tuple[pd.Series, str]] = {}
    for series_id, (fed_url, _inner, _name, minimum) in FED_SOURCES.items():
        fred = _fred_csv(series_id)
        if fred is not None and len(fred) >= minimum:
            loaded[series_id] = (fred, FRED_CSV.format(series_id=series_id))
            continue
        fed = _fed_series(series_id)
        if len(fed) < minimum:
            raise RuntimeError(f"{series_id} สั้นผิดปกติ ({len(fed)} จุด)")
        loaded[series_id] = (fed, fed_url)
    return loaded


def write_macro_cache(loaded: dict[str, tuple[pd.Series, str]], folder: Path = FRED_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    notes = ["# แหล่งข้อมูลแมโคร", ""]
    for series_id, (series, url) in loaded.items():
        frame = series.rename(series_id).rename_axis("observation_date").reset_index()
        frame.to_csv(folder / f"{series_id}.csv", index=False)
        notes.append(
            f"- {series_id}: {series.index.min().date().isoformat()} ถึง "
            f"{series.index.max().date().isoformat()} ({len(series)} จุด) จาก {url}"
        )
    notes.extend(
        [
            "",
            "หน้าชุดข้อมูลบน FRED (ตัวเลขชุดเดียวกับไฟล์ของคณะกรรมการเฟด):",
            "- M2SL https://fred.stlouisfed.org/series/M2SL",
            "- WALCL https://fred.stlouisfed.org/series/WALCL",
            "- FEDFUNDS https://fred.stlouisfed.org/series/FEDFUNDS",
            "",
            "ไฟล์ต้นทางของคณะกรรมการเฟด:",
            "- H.6 https://www.federalreserve.gov/releases/h6/current/default.htm",
            "- H.4.1 https://www.federalreserve.gov/releases/h41/current/default.htm",
            "- H.15 https://www.federalreserve.gov/releases/h15/",
        ]
    )
    (folder / "README.md").write_text("\n".join(notes) + "\n", encoding="utf-8")


def load_macro_series(folder: Path = FRED_DIR, refresh: bool = False) -> dict[str, pd.Series]:
    if refresh or any(not (folder / f"{series_id}.csv").exists() for series_id in FED_SOURCES):
        write_macro_cache(fetch_macro_series(), folder)
    loaded = {}
    for series_id in FED_SOURCES:
        loaded[series_id] = parse_fred_csv((folder / f"{series_id}.csv").read_text(encoding="utf-8"))
    return loaded
