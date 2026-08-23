"""Geocoding via GSI (Geospatial Information Authority of Japan).

- Forward geocoding: https://msearch.gsi.go.jp/address-search/AddressSearch
- Reverse geocoding (point -> municipality code): mreversegeocoder LonLatToAddress

Both are public, keyless endpoints operated by the Japanese government.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from sonae.datasources.http import fetch_json

FORWARD_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q={query}"
REVERSE_URL = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress?lat={lat}&lon={lon}"

# One day: addresses don't move.
_CACHE_AGE = 24 * 3600


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    matched_name: str
    muni_code: str  # 5-digit municipality code (e.g. "20201")
    locality: str | None  # 大字/町丁目 name from the reverse geocoder


class GeocodeError(RuntimeError):
    pass


def geocode(address: str) -> GeocodeResult:
    """Resolve a Japanese address string to coordinates + municipality code."""
    results = fetch_json(FORWARD_URL.format(query=quote(address)), max_age_seconds=_CACHE_AGE)
    if not results:
        raise GeocodeError(f"GSI address search returned no results for: {address!r}")
    top = results[0]
    lon, lat = top["geometry"]["coordinates"]
    matched = top.get("properties", {}).get("title", address)

    rev = fetch_json(REVERSE_URL.format(lat=lat, lon=lon), max_age_seconds=_CACHE_AGE)
    muni = rev.get("results", {}) or {}
    muni_code = muni.get("muniCd")
    if not muni_code:
        raise GeocodeError(f"reverse geocoder returned no municipality for {lat},{lon} ({address!r})")
    return GeocodeResult(
        lat=float(lat),
        lon=float(lon),
        matched_name=matched,
        muni_code=str(muni_code),
        locality=muni.get("lv01Nm"),
    )
