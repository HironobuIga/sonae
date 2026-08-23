"""Point-in-hazard lookup against the national hazard-map tile service.

The MLIT/GSI "disaportal" publishes every municipality's statutory hazard
maps as XYZ raster tiles (https://disaportal.gsi.go.jp, open data). There is
no point-query API, so Sonae samples the tile pixel under the home's
coordinates and decodes the official legend colors. Legend colors were
verified empirically against the July 2020 Kuma River flood area.

Layers used:
- 01_flood_l2_shinsuishin_data      flood inundation, largest-scale scenario (想定最大規模)
- 03_hightide_l2_shinsuishin_data   storm-surge inundation
- 04_tsunami_newlegend_data         tsunami inundation
- 05_dosekiryukeikaikuiki           debris-flow warning zones
- 05_kyukeishakeikaikuiki           steep-slope failure warning zones
- 05_jisuberikeikaikuiki            landslide warning zones
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image

from sonae.datasources.http import fetch_bytes
from sonae.schemas import HazardType, Source

TILE_URL = "https://disaportaldata.gsi.go.jp/raster/{layer}/{z}/{x}/{y}.png"
PORTAL_URL = "https://disaportal.gsi.go.jp/"

# Official inundation-depth legend (RGB -> depth range).
DEPTH_LEGEND: dict[tuple[int, int, int], tuple[str, str, float]] = {
    # rgb: (label_en, label_ja, representative depth in meters)
    (247, 245, 169): ("under 0.5 m", "0.5m未満", 0.3),
    (255, 216, 192): ("0.5–3 m", "0.5〜3m", 1.5),
    (255, 183, 183): ("3–5 m", "3〜5m", 4.0),
    (255, 145, 145): ("5–10 m", "5〜10m", 7.0),
    (242, 133, 201): ("10–20 m", "10〜20m", 15.0),
    (220, 122, 220): ("over 20 m", "20m以上", 25.0),
}

DEPTH_LAYERS: dict[HazardType, str] = {
    HazardType.flood: "01_flood_l2_shinsuishin_data",
    HazardType.storm_surge: "03_hightide_l2_shinsuishin_data",
    HazardType.tsunami: "04_tsunami_newlegend_data",
}

LANDSLIDE_LAYERS = {
    "debris flow (土石流)": "05_dosekiryukeikaikuiki",
    "steep slope failure (急傾斜地)": "05_kyukeishakeikaikuiki",
    "landslide (地滑り)": "05_jisuberikeikaikuiki",
}

_ZOOMS = (16, 15, 14, 13)  # try finest first; some municipalities only publish coarse tiles


@dataclass
class DepthHit:
    label_en: str
    label_ja: str
    representative_m: float
    at_center: bool  # True if the home pixel itself is inside; False if only nearby (<~50 m)


def _tile_xy(lat: float, lon: float, z: int) -> tuple[int, int, int, int]:
    """Return (tile_x, tile_y, pixel_x, pixel_y) for Web Mercator XYZ tiles."""
    n = 2**z
    fx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    fy = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    x, y = int(fx), int(fy)
    px = int((fx - x) * 256)
    py = int((fy - y) * 256)
    return x, y, px, py


def _fetch_tile(layer: str, z: int, x: int, y: int) -> Image.Image | None:
    url = TILE_URL.format(layer=layer, z=z, x=x, y=y)
    try:
        raw = fetch_bytes(url, max_age_seconds=30 * 24 * 3600, retries=2)
    except ConnectionError:
        return None
    try:
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except OSError:
        return None  # server returns HTML error pages for empty areas


def _sample(layer: str, lat: float, lon: float, window: int = 9) -> tuple[tuple[int, int, int] | None, bool]:
    """Return (dominant nearby legend color, center_hit) sampled around the point.

    window=9 at z=16 spans roughly +/-20 m — tolerant of geocoding offsets
    while never reaching across a whole neighborhood.
    """
    for z in _ZOOMS:
        x, y, px, py = _tile_xy(lat, lon, z)
        img = _fetch_tile(layer, z, x, y)
        if img is None:
            continue
        pixels = img.load()
        center = pixels[px, py]
        center_hit = center[3] > 0
        best: tuple[int, int, int] | None = (center[0], center[1], center[2]) if center_hit else None
        best_depth = -1.0
        if best and best in DEPTH_LEGEND:
            best_depth = DEPTH_LEGEND[best][2]
        half = window // 2
        for dy in range(-half, half + 1):
            for dx in range(-half, half + 1):
                sx, sy = px + dx, py + dy
                if not (0 <= sx < 256 and 0 <= sy < 256):
                    continue
                r, g, b, a = pixels[sx, sy]
                if a == 0:
                    continue
                depth = DEPTH_LEGEND.get((r, g, b), (None, None, 0.0))[2]
                if depth > best_depth:
                    best, best_depth = (r, g, b), depth
        return best, center_hit
    return None, False


def lookup_depth(hazard: HazardType, lat: float, lon: float) -> DepthHit | None:
    """Inundation depth at a point for flood / storm surge / tsunami layers."""
    layer = DEPTH_LAYERS[hazard]
    color, center_hit = _sample(layer, lat, lon)
    if color is None:
        return None
    if color in DEPTH_LEGEND:
        en, ja, meters = DEPTH_LEGEND[color]
    else:
        en, ja, meters = ("inundation zone (depth class unknown)", "浸水想定区域", 0.5)
    return DepthHit(label_en=en, label_ja=ja, representative_m=meters, at_center=center_hit)


def lookup_landslide(lat: float, lon: float) -> list[str]:
    """Names of landslide-type designated zones at/near the point."""
    hits: list[str] = []
    for name, layer in LANDSLIDE_LAYERS.items():
        color, center_hit = _sample(layer, lat, lon, window=5)
        if color is not None:
            where = "at this location" if center_hit else "within ~20 m"
            hits.append(f"{name} designated zone {where}")
    return hits


def hazard_source() -> Source:
    return Source(
        name="MLIT/GSI national hazard map portal (重ねるハザードマップ)",
        url=PORTAL_URL,
        note="statutory hazard-map raster tiles; legend per MLIT specification",
    )
