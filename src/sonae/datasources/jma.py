"""Live JMA (Japan Meteorological Agency) warning and forecast feeds.

Endpoints (public JSON, no key):
- warnings: https://www.jma.go.jp/bosai/warning/data/warning/{office}.json
- forecast: https://www.jma.go.jp/bosai/forecast/data/forecast/{office}.json

JMA does not document these as a formal API, so parsing is defensive and
every event carries the raw source URL as its citation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sonae.datasources.http import fetch_json
from sonae.schemas import FeedEvent, FeedEventKind, Source

WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{office}.json"
FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{office}.json"

# JMA warning/advisory codes -> (name_ja, name_en, kind)
# kind: "emergency" = 特別警報, "warning" = 警報, "advisory" = 注意報
WARNING_CODES: dict[str, tuple[str, str, str]] = {
    "02": ("暴風雪警報", "Snowstorm Warning", "warning"),
    "03": ("大雨警報", "Heavy Rain Warning", "warning"),
    "04": ("洪水警報", "Flood Warning", "warning"),
    "05": ("暴風警報", "Storm Warning", "warning"),
    "06": ("大雪警報", "Heavy Snow Warning", "warning"),
    "07": ("波浪警報", "High Wave Warning", "warning"),
    "08": ("高潮警報", "Storm Surge Warning", "warning"),
    "10": ("大雨注意報", "Heavy Rain Advisory", "advisory"),
    "12": ("大雪注意報", "Heavy Snow Advisory", "advisory"),
    "13": ("風雪注意報", "Snow Gale Advisory", "advisory"),
    "14": ("雷注意報", "Thunderstorm Advisory", "advisory"),
    "15": ("強風注意報", "Gale Advisory", "advisory"),
    "16": ("波浪注意報", "High Wave Advisory", "advisory"),
    "17": ("融雪注意報", "Snowmelt Advisory", "advisory"),
    "18": ("洪水注意報", "Flood Advisory", "advisory"),
    "19": ("高潮注意報", "Storm Surge Advisory", "advisory"),
    "20": ("濃霧注意報", "Dense Fog Advisory", "advisory"),
    "21": ("乾燥注意報", "Dry Air Advisory", "advisory"),
    "22": ("なだれ注意報", "Avalanche Advisory", "advisory"),
    "23": ("低温注意報", "Low Temperature Advisory", "advisory"),
    "24": ("霜注意報", "Frost Advisory", "advisory"),
    "25": ("着氷注意報", "Icing Advisory", "advisory"),
    "26": ("着雪注意報", "Snow Accretion Advisory", "advisory"),
    "32": ("暴風雪特別警報", "Emergency Snowstorm Warning", "emergency"),
    "33": ("大雨特別警報", "Emergency Heavy Rain Warning", "emergency"),
    "35": ("暴風特別警報", "Emergency Storm Warning", "emergency"),
    "36": ("大雪特別警報", "Emergency Heavy Snow Warning", "emergency"),
    "37": ("波浪特別警報", "Emergency High Wave Warning", "emergency"),
    "38": ("高潮特別警報", "Emergency Storm Surge Warning", "emergency"),
}

# Cabinet Office alert-level equivalences for JMA information
# (警戒レベル相当情報). Level 4/5 evacuation orders themselves are issued by
# municipalities, so from JMA feeds alone we can only assert "equivalent" levels.
# "unclassified" is not a JMA category: it is a code this table does not know
# (JMA adds codes). Ranking it as an advisory quietly under-ranked whatever it
# actually was, so it is treated as warning-equivalent and labeled as unknown.
_KIND_TO_LEVEL = {"advisory": 2, "warning": 3, "emergency": 5, "unclassified": 3}

UNCLASSIFIED = "unclassified"


def describe_warning_code(code: str) -> tuple[str, str, str]:
    return WARNING_CODES.get(
        code, (f"未分類コード{code}", f"unclassified JMA code {code}", UNCLASSIFIED)
    )


def fetch_active_warnings(
    office_code: str, class20_code: str | Iterable[str] | None = None
) -> list[FeedEvent]:
    """Return active warnings for an office, narrowed to one or more class20 areas.

    Pass every candidate area when the home's area could not be resolved
    unambiguously (see jma_area.resolve) — filtering to a single guessed area
    is how a household ends up watched under its neighbors' warnings.
    """
    wanted = {class20_code} if isinstance(class20_code, str) else set(class20_code or ())
    url = WARNING_URL.format(office=office_code)
    data = fetch_json(url, max_age_seconds=60)
    reported = _parse_dt(data.get("reportDatetime"))
    headline = (data.get("headlineText") or "").strip()

    events: list[FeedEvent] = []
    for area_type in data.get("areaTypes", []):
        for area in area_type.get("areas", []):
            code = str(area.get("code", ""))
            if wanted and code not in wanted:
                continue
            active = [
                w for w in area.get("warnings", [])
                if w.get("status") not in (None, "解除", "発表警報・注意報はなし")
            ]
            if not active:
                continue
            names = [describe_warning_code(str(w["code"])) for w in active if "code" in w]
            if not names:
                continue
            level = max((_KIND_TO_LEVEL[k] for _, _, k in names), default=2)
            title_ja = "・".join(n for n, _, _ in names)
            title_en = ", ".join(e for _, e, _ in names)
            unknown = [en for _, en, k in names if k == UNCLASSIFIED]
            caveat = (
                f" UNCLASSIFIED: {', '.join(unknown)} — not in Sonae's code table, "
                "treated as warning-equivalent (level 3) pending human confirmation; "
                "the real severity may be higher."
                if unknown
                else ""
            )
            events.append(
                FeedEvent(
                    ts=reported,
                    kind=FeedEventKind.jma_warning,
                    area_code=code,
                    title=f"{title_ja} ({title_en})",
                    body=(
                        f"Active JMA notices for area {code}: {title_en}. "
                        f"Highest equivalence: alert level {level}. Headline: {headline or 'n/a'}"
                        f"{caveat}"
                    ),
                    source=Source(name="JMA warning feed", url=url, retrieved_at=datetime.now(UTC)),
                )
            )
    return events


def fetch_forecast_summary(office_code: str) -> FeedEvent:
    """Compact three-day forecast for the office area (context for the Sentinel)."""
    url = FORECAST_URL.format(office=office_code)
    data = fetch_json(url, max_age_seconds=600)
    lines: list[str] = []
    try:
        series = data[0]["timeSeries"][0]
        times = series.get("timeDefines", [])
        area = series["areas"][0]
        weathers = area.get("weathers", [])
        for t, w in zip(times, weathers, strict=False):
            lines.append(f"{t}: {w}")
        area_name = area.get("area", {}).get("name", "")
    except (KeyError, IndexError, TypeError):
        area_name = ""
        lines.append("forecast structure not recognized; see source URL")
    return FeedEvent(
        ts=datetime.now(UTC),
        kind=FeedEventKind.jma_forecast,
        area_code=office_code,
        area_name=area_name,
        title=f"JMA 3-day forecast ({area_name})",
        body="\n".join(lines),
        source=Source(name="JMA forecast feed", url=url, retrieved_at=datetime.now(UTC)),
    )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC)
