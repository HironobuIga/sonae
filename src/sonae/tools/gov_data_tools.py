"""Strands tools exposing Japan's government open data to Sonae's agents.

Each tool returns plain dicts with a `sources` field so agents can cite —
and the Verifier can audit — every factual claim against official data.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from sonae.datasources import gsi_geocode, gsi_hazard, gsi_shelters, jma, jma_area
from sonae.schemas import HazardType


@tool
def geocode_address(address: str) -> dict[str, Any]:
    """Resolve a Japanese address to coordinates, municipality, and JMA warning areas.

    Args:
        address: Japanese address string, e.g. '長野県長野市穂保'
    """
    g = gsi_geocode.geocode(address)
    pref, muni = jma_area.muni_name(g.muni_code)
    area = jma_area.resolve(g.muni_code, locality=g.locality)
    return {
        "lat": g.lat,
        "lon": g.lon,
        "matched_name": g.matched_name,
        "locality": g.locality,
        "muni_code": g.muni_code,
        "prefecture": pref,
        "municipality": muni,
        "jma_office_code": area.office_code,
        "jma_office_name": area.office_name,
        "jma_class20_code": area.class20_code,
        "jma_class20_name": area.class20_name,
        # Set when the municipality splits into several JMA areas and the
        # locality did not pin the home to one of them — all are then watched.
        "jma_class20_ambiguous": area.ambiguous,
        "jma_class20_candidates": list(area.candidates),
        "sources": [
            {"name": "GSI address search / reverse geocoder", "url": "https://msearch.gsi.go.jp/"}
        ],
    }


@tool
def assess_hazards_at_point(lat: float, lon: float) -> dict[str, Any]:
    """Read the statutory hazard maps at a coordinate: flood / storm-surge / tsunami
    inundation depth and landslide designated zones.

    Args:
        lat: latitude (WGS84)
        lon: longitude (WGS84)
    """
    result: dict[str, Any] = {"hazards": {}, "landslide_zones": [], "sources": []}
    for hazard in (HazardType.flood, HazardType.storm_surge, HazardType.tsunami):
        hit = gsi_hazard.lookup_depth(hazard, lat, lon)
        if hit is None:
            result["hazards"][hazard.value] = {"at_risk": False}
        else:
            result["hazards"][hazard.value] = {
                "at_risk": True,
                "expected_depth": hit.label_en,
                "expected_depth_ja": hit.label_ja,
                "representative_depth_m": hit.representative_m,
                "at_exact_point": hit.at_center,
            }
    result["landslide_zones"] = gsi_hazard.lookup_landslide(lat, lon)
    src = gsi_hazard.hazard_source()
    result["sources"] = [{"name": src.name, "url": src.url, "note": src.note}]
    result["note"] = (
        "Depth classes come from the largest-scale statutory inundation scenario "
        "(想定最大規模). 'at_exact_point'=false means the zone is within ~20 m."
    )
    return result


@tool
def find_evacuation_sites(
    lat: float,
    lon: float,
    prefecture: str,
    municipality: str,
    hazard: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Find the nearest designated emergency evacuation sites suitable for a hazard.

    Args:
        lat: home latitude
        lon: home longitude
        prefecture: e.g. '長野県'
        municipality: e.g. '長野市'
        hazard: one of flood, landslide, storm_surge, earthquake, tsunami,
            large_fire, inland_flood, volcano
        limit: max number of sites to return
    """
    sites = gsi_shelters.nearest_shelters(
        lat, lon, prefecture + municipality, hazard=HazardType(hazard), limit=limit
    )
    return {
        "sites": [
            {
                "name": s.name,
                "address": s.address,
                "lat": s.lat,
                "lon": s.lon,
                "distance_km": s.distance_km,
                "suitable_for": [h.value for h in s.suitable_for],
                "also_mid_term_shelter": s.is_designated_shelter,
            }
            for s in sites
        ],
        "caveat": gsi_shelters.DATA_CAVEAT,
        "sources": [{"name": "GSI designated evacuation site data", "url": "https://hinanmap.gsi.go.jp/"}],
    }


@tool
def get_active_warnings(jma_office_code: str, jma_class20_code: str) -> dict[str, Any]:
    """Fetch currently active JMA warnings/advisories for a municipality's warning area.

    Args:
        jma_office_code: prefecture-level JMA code, e.g. '200000'
        jma_class20_code: municipality-level JMA code, e.g. '2020111'
    """
    events = jma.fetch_active_warnings(jma_office_code, jma_class20_code)
    return {
        "active": [
            {"title": e.title, "body": e.body, "reported_at": e.ts.isoformat(), "source_url": e.source.url}
            for e in events
        ],
        "count": len(events),
    }


@tool
def get_forecast(jma_office_code: str) -> dict[str, Any]:
    """Fetch the JMA 3-day forecast summary for a prefecture office area.

    Args:
        jma_office_code: prefecture-level JMA code, e.g. '200000'
    """
    e = jma.fetch_forecast_summary(jma_office_code)
    return {"title": e.title, "body": e.body, "source_url": e.source.url}
