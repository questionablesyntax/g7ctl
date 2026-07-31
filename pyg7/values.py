"""Value coercion shared by the category modules (sticks, triggers,
vibration, dock_settings).

These are tiny, but each one used to exist as its own private copy in every
category module -- four identical `_percent()` definitions and two
`_side_offset()`s. Nothing forced the copies to stay in step, so a fix or a
loosened bound in one was silently absent from the others. They live here
once instead.
"""
from typing import Union

# A raw setting value as it arrives at a category module's set_value(): the
# CLI hands over an argparse string, the GUI hands over a native int/bool
# widget value. Individual settings narrow this further (a percent only
# ever takes int/str, never bool) -- this is the umbrella type for a
# set_value() that dispatches across several differently-shaped settings.
SettingValue = Union[int, str, bool]


def percent(v: Union[int, str]) -> int:
    """Coerce to the 0-100 percentage byte almost every level/deadzone
    setting on this device uses. Accepts anything int() accepts, so a CLI
    string ("50") and a GUI spinbox value (50) both work."""
    v = int(v)
    if not 0 <= v <= 100:
        raise ValueError(f"value must be 0-100, got {v}")
    return v


def boolean(v: Union[bool, str]) -> bool:
    """Coerce to bool, accepting the on/off-style strings the CLI passes
    through verbatim as well as real bools from the GUI."""
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("1", "true", "on", "yes")


def side_offset(side: str, right_offset: int) -> int:
    """Left/Right SETTING_ID offset.

    Right-hand settings reuse the Left side's SETTING_IDs shifted by a fixed
    per-category amount. `right_offset` is that amount and is deliberately a
    caller-supplied argument, not a constant here: it is NOT universal
    (Sticks uses +0x20, Triggers +0x1C), and hardcoding one value was how
    the two private copies of this function came to exist. See PROTOCOL.md
    "Sticks" / "Triggers".
    """
    side = side.lower()
    if side == "left":
        return 0
    if side == "right":
        return right_offset
    raise ValueError(f"side must be 'left' or 'right', got {side!r}")
