"""Frozen interface, A0 of the redesign (`IMPLEMENTATION-PLAN.md` track A).

A2 (components) and A3 (shell) build against `Palette` by type only. A1
(foundation) is the only phase that implements it, wires theme-change
invalidation, and feeds it into the QSS generator, `QPainter` widgets and
the icon loader. Changing a role name here after A2/A3 start means
revising the plan, not a routine edit.

Role names and values come from `DIRECTION-A.md` section 2 ("Semantic role
map"), adopted in full by `DESIGN-SPEC.md` section 5. This module fixes the
*names* and *shape* only -- the hex values live in A1's implementation,
not here, so this file stays stable while that implementation is written
and reviewed.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Protocol, runtime_checkable


class ThemeVariant(enum.Enum):
    """Which of the two designed themes (`DESIGN-SPEC.md` section 5) is
    active. Follows `QStyleHints.colorScheme()` (confirmed present on the
    installed binding, A0) with a user override.
    """

    DARK = "dark"
    LIGHT = "light"


@runtime_checkable
class Palette(Protocol):
    """One semantic palette, serving QSS, `QPainter` widgets, cached icons
    and local notices alike (`DESIGN-SPEC.md` 10.2 item 5 -- the orange
    rule must hold across all of them, not just stylesheet strings).

    Every property returns a hex color string (`"#rrggbb"`). Property
    names mirror the dotted role names in `DIRECTION-A.md` with `.`
    replaced by `_`; `edited_mark` is a named alias for `text_primary`
    kept distinct here because its callers (field "was" marks) are
    conceptually different from body text, even though today's value is
    the same.
    """

    variant: ThemeVariant

    # -- surfaces --
    @property
    def surface_ground(self) -> str: ...
    @property
    def surface_panel(self) -> str: ...
    @property
    def surface_raised(self) -> str: ...
    @property
    def surface_overlay(self) -> str: ...
    @property
    def surface_signal_tint(self) -> str: ...
    @property
    def surface_alarm_tint(self) -> str: ...

    # -- text --
    @property
    def text_primary(self) -> str: ...
    @property
    def edited_mark(self) -> str: ...
    @property
    def text_secondary(self) -> str: ...
    @property
    def text_disabled(self) -> str: ...
    @property
    def text_signal(self) -> str: ...
    @property
    def text_alarm(self) -> str: ...
    @property
    def text_caution(self) -> str: ...
    @property
    def text_on_signal(self) -> str: ...
    @property
    def text_on_alarm(self) -> str: ...

    # -- borders --
    @property
    def border_subtle(self) -> str: ...
    @property
    def border_control(self) -> str: ...
    @property
    def border_selected(self) -> str: ...

    # -- signal (the controller-is-involved closed list, CRITIC.md #1) --
    @property
    def signal_fill(self) -> str: ...
    @property
    def signal_fill_hover(self) -> str: ...
    @property
    def signal_fill_pressed(self) -> str: ...
    @property
    def signal_mark(self) -> str: ...

    # -- alarm --
    @property
    def alarm_fill(self) -> str: ...
    @property
    def alarm_fill_hover(self) -> str: ...

    # -- focus (never the accent) --
    @property
    def focus_ring(self) -> str: ...


# Every `Palette` property name, in the order `DIRECTION-A.md` lists them.
# The contrast test (A1) and the colour-rule test (A1 -- signal colour only
# in its three roles) both iterate this instead of hand-maintaining a
# second list that can drift from the Protocol above.
PALETTE_ROLE_NAMES: tuple[str, ...] = (
    "surface_ground",
    "surface_panel",
    "surface_raised",
    "surface_overlay",
    "surface_signal_tint",
    "surface_alarm_tint",
    "text_primary",
    "edited_mark",
    "text_secondary",
    "text_disabled",
    "text_signal",
    "text_alarm",
    "text_caution",
    "text_on_signal",
    "text_on_alarm",
    "border_subtle",
    "border_control",
    "border_selected",
    "signal_fill",
    "signal_fill_hover",
    "signal_fill_pressed",
    "signal_mark",
    "alarm_fill",
    "alarm_fill_hover",
    "focus_ring",
)

# The three roles the signal colour is ever allowed in (CRITIC.md #1): the
# held state, live input marks, and the button that actually writes. A1's
# colour-rule test asserts no other role, in QSS, painter or asset use,
# carries this hue.
SIGNAL_ROLE_NAMES: tuple[str, ...] = (
    "surface_signal_tint",
    "signal_fill",
    "signal_fill_hover",
    "signal_fill_pressed",
    "signal_mark",
)


# ---------------------------------------------------------------------------
# Concrete implementation, A1. Values from `DIRECTION-A.md` section 2's
# semantic role map, verified independently by the feasibility review
# (13 of A's contrast pairs recomputed, all matched to two decimals --
# `DESIGN-SPEC.md` section 5). A plain frozen dataclass satisfies `Palette`
# structurally (attribute access, not a formal property, is all the
# Protocol requires) and needs no Qt import, so palette values and the
# contrast/colour-rule tests that check them stay testable without PyQt6.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _StaticPalette:
    variant: ThemeVariant

    surface_ground: str
    surface_panel: str
    surface_raised: str
    surface_overlay: str
    surface_signal_tint: str
    surface_alarm_tint: str

    text_primary: str
    text_secondary: str
    text_disabled: str
    text_signal: str
    text_alarm: str
    text_caution: str
    text_on_signal: str
    text_on_alarm: str

    border_subtle: str
    border_control: str
    border_selected: str

    signal_fill: str
    signal_fill_hover: str
    signal_fill_pressed: str
    signal_mark: str

    alarm_fill: str
    alarm_fill_hover: str

    focus_ring: str

    @property
    def edited_mark(self) -> str:
        # Named alias, not a duplicated literal: this stays locked to
        # text_primary by construction instead of by convention.
        return self.text_primary


DARK_PALETTE = _StaticPalette(
    variant=ThemeVariant.DARK,
    surface_ground="#1b1d20",
    surface_panel="#23262a",
    surface_raised="#2d3035",
    surface_overlay="#30343a",
    surface_signal_tint="#3a2a1f",
    surface_alarm_tint="#3a2224",
    text_primary="#e9ebee",
    text_secondary="#aab0b8",
    text_disabled="#7a8089",
    text_signal="#ff9a55",
    text_alarm="#ff6f6a",
    text_caution="#e8bb4a",
    text_on_signal="#1b1d20",
    text_on_alarm="#fbfcfc",
    border_subtle="#3a3e44",
    border_control="#7a8089",
    border_selected="#e9ebee",
    signal_fill="#ff8a3d",
    signal_fill_hover="#ff9d5c",
    signal_fill_pressed="#e67736",
    signal_mark="#ff8a3d",
    alarm_fill="#d23b33",
    alarm_fill_hover="#b8302a",
    focus_ring="#8fd0ff",
)

LIGHT_PALETTE = _StaticPalette(
    variant=ThemeVariant.LIGHT,
    surface_ground="#e9ecef",
    surface_panel="#f6f7f8",
    # Light surface.overlay is the same fill as raised plus a
    # border.control stroke (`DIRECTION-A.md` section 2's role map marks
    # it "`#fbfcfc` + `border.control`") -- the stroke is drawn by callers
    # that use this role, not encoded as a second colour here.
    surface_raised="#fbfcfc",
    surface_overlay="#fbfcfc",
    surface_signal_tint="#f7e3d6",
    surface_alarm_tint="#f9dde0",
    text_primary="#1b1e22",
    text_secondary="#4f5862",
    text_disabled="#7b838c",
    text_signal="#a84607",
    text_alarm="#b0182f",
    text_caution="#8a5a00",
    text_on_signal="#fbfcfc",
    text_on_alarm="#fbfcfc",
    border_subtle="#d3d8dd",
    border_control="#7b838c",
    border_selected="#1b1e22",
    signal_fill="#b8500f",
    signal_fill_hover="#a3460c",
    signal_fill_pressed="#9a3f08",
    signal_mark="#b8500f",
    alarm_fill="#b0182f",
    alarm_fill_hover="#93122a",
    focus_ring="#0a63c2",
)

_PALETTES: dict[ThemeVariant, Palette] = {
    ThemeVariant.DARK: DARK_PALETTE,
    ThemeVariant.LIGHT: LIGHT_PALETTE,
}


def palette_for(variant: ThemeVariant) -> Palette:
    return _PALETTES[variant]


class PaletteProvider:
    """Tracks the active `Palette` and notifies listeners on a theme
    change, so QSS, cached icons and `QPainter` widgets all invalidate
    together (`DESIGN-SPEC.md` 10.2 item 5) rather than drifting out of
    sync with each other. Framework-agnostic on purpose: plain callables,
    no `QObject`/signal here, so this stays importable (and testable)
    without PyQt6. `g7ctlc/theme_runtime.py` is the Qt-aware layer that
    wires this to `QStyleHints.colorSchemeChanged` and re-exposes it as a
    Qt signal for widgets to connect to.
    """

    def __init__(self, initial: ThemeVariant = ThemeVariant.DARK) -> None:
        self._variant = initial
        self._listeners: list = []

    @property
    def variant(self) -> ThemeVariant:
        return self._variant

    @property
    def current(self) -> Palette:
        return palette_for(self._variant)

    def set_variant(self, variant: ThemeVariant) -> None:
        if variant is self._variant:
            return
        self._variant = variant
        for listener in list(self._listeners):
            listener(self.current)

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        self._listeners.remove(callback)
