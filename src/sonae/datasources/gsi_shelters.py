"""Designated emergency evacuation sites (指定緊急避難場所) nationwide.

GSI publishes the nationwide merged CSV of municipality-registered
evacuation sites, including per-hazard suitability flags mandated by the
Disaster Countermeasures Basic Act, Art. 49-4.

Download site (consent-gated UI, files themselves are direct):
https://hinanmap.gsi.go.jp/

Per GSI's terms of use we must relay: the data may lag municipal updates —
final confirmation belongs to the municipality. Sonae surfaces this caveat
with every shelter recommendation.
"""

from __future__ import annotations

import csv
import io
import math
from functools import lru_cache
from pathlib import Path

from sonae.config import settings
from sonae.datasources.http import fetch_bytes
from sonae.schemas import HazardType, Shelter, Source

# mergeFromCity_2 = 指定緊急避難場所 (emergency evacuation sites, per-hazard flags)
# mergeFromCity_1 = 指定避難所 (mid-term shelters)
EVAC_SITES_URL = "https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv/mergeFromCity_2.csv"
SHELTERS_URL = "https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/csv/mergeFromCity_1.csv"

_MONTH = 30 * 24 * 3600

DATA_CAVEAT = (
    "Shelter data is registered by municipalities and may not reflect the latest "
    "designations; confirm with the municipality for critical decisions (GSI terms of use)."
)

_HAZARD_COLUMNS: list[tuple[str, HazardType]] = [
    ("洪水", HazardType.flood),
    ("崖崩れ、土石流及び地滑り", HazardType.landslide),
    ("高潮", HazardType.storm_surge),
    ("地震", HazardType.earthquake),
    ("津波", HazardType.tsunami),
    ("大規模な火事", HazardType.large_fire),
    ("内水氾濫", HazardType.inland_flood),
    ("火山現象", HazardType.volcano),
]


def _load_csv(url: str, bundled_name: str) -> list[dict[str, str]]:
    if settings.offline:
        raw = (settings.resources_dir / bundled_name).read_bytes()
    else:
        try:
            raw = fetch_bytes(url, max_age_seconds=_MONTH)
        except ConnectionError:
            bundled = settings.resources_dir / bundled_name
            if not bundled.exists():
                raise
            raw = bundled.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


@lru_cache(maxsize=1)
def _evac_sites() -> list[dict[str, str]]:
    return _load_csv(EVAC_SITES_URL, "sample_evac_sites.csv")


@lru_cache(maxsize=1)
def _mid_term_shelters() -> set[tuple[str, str]]:
    """(muni+facility name) pairs that are also designated mid-term shelters."""
    rows = _load_csv(SHELTERS_URL, "sample_shelters.csv")
    return {(r.get("都道府県名及び市町村名", ""), r.get("施設・場所名", "")) for r in rows}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def shelter_source() -> Source:
    return Source(
        name="GSI designated emergency evacuation site data (指定緊急避難場所データ)",
        url="https://hinanmap.gsi.go.jp/",
        note=DATA_CAVEAT,
    )


def nearest_shelters(
    lat: float,
    lon: float,
    muni_and_pref: str,
    *,
    hazard: HazardType | None = None,
    limit: int = 5,
) -> list[Shelter]:
    """Nearest designated evacuation sites for a home.

    muni_and_pref: e.g. '長野県長野市' — matches the CSV's combined name column.
    hazard: if given, only sites designated safe for that hazard type.
    """
    mid_term = _mid_term_shelters()
    results: list[Shelter] = []
    for row in _evac_sites():
        if row.get("都道府県名及び市町村名", "") != muni_and_pref:
            continue
        try:
            s_lat = float(row["緯度"])
            s_lon = float(row["経度"])
        except (KeyError, ValueError):
            continue
        suitable = [
            haz for col, haz in _HAZARD_COLUMNS if row.get(col, "").strip() not in ("", "0")
        ]
        if hazard is not None and hazard not in suitable:
            continue
        name = row.get("施設・場所名", "(unnamed)")
        results.append(
            Shelter(
                name=name,
                address=row.get("住所", ""),
                lat=s_lat,
                lon=s_lon,
                distance_km=round(haversine_km(lat, lon, s_lat, s_lon), 2),
                suitable_for=suitable,
                is_designated_shelter=(muni_and_pref, name) in mid_term,
                source=shelter_source(),
            )
        )
    results.sort(key=lambda s: s.distance_km)
    return results[:limit]


def export_sample(muni_and_pref_list: list[str], out_dir: Path) -> None:
    """Write bundled sample extracts for offline demo/test use."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for url, bundled_name in ((EVAC_SITES_URL, "sample_evac_sites.csv"), (SHELTERS_URL, "sample_shelters.csv")):
        raw = fetch_bytes(url, max_age_seconds=_MONTH).decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(raw)))
        header, body = rows[0], rows[1:]
        muni_idx = header.index("都道府県名及び市町村名")
        keep = [r for r in body if len(r) > muni_idx and r[muni_idx] in muni_and_pref_list]
        with open(out_dir / bundled_name, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(keep)
