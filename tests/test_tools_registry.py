"""Registry integrity: every tool schema must have a matching function and
vice versa, and the risky/safe split must match what each tool actually does."""

from tools.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS, RISKY_TOOLS


def test_every_schema_has_a_function():
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    func_names = set(TOOL_FUNCTIONS)
    assert schema_names == func_names, (
        f"schemas without functions: {schema_names - func_names}; "
        f"functions without schemas: {func_names - schema_names}"
    )


def test_no_duplicate_schema_names():
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert len(names) == len(set(names)), "duplicate tool name in TOOL_SCHEMAS"


def test_risky_tools_are_a_subset_of_registered_tools():
    assert RISKY_TOOLS <= set(TOOL_FUNCTIONS)


def test_read_only_tools_are_not_marked_risky():
    """Tools that only look at data (never change anything) should never
    require confirmation -- if one of these starts showing up as risky,
    something about its classification is wrong."""
    read_only_tools = {
        "get_current_time", "calculate", "list_directory", "read_file",
        "list_workspace", "read_any_file", "search_files", "index_files",
        "git_status", "git_log", "git_diff", "git_branch_list",
        "take_screenshot", "read_screen_text", "find_text_on_screen",
        "list_windows", "system_status", "top_processes", "web_search",
    }
    present = read_only_tools & set(TOOL_FUNCTIONS)
    assert present, "none of the expected read-only tools are even registered -- check the tool name list"
    assert not (present & RISKY_TOOLS), f"read-only tools incorrectly marked risky: {present & RISKY_TOOLS}"


def test_state_changing_tools_are_marked_risky():
    """Tools that change the real filesystem/system/repo/window state
    should always require confirmation."""
    should_be_risky = {
        "run_command", "open_application", "write_any_file", "delete_any_file",
        "rename_file", "move_file", "organize_directory",
        "git_add", "git_commit", "git_checkout", "git_push",
        "mouse_click", "keyboard_type", "keyboard_hotkey",
        "focus_window", "minimize_window", "close_window",
    }
    present = should_be_risky & set(TOOL_FUNCTIONS)
    assert present == should_be_risky, f"expected risky tools missing from registry: {should_be_risky - present}"
    assert present <= RISKY_TOOLS, f"state-changing tools NOT marked risky: {present - RISKY_TOOLS}"
