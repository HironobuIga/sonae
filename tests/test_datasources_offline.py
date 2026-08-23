"""Offline tests against bundled government-data resources."""

from sonae.datasources import gsi_shelters, jma_area
from sonae.schemas import HazardType

HOYASU = (36.684467, 138.271759)


def test_muni_name_offline(offline):
    assert jma_area.muni_name("20201") == ("長野県", "長野市")


def test_jma_area_resolution_offline(offline):
    area = jma_area.resolve("20201")
    assert area.office_code == "200000"
    assert area.class20_code.startswith("20201")
    assert "長野" in area.office_name


def test_nearest_flood_shelters_offline(offline):
    gsi_shelters._evac_sites.cache_clear()
    gsi_shelters._mid_term_shelters.cache_clear()
    sites = gsi_shelters.nearest_shelters(*HOYASU, "長野県長野市", hazard=HazardType.flood, limit=5)
    assert sites, "bundled sample must contain Nagano City flood sites"
    assert all(HazardType.flood in s.suitable_for for s in sites)
    assert sites[0].distance_km <= sites[-1].distance_km
    assert sites[0].distance_km < 5.0


def test_hazard_filter_differs_offline(offline):
    gsi_shelters._evac_sites.cache_clear()
    gsi_shelters._mid_term_shelters.cache_clear()
    flood = {s.name for s in gsi_shelters.nearest_shelters(*HOYASU, "長野県長野市", hazard=HazardType.flood, limit=30)}
    quake = {s.name for s in gsi_shelters.nearest_shelters(*HOYASU, "長野県長野市", hazard=HazardType.earthquake, limit=30)}
    assert flood and quake
    assert flood != quake, "flood-safe and earthquake-safe site sets should differ"
