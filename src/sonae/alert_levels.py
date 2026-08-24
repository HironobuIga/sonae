"""Deterministic Cabinet Office alert-level equivalences.

The Sentinel is a language model. It can fill a `level` field with 5 while its
own reasoning correctly concludes "no Level 5 signal is present" — we have that
exact failure in the flight recorder. These tables let the watch pipeline clamp
an activation to the highest level the official event text actually supports,
so a model slip cannot escalate a family past what the government said.

The clamp only ever lowers a level, and only when at least one signal is
recognised. An unrecognised event is left to the Sentinel's judgment: a new
wording must never be able to silence an alert.

大雨特別警報 sits at 4 here on purpose. It is formally a Level-5-equivalent
rainfall signal, but Level 5 means "protect yourself where you are", so the
family's approved plan names it in the Level 4 "complete the evacuation" step.
See PLANNER/SENTINEL in agents/prompts.py.
"""

from __future__ import annotations

# Longest strings first: 氾濫危険情報 must win before a bare 警報 pattern.
SIGNAL_LEVELS: tuple[tuple[str, int], ...] = (
    # Level 5 — inundation is actually occurring
    ("氾濫発生情報", 5),
    ("緊急安全確保", 5),
    ("災害発生情報", 5),
    ("flooding occurring", 5),
    ("disaster occurring", 5),
    # Level 4 — everyone leaves, while leaving is still possible
    ("氾濫危険情報", 4),
    ("大雨特別警報", 4),
    ("特別警報", 4),
    ("避難指示", 4),
    ("避難勧告", 4),
    ("flood danger", 4),
    ("emergency heavy rain warning", 4),
    ("evacuation order", 4),
    ("evacuation advisory", 4),
    # Level 3 — elderly and mobility-limited start moving
    ("氾濫警戒情報", 3),
    ("高齢者等避難", 3),
    ("避難準備", 3),
    ("大雨警報", 3),
    ("洪水警報", 3),
    ("flood warning", 3),
    ("elderly evacuation", 3),
    # Level 2 — check the route, ready the bag
    ("氾濫注意情報", 2),
    ("大雨注意報", 2),
    ("洪水注意報", 2),
    ("flood advisory", 2),
    # Level 1 — stay informed
    ("早期注意情報", 1),
)


def max_supported_level(texts: list[str]) -> int | None:
    """Highest alert level the given official text positively supports.

    Returns None when no known signal appears, meaning "we cannot judge this
    from the wording" — callers must then trust the Sentinel rather than
    suppress the event.
    """
    best: int | None = None
    for text in texts:
        haystack = text.lower()
        for needle, level in SIGNAL_LEVELS:
            if needle in text or needle.lower() in haystack:
                best = level if best is None else max(best, level)
    return best
