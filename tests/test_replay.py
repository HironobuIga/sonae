from datetime import datetime
from pathlib import Path

from sonae.datasources.replay import ReplayClock, load_scenario

SCENARIO = Path(__file__).parents[1] / "scenarios" / "hagibis_2019_nagano.json"


def test_scenario_loads_sorted():
    s = load_scenario(SCENARIO)
    assert s.scenario_id == "hagibis-2019-nagano"
    times = [e.ts for e in s.events]
    assert times == sorted(times)
    assert all(e.source.url.startswith("https://") for e in s.events)
    # The two anchor facts of the demo narrative must be present.
    titles = " / ".join(e.title for e in s.events)
    assert "大雨特別警報" in titles
    assert "HOYASU" in titles


def test_clock_advances_by_moment():
    clock = ReplayClock(load_scenario(SCENARIO))
    seen = 0
    moments = 0
    while not clock.exhausted:
        batch = clock.advance()
        assert batch, "advance must release at least one event"
        assert len({e.ts for e in batch}) == 1, "a moment shares one timestamp"
        seen += len(batch)
        moments += 1
    assert seen == len(clock.scenario.events)
    assert moments >= 10
    assert clock.advance() == []


def test_peek_moment_does_not_move_the_cursor():
    """The web step endpoint peeks, processes, then advances — a failed cycle
    must leave the moment pending instead of skipping its events."""
    clock = ReplayClock(load_scenario(SCENARIO))
    peeked = clock.peek_moment()
    assert peeked and clock.now is None
    assert clock.peek_moment() == peeked
    assert clock.advance() == peeked
    assert clock.peek_moment() != peeked


def test_clock_advance_until():
    clock = ReplayClock(load_scenario(SCENARIO))
    cutoff = datetime.fromisoformat("2019-10-12T18:00:00+09:00")
    batch = clock.advance(until=cutoff)
    assert all(e.ts <= cutoff for e in batch)
    assert clock.peek_next().ts > cutoff
