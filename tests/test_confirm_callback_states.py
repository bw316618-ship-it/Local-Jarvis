from unittest.mock import MagicMock

from brain.session import make_confirm_callback


def test_hud_confirm_sets_confirming_state_then_resumes_thinking():
    hud = MagicMock()
    hud.request_confirmation.return_value = True

    confirm = make_confirm_callback(hud=hud)
    result = confirm("run_command", {"cmd": "ls"})

    assert result is True
    # confirming (with the tool name as meta) must be set *before* the
    # actual confirmation call, and "thinking" resumed afterward -- not
    # the other way around, and not skipped.
    assert hud.set_state.call_args_list[0].args == ("confirming", {"name": "run_command"})
    assert hud.set_state.call_args_list[-1].args == ("thinking",)
    hud.request_confirmation.assert_called_once_with("run_command", {"cmd": "ls"})


def test_hud_confirm_resumes_thinking_even_when_denied():
    hud = MagicMock()
    hud.request_confirmation.return_value = False

    confirm = make_confirm_callback(hud=hud)
    result = confirm("delete_any_file", {"path": "/tmp/x"})

    assert result is False
    assert hud.set_state.call_args_list[-1].args == ("thinking",)


def test_hud_confirm_resumes_thinking_even_if_request_confirmation_raises():
    hud = MagicMock()
    hud.request_confirmation.side_effect = RuntimeError("socket dropped")

    confirm = make_confirm_callback(hud=hud)

    try:
        confirm("run_command", {"cmd": "ls"})
    except RuntimeError:
        pass

    # The finally-block must still resume "thinking" even though the
    # confirmation call itself blew up -- otherwise the HUD would be
    # stuck showing "confirming" for a request that already failed.
    assert hud.set_state.call_args_list[-1].args == ("thinking",)


def test_hud_confirm_without_set_state_does_not_crash():
    """A test double or an older hud adapter without set_state must not
    break the confirmation flow itself -- that's the part that actually
    gates the tool call."""

    class BareHud:
        def __init__(self):
            self.confirmed_with = None

        def request_confirmation(self, name, arguments):
            self.confirmed_with = (name, arguments)
            return True

    hud = BareHud()
    confirm = make_confirm_callback(hud=hud)

    assert confirm("run_command", {"cmd": "ls"}) is True
    assert hud.confirmed_with == ("run_command", {"cmd": "ls"})


def test_console_confirm_still_works_without_a_hud():
    console = MagicMock()
    console.input.return_value = "y"

    confirm = make_confirm_callback(console=console)

    assert confirm("run_command", {"cmd": "ls"}) is True
    console.print.assert_called_once()


def test_no_surface_fails_closed():
    confirm = make_confirm_callback()
    assert confirm("run_command", {"cmd": "ls"}) is False
