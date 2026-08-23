# There is no API for "how deep will the water be at my house" — so we made one from map tiles

*Draft for builder.aws — article 2 of 3 for the Agents for Humans Hackathon (Sonae project)*

Japan has some of the best disaster open data in the world. The Japan Meteorological Agency
publishes warning feeds as keyless JSON. The Geospatial Information Authority (GSI) publishes
every municipality's designated evacuation sites as a nationwide CSV — with per-hazard suitability
flags. And the national hazard-map portal publishes the statutory flood, tsunami, storm-surge and
landslide maps for the entire country.

But ask the obvious agent question — *"what is the expected flood depth at this exact address?"* —
and you hit a wall: the hazard maps ship as XYZ raster tiles for human eyes, not as a queryable
API. No endpoint takes a coordinate and returns a depth.

For our hackathon project Sonae (an agent team that builds family evacuation plans), that question
is the foundation of everything. Here's how we turned a PNG tile server into a Strands tool an LLM
can call — and how we validated it against a real disaster.

## Web-Mercator arithmetic, then one pixel

Slippy-map tiles address the world in a simple scheme: at zoom `z`, the world is a 2^z × 2^z grid
of 256-pixel tiles. Converting a coordinate to (tile, pixel) is a few lines:

```python
def _tile_xy(lat, lon, z):
    n = 2**z
    fx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    fy = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    x, y = int(fx), int(fy)
    return x, y, int((fx - x) * 256), int((fy - y) * 256)
```

Fetch `https://disaportaldata.gsi.go.jp/raster/01_flood_l2_shinsuishin_data/{z}/{x}/{y}.png`,
read the pixel — and decode its color against the official legend, which is standardized across
the country by MLIT specification:

```python
DEPTH_LEGEND = {
    (247, 245, 169): ("under 0.5 m", 0.3),
    (255, 216, 192): ("0.5–3 m",    1.5),
    (255, 183, 183): ("3–5 m",      4.0),
    (255, 145, 145): ("5–10 m",     7.0),
    (242, 133, 201): ("10–20 m",   15.0),
    (220, 122, 220): ("over 20 m", 25.0),
}
```

A transparent pixel means "outside the inundation zone." The same trick works for storm surge,
tsunami, and the three landslide-zone layers (there, any non-transparent pixel means "inside a
designated warning zone").

Three robustness details worth copying:

1. **Sample a window, not a point.** Geocoding an address has meters of error. We take the worst
   (deepest) legend color in a small window around the target pixel — at zoom 16 that's roughly
   ±20 m, tolerant of geocoder offsets without reaching across a neighborhood.
2. **Fall through zoom levels.** Not every municipality publishes tiles at the finest zoom; we try
   16 → 13 and use the first tile that exists.
3. **Cache aggressively.** Hazard maps change on the timescale of years; a month-long tile cache
   makes the agent loop fast and gentle on a public service.

## Validation: the 2020 Kuma River flood

How do you trust a color-decoder? Point it somewhere reality has already graded. We sampled the
tiles over Hitoyoshi, Kumamoto — inundated by the July 2020 Kuma River flood — and the decoder
returned 5–10 m depth classes exactly where post-event surveys reported them. Then, for our demo
household by the Chikuma River in Nagano (beside the levee that failed during Typhoon Hagibis in
2019), it returned 10–20 m: consistent with the district that flooded to its rooftops that night.

## Wrapping it as a Strands tool

The Strands Agents SDK makes the last step almost free — a decorated function whose docstring and
type hints become the tool contract:

```python
@tool
def assess_hazards_at_point(lat: float, lon: float) -> dict:
    """Read the statutory hazard maps at a coordinate: flood / storm-surge /
    tsunami inundation depth and landslide designated zones."""
    ...
    return {"hazards": ..., "landslide_zones": ..., "sources": [...]}
```

Every tool result carries a `sources` field naming the portal and its legend specification. Our
verifier agent — which re-derives every claim in a generated plan with these same tools — quotes
those results as evidence, so "expected depth 10–20 m" in a family's evacuation plan is traceable
to a specific statutory dataset, not to a model's vibes.

One unexpected payoff: the evacuation-site registry's per-hazard flags meant our agent noticed
that the site nearest our demo home — 600 meters away — is designated for earthquakes but **not**
for floods. The correct flood destination is 2.6 km in the other direction. That single fact,
surfaced automatically, is the kind of thing that decides outcomes at 2 a.m. — and most families
have never checked it.

## Takeaways

- "No API" often means "an API you haven't decoded yet." Raster legends are data.
- Validate decoders against ground truth reality has already provided.
- Ship provenance with every tool result; downstream verifier agents need evidence to quote.

*Sonae is open source (MIT): Strands Agents SDK + Amazon Bedrock + Japan's government open data.*
