"""
Voice/tool-calling control for the desktop pet's house (ui/desktop_pet.py).

The DesktopPet instance itself is created and owned by jarvis_tray.py (same
lifecycle as NativeOverlay). This module just exposes two thin tool
functions over whatever instance is registered via set_pet(), following the
same TOOL_SCHEMAS/TOOL_FUNCTIONS/RISKY_TOOLS shape as tools/window_control.py.
"""

_pet = None  # set by jarvis_tray.py once DesktopPet is constructed


def set_pet(pet_instance) -> None:
    """Called once at startup by jarvis_tray.py to register the live
    DesktopPet instance this module should control."""
    global _pet
    _pet = pet_instance


def let_pet_out() -> str:
    """Open the house door and let the desktop pet roam the screen."""
    if _pet is None:
        return "The desktop pet isn't running."
    if _pet.is_out():
        return "The pet is already out and roaming."
    _pet.release()
    return "Let the pet out -- it's roaming the screen now."


def call_pet_home() -> str:
    """Recall the desktop pet to its house; it stops roaming and goes back to sleep."""
    if _pet is None:
        return "The desktop pet isn't running."
    if not _pet.is_out():
        return "The pet is already home, asleep in its house."
    _pet.call_home()
    return "Calling the pet home -- it'll settle back in its house."


DESKTOP_PET_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "let_pet_out",
            "description": "Open the desktop pet's house and let it out to roam freely around the screen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_pet_home",
            "description": "Recall the desktop pet back to its house, where it stops roaming and goes to sleep.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

DESKTOP_PET_TOOL_FUNCTIONS = {
    "let_pet_out": let_pet_out,
    "call_pet_home": call_pet_home,
}

# Neither changes files, runs commands, or touches anything outside the
# pet's own overlay window -- purely cosmetic, so no confirmation needed.
DESKTOP_PET_RISKY_TOOLS = set()
