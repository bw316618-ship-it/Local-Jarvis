"""brain/session.py's JarvisSession drains tools/map_hud.py's shared,
process-wide _MAP_ACTIONS queue for every handle_message() call, on
every surface (CLI console, HUD chat, any connected device) -- not
just ui/hud_server.py's own handlers, which used to be the only
drainers.

Regression coverage for the "map search only works once / results
don't clear" bug: a map-producing tool call (find_nearby_place,
clear_map_markers, focus_map_marker) made from a surface that never
drained (CLI, a non-HUD device) used to leak its action into the
queue forever, waiting for some later, unrelated drain (the HUD's
search box, or another device's turn) to scoop it up and misattribute
it. Every JarvisSession.handle_message() call now drains under
MAP_ACTIONS_LOCK regardless of whether a hud= was even supplied, so
nothing can leak, and broadcasts what it drained to its own hud (if
any) via a broadcast_map_actions() method that hud objects implement.
"""

from unittest.mock import MagicMock

from brain.session import JarvisSession
from tools.map_hud import _queue_action, drain_map_actions


def setup_function(_):
    # The queue is module-level/global -- drain any leftovers from an
    # earlier test so they can't be mistaken for this test's own output.
    drain_map_actions()


def make_fake_jarvis(reply="ok", side_effect=None):
    jarvis = MagicMock()
    if side_effect is not None:
        jarvis.chat.side_effect = side_effect
    else:
        jarvis.chat.return_value = reply
    return jarvis


def test_map_action_produced_during_chat_is_forwarded_to_hud():
    def fake_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("set_markers", markers=[{"name": "Cafe"}])
        return "found it"

    jarvis = make_fake_jarvis(side_effect=fake_chat)
    hud = MagicMock()

    session = JarvisSession(jarvis, hud=hud)
    session.handle_message("coffee near me")

    hud.broadcast_map_actions.assert_called_once()
    (forwarded,), _ = hud.broadcast_map_actions.call_args
    assert forwarded == [{"action": "set_markers", "markers": [{"name": "Cafe"}]}]

    # And the shared queue is left clean for the next caller.
    assert drain_map_actions() == []


def test_no_map_actions_means_no_broadcast_call():
    jarvis = make_fake_jarvis(reply="no maps involved")
    hud = MagicMock()

    session = JarvisSession(jarvis, hud=hud)
    session.handle_message("what's 2+2")

    hud.broadcast_map_actions.assert_not_called()


def test_console_only_session_still_drains_so_nothing_leaks_to_the_next_caller():
    """This is the actual regression: main.py's CLI session is built
    with hud=None-ish behavior in the old code path (or, in the real
    app, hud=hud but nothing ever drained on that call). Either way, a
    map-producing tool call made from a session with no hud to forward
    to must not leave its action sitting in the queue for some later,
    unrelated HUD interaction to pick up."""

    def fake_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("clear_markers", category="")
        return "cleared"

    jarvis = make_fake_jarvis(side_effect=fake_chat)

    session = JarvisSession(jarvis, hud=None)
    session.handle_message("clear the map")

    # No hud to forward to, but the queue must still be empty afterward --
    # this is what prevents contamination of the next, unrelated drain.
    assert drain_map_actions() == []


def test_hud_without_broadcast_map_actions_does_not_crash():
    """A test double or older adapter that hasn't implemented the new
    method must not break the turn -- draining still happens either
    way, so nothing leaks even if forwarding silently no-ops."""

    def fake_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("focus_marker", latitude=1.0, longitude=2.0)
        return "ok"

    jarvis = make_fake_jarvis(side_effect=fake_chat)

    class BareHud:
        def set_state(self, *a, **k):
            pass

    session = JarvisSession(jarvis, hud=BareHud())
    reply = session.handle_message("focus there")

    assert reply == "ok"
    assert drain_map_actions() == []


def test_actions_queued_before_an_exception_are_still_drained_not_leaked():
    def fake_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("set_markers", markers=[{"name": "Half-done search"}])
        raise RuntimeError("model blew up mid-turn")

    jarvis = make_fake_jarvis(side_effect=fake_chat)
    hud = MagicMock()

    session = JarvisSession(jarvis, hud=hud)

    try:
        session.handle_message("search for something")
    except RuntimeError:
        pass

    # The failed turn's partial action isn't broadcast (there's no
    # sensible result to show), but it must not sit in the queue either.
    assert drain_map_actions() == []


def test_leaked_action_from_a_non_hud_surface_no_longer_contaminates_a_later_hud_turn():
    """End-to-end shape of the original bug report: a CLI/non-HUD turn
    produces a map action, then later a real HUD turn (with its own,
    unrelated map action) must broadcast only its own marker -- not
    the earlier leftover too."""

    def cli_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("set_markers", markers=[{"name": "Old CLI result"}])
        return "cli done"

    cli_jarvis = make_fake_jarvis(side_effect=cli_chat)
    # Old, buggy behavior: a console-only JarvisSession that never
    # drained would leave this in the queue. Here we exercise the
    # fixed behavior, so nothing should be left over --
    JarvisSession(cli_jarvis, hud=None).handle_message("cli turn")

    def hud_chat(text, on_step=None, on_sentence=None, map_context=None):
        _queue_action("set_markers", markers=[{"name": "New HUD result"}])
        return "hud done"

    hud_jarvis = make_fake_jarvis(side_effect=hud_chat)
    hud = MagicMock()
    JarvisSession(hud_jarvis, hud=hud).handle_message("hud turn")

    (forwarded,), _ = hud.broadcast_map_actions.call_args
    assert forwarded == [{"action": "set_markers", "markers": [{"name": "New HUD result"}]}]
