"""Frozen interface, A0 of the redesign (`IMPLEMENTATION-PLAN.md` track A).

A2 and A3 build against `IconLoader` by type only; A1 implements it.
Source SVGs are vendored at `g7ctlc/assets/icons/` (`lucide-static` 1.61.0,
pinned; see `g7ctlc/assets/icons/SOURCES.md` for exact provenance). All 22
names below were checked against that exact vendored set in A0 -- every
one exists as `g7ctlc/assets/icons/<name>.svg`.

Per `DIRECTION-A.md`'s assets section (adopted in full by `DESIGN-SPEC.md`
section 5): rendered via QtSvg on a 24 grid, one absolute stroke, tinted at
theme load from a `Palette` role, recoloured per state, never shipped as
coloured copies.

This module is deliberately Qt-free, same reasoning as `palette.py` and
`tokens.py`: A2/A3 can type against `IconLoader` without pulling in
PyQt6, and tests that only need `ICON_NAMES`/`IconName` run without it
too. The concrete implementation, `LucideIconLoader`, lives in
`g7ctlc/icon_loader.py` instead -- that module needs PyQt6 (QtSvg,
`QPixmap`) and importing it without it raises, same as every other
Qt-backed g7ctlc module.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

IconName = Literal[
    "gamepad-2",
    "layers",
    "unplug",
    "usb",
    "loader-circle",
    "refresh-cw",
    "rotate-ccw",
    "file-up",
    "file-down",
    "lock",
    "check",
    "x",
    "search",
    "chevron-down",
    "circle-help",
    "info",
    "triangle-alert",
    "circle-alert",
    "battery",
    "battery-low",
    "battery-charging",
    "activity",
]

ICON_NAMES: tuple[IconName, ...] = (
    "gamepad-2",
    "layers",
    "unplug",
    "usb",
    "loader-circle",
    "refresh-cw",
    "rotate-ccw",
    "file-up",
    "file-down",
    "lock",
    "check",
    "x",
    "search",
    "chevron-down",
    "circle-help",
    "info",
    "triangle-alert",
    "circle-alert",
    "battery",
    "battery-low",
    "battery-charging",
    "activity",
)

# The two sizes `DIRECTION-A.md` specifies: 16 inline (within text), 20 in
# the rail and bars.
IconSize = Literal[16, 20]


@runtime_checkable
class IconLoader(Protocol):
    """Loads a vendored Lucide SVG, tinted from a `Palette` role, cached
    per (name, size, role, `ThemeVariant`). Never a coloured copy on disk --
    recolouring happens at load, so a theme change invalidates the cache
    rather than re-vendoring assets (`DESIGN-SPEC.md` 10.2 item 5).

    **Correction during A1, before any A2/A3 code existed to build
    against it**: the A0 draft of this signature took `role` alone and
    assumed the loader could resolve a hex value from it without being
    told which `Palette` is active. It can't -- `role` is only a name
    (`palette.PALETTE_ROLE_NAMES`); the actual colour has to come from
    somewhere. Fixed by taking the active `Palette` explicitly, here,
    before the signature had any caller to break.
    """

    def icon(self, name: IconName, size: IconSize, role: str, palette: object) -> object:
        """Return a `QIcon` for `name` at `size`, tinted with the colour at
        `palette`'s `role` property (one of `palette.PALETTE_ROLE_NAMES`).
        `palette` and the return type are typed `object` here, not
        `Palette`/`QIcon`, so this interface module carries no Qt import --
        A1's implementation is where PyQt6 is actually pulled in.
        """
        ...
