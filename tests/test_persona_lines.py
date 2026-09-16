import brain.persona_lines as persona_lines


EXPECTED_EVENTS = [
    "mute",
    "unmute",
    "end_session",
    "enter_companion",
    "exit_companion",
    "enter_creative",
    "exit_creative",
    "enter_coding",
    "exit_coding",
    "enter_heavy_brain",
    "exit_heavy_brain",
]


def test_every_expected_event_has_a_pool():
    for event in EXPECTED_EVENTS:
        assert event in persona_lines.POOLS


def test_every_pool_has_more_than_one_line():
    """A pool of exactly one line isn't 'varied' -- it's the same old
    static string with extra steps."""
    for event, pool in persona_lines.POOLS.items():
        assert len(pool) >= 2, f"{event} pool needs at least 2 lines"


def test_pick_returns_a_line_from_the_right_pool():
    for event in EXPECTED_EVENTS:
        assert persona_lines.pick(event) in persona_lines.POOLS[event]


def test_pick_of_unknown_event_falls_back_to_the_event_name():
    """A missing pool shouldn't be able to break the tool call that
    wanted a phrase from it."""
    assert persona_lines.pick("nonexistent_event") == "nonexistent_event"


def test_pick_varies_across_many_calls(monkeypatch):
    """Not a strict guarantee (it's random), but with a pool of 3 and
    200 draws, seeing only one distinct value would mean pick() is
    broken (e.g. always returning pool[0])."""
    seen = {persona_lines.pick("mute") for _ in range(200)}
    assert len(seen) > 1
