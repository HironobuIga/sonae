"""Offline tests against bundled government-data resources."""

from sonae.datasources import gsi_shelters, jma, jma_area
from sonae.schemas import HazardType

HOYASU = (36.684467, 138.271759)


def test_muni_name_offline(offline):
    assert jma_area.muni_name("20201") == ("長野県", "長野市")


def test_jma_area_resolution_offline(offline):
    area = jma_area.resolve("20201")
    assert area.office_code == "200000"
    assert area.class20_code.startswith("20201")
    assert "長野" in area.office_name
    # Nagano City is split into 長野市長野 / 長野市鬼無里戸隠. With no locality to
    # go on, the split is reported instead of silently guessed.
    assert area.ambiguous is True
    assert set(area.candidates) == {"2020111", "2020112"}


def test_jma_area_locality_picks_the_covering_area(offline):
    kinasa = jma_area.resolve("20201", locality="鬼無里日下野")
    assert kinasa.class20_code == "2020112"
    assert kinasa.ambiguous is False

    core = jma_area.resolve("20201", locality="長野")
    assert core.class20_code == "2020111"
    assert core.ambiguous is False

    # a locality that matches neither area name stays ambiguous: callers watch
    # every candidate rather than half the municipality
    hoyasu = jma_area.resolve("20201", locality="穂保")
    assert hoyasu.ambiguous is True
    assert hoyasu.class20_code == "2020111"
    assert len(hoyasu.candidates) == 2


def test_unknown_warning_code_is_flagged_not_downranked():
    assert jma.describe_warning_code("33")[2] == "emergency"
    name_ja, name_en, kind = jma.describe_warning_code("99")
    assert kind == jma.UNCLASSIFIED
    assert "99" in name_ja and "99" in name_en
    # an unknown code must not quietly become a level-2 advisory
    assert jma._KIND_TO_LEVEL[kind] == 3


def test_active_warnings_filter_all_candidate_areas(monkeypatch):
    payload = {
        "reportDatetime": "2019-10-12T15:00:00+09:00",
        "headlineText": "",
        "areaTypes": [
            {
                "areas": [
                    {"code": "2020111", "warnings": [{"code": "03", "status": "発表"}]},
                    {"code": "2020112", "warnings": [{"code": "99", "status": "発表"}]},
                    {"code": "2020200", "warnings": [{"code": "33", "status": "発表"}]},
                ]
            }
        ],
    }
    monkeypatch.setattr(jma, "fetch_json", lambda url, **kw: payload)

    events = jma.fetch_active_warnings("200000", ["2020111", "2020112"])
    assert {e.area_code for e in events} == {"2020111", "2020112"}
    unknown = next(e for e in events if e.area_code == "2020112")
    assert "UNCLASSIFIED" in unknown.body and "level 3" in unknown.body

    # a single code still narrows to one area (unchanged behavior)
    assert {e.area_code for e in jma.fetch_active_warnings("200000", "2020111")} == {"2020111"}


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
