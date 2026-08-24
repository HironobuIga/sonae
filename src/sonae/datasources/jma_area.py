"""JMA area-code resolution.

JMA publishes warnings per *office* (prefecture-level, 6-digit code) with
breakdowns per *class20* area (municipality-level, 7-digit code). This module
maps a 5-digit municipality code (from the GSI reverse geocoder) to those
JMA codes by walking the area hierarchy in the official area master
(https://www.jma.go.jp/bosai/common/const/area.json).

A copy of the area master is bundled so the pipeline works offline; it is
refreshed transparently when the network is available.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from sonae.config import settings
from sonae.datasources.http import fetch_bytes

AREA_MASTER_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
MUNI_MASTER_URL = "https://maps.gsi.go.jp/js/muni.js"

_WEEK = 7 * 24 * 3600


@dataclass
class JmaArea:
    office_code: str  # e.g. "200000" (Nagano Prefecture)
    office_name: str
    class20_code: str  # e.g. "2020111" (Nagano City / Nagano area)
    class20_name: str
    candidates: tuple[str, ...] = ()  # every class20 area under this municipality
    ambiguous: bool = False  # True when the home could not be pinned to one of them


@lru_cache(maxsize=1)
def _area_master() -> dict:
    if settings.offline:
        bundled = settings.resources_dir / "jma_area.json"
        return json.loads(bundled.read_text())
    try:
        return json.loads(fetch_bytes(AREA_MASTER_URL, max_age_seconds=_WEEK))
    except ConnectionError:
        bundled = settings.resources_dir / "jma_area.json"
        return json.loads(bundled.read_text())


@lru_cache(maxsize=1)
def _muni_names() -> dict[str, tuple[str, str]]:
    """muni_code -> (prefecture name, municipality name), from GSI's muni.js."""
    if settings.offline:
        text = (settings.resources_dir / "gsi_muni.js").read_text()
    else:
        try:
            text = fetch_bytes(MUNI_MASTER_URL, max_age_seconds=_WEEK).decode("utf-8", errors="replace")
        except ConnectionError:
            text = (settings.resources_dir / "gsi_muni.js").read_text()
    # Lines look like: GSI.MUNI_ARRAY["20201"] = '20,長野県,20201,長野市';
    table: dict[str, tuple[str, str]] = {}
    for match in re.finditer(r"'(\d+),([^,]+),(\d+),([^']+)'", text):
        _, pref, code, name = match.groups()
        table[code.zfill(5)] = (pref, name.replace("　", ""))
    return table


def muni_name(muni_code: str) -> tuple[str, str]:
    """Return (prefecture, municipality) display names for a 5-digit code."""
    table = _muni_names()
    code = muni_code.zfill(5)
    if code not in table:
        raise KeyError(f"unknown municipality code: {muni_code}")
    return table[code]


def _name_affinity(area_name: str, muni: str, locality: str) -> int:
    """How strongly a class20 area name matches a reverse-geocoded locality.

    Class20 names are municipality-prefixed ('長野市鬼無里戸隠'); strip the
    municipality and compare what is left with the 大字 name of the home
    ('鬼無里日下野' shares three characters with 鬼無里戸隠, none with 長野).
    """
    name = area_name.removeprefix(muni)
    if not name or not locality:
        return 0
    if name in locality or locality in name:
        return len(name)
    common = 0
    for a, b in zip(name, locality, strict=False):
        if a != b:
            break
        common += 1
    return common


def _pick_class20(candidates: list[str], class20s: dict, code5: str, locality: str | None) -> tuple[str, bool]:
    """Choose the class20 area covering this home; returns (code, ambiguous)."""
    if len(candidates) == 1:
        return candidates[0], False
    try:
        muni = muni_name(code5)[1]
    except KeyError:
        muni = ""
    scores = {c: _name_affinity(class20s[c]["name"], muni, locality or "") for c in candidates}
    best = max(scores.values())
    winners = [c for c in candidates if scores[c] == best]
    if best >= 2 and len(winners) == 1:
        return winners[0], False
    # Nothing decides it. Keep the first sub-area as the primary (it is the
    # municipality's core area) but say so: silently watching one half of a
    # split municipality is how a warning misses the home it was issued for.
    return candidates[0], True


def resolve(muni_code: str, locality: str | None = None) -> JmaArea:
    """Map a 5-digit municipality code to its JMA office and class20 area.

    Some municipalities are split across several class20 areas (Nagano City is
    長野市長野 + 長野市鬼無里戸隠). `locality` — the 大字 name from the GSI
    reverse geocoder — decides which one covers the home. When it cannot,
    `ambiguous` is set and every `candidates` code is reported so callers can
    watch them all instead of guessing.
    """
    area = _area_master()
    class20s = area["class20s"]
    code5 = muni_code.zfill(5)

    candidates = sorted(c for c in class20s if c.startswith(code5))
    if not candidates:
        raise KeyError(f"no JMA class20 area found for municipality {muni_code}")
    class20_code, ambiguous = _pick_class20(candidates, class20s, code5, locality)
    class20 = class20s[class20_code]

    # Walk parents: class20 -> class15 -> class10 -> office
    parent = class20["parent"]
    for layer in ("class15s", "class10s"):
        node = area[layer].get(parent)
        if node is None:
            break
        parent = node["parent"]
    office = area["offices"].get(parent)
    if office is None:
        raise KeyError(f"could not resolve JMA office for municipality {muni_code}")

    return JmaArea(
        office_code=parent,
        office_name=office["name"],
        class20_code=class20_code,
        class20_name=class20["name"],
        candidates=tuple(candidates),
        ambiguous=ambiguous,
    )
