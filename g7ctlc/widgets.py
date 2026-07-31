"""Shared Qt widget helpers used across category view tabs."""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QSpinBox, QWidget

from pyg7.buttons import KNOWN_KEYCODES
from pyg7.curves import CURVE_PRESET_INDEX

# Curve presets offered by the Sticks and Triggers tabs. Derived from the
# protocol layer rather than retyped, so a preset added there can't go
# missing from the pickers -- both views previously kept their own hardcoded
# copy of this list.
CURVE_OPTIONS = list(CURVE_PRESET_INDEX) + ["custom"]


def percent_spin() -> QSpinBox:
    """The 0-100 spinbox used for every level/deadzone field."""
    sb = QSpinBox()
    sb.setRange(0, 100)
    return sb


class CategorySideWidget(QWidget):
    """Shared scaffolding for a per-side category widget (Sticks'
    `_StickSideWidget`, Triggers' `_TriggerSideWidget`): a loading guard and
    a `changed` signal, previously hand-implemented identically in both
    -- easy for the two to quietly drift since nothing enforced they stay
    in step.

    The loading guard exists because `load()` sets every field from a state
    dict, and each field's own `valueChanged`/`toggled`/`currentIndexChanged`
    signal is wired to `_emit_changed()` -- without a guard, loading would
    itself look like N user edits and re-trigger `changed` (and therefore a
    write back into the state dict) N times for data that came FROM the
    state dict a moment ago.

    Subclasses build their own widgets in `__init__` (calling
    `super().__init__(parent)` first) and implement `_load_fields()` (called
    inside the guard) and `save_into()`. Override `_after_load()` for any
    step that must run once loading is complete but should NOT itself be
    guarded against re-triggering `changed` (Sticks uses this to refresh
    which Advanced Mapping rows are visible for the now-loaded output mode).
    """
    changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False

    def _emit_changed(self, *_: object) -> None:
        if not self._loading:
            self.changed.emit()

    def load(self, side_data: dict) -> None:
        self._loading = True
        try:
            self._load_fields(side_data)
        finally:
            self._loading = False
        self._after_load()

    def _load_fields(self, side_data: dict) -> None:
        raise NotImplementedError

    def _after_load(self) -> None:
        """Optional hook, run after load()'s guard is released."""

    def save_into(self, side_data: dict) -> None:
        raise NotImplementedError

# Display-grouping only (see buttons.py: there's no "page" concept on the
# wire). Each entry is (internal_name, short_label); the combo box renders
# items as "{group_label}: {short_label}" (e.g. "Native: A", "Num Pad: 1",
# "Mouse: Left Button") -- a consistent, scannable structure that also
# means Qt's built-in type-ahead (typing a letter jumps to the first
# matching item) lands on a category's first entry when you type its
# initial, since every item in that category shares the same prefix.
# Groups themselves are ordered alphabetically by label for the same
# reason -- predictable jump targets.
#
# Keyboard row order matches the physical layout (Esc/F-row, number row,
# then each subsequent row top to bottom, left to right) -- see buttons.py's
# KNOWN_KEYCODES for confirmed-vs-predicted status per key.
KEYCODE_GROUPS = [
    ("Keyboard", [
        ("esc", "Esc"), ("f1", "F1"), ("f2", "F2"), ("f3", "F3"), ("f4", "F4"),
        ("f5", "F5"), ("f6", "F6"), ("f7", "F7"), ("f8", "F8"), ("f9", "F9"),
        ("f10", "F10"), ("f11", "F11"), ("f12", "F12"),
        ("backtick", "` / ~"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"),
        ("5", "5"), ("6", "6"), ("7", "7"), ("8", "8"), ("9", "9"), ("0", "0"),
        ("minus", "- / _"), ("equals", "= / +"), ("backspace", "Backspace"),
        ("tab", "Tab"), ("q", "Q"), ("w", "W"), ("e", "E"), ("r", "R"), ("t", "T"),
        ("y", "Y"), ("u", "U"), ("i", "I"), ("o", "O"), ("p", "P"),
        ("lbracket", "[ / {"), ("rbracket", "] / }"), ("backslash", "\\ / |"),
        ("capslock", "Caps Lock"), ("a", "A"), ("s", "S"), ("d", "D"), ("f", "F"),
        ("g", "G"), ("h", "H"), ("j", "J"), ("k", "K"), ("l", "L"),
        ("semicolon", "; / :"), ("quote", "' / \""), ("enter", "Enter"),
        ("shift", "Shift (L)"), ("z", "Z"), ("x", "X"), ("c", "C"), ("v", "V"),
        ("b", "B"), ("n", "N"), ("m", "M"), ("comma", ", / <"), ("period", ". / >"),
        ("slash", "/ / ?"), ("rshift", "Shift (R)"), ("ctrl", "Ctrl (L)"),
        ("win", "Win"), ("alt", "Alt (L)"), ("space", "Space"),
        ("ralt", "Alt (R)"), ("rctrl", "Ctrl (R)"),
    ]),
    ("Mouse", [
        ("mouse_left", "Left Button"), ("mouse_middle", "Middle Button"),
        ("mouse_right", "Right Button"),
        ("mouse_button4", "Button 4"), ("mouse_button5", "Button 5"),
        ("scroll_up", "Scroll Up"), ("scroll_down", "Scroll Down"),
    ]),
    ("Native", [
        ("native_dpad_up", "D-Pad Up"), ("native_dpad_down", "D-Pad Down"),
        ("native_dpad_left", "D-Pad Left"), ("native_dpad_right", "D-Pad Right"),
        ("native_lb", "LB"), ("native_rb", "RB"),
        ("native_l3", "L3"), ("native_r3", "R3"),
        ("native_a", "A"), ("native_b", "B"), ("native_x", "X"), ("native_y", "Y"),
        ("native_home", "Home (Xbox/Guide)"),
        ("native_view", "View"), ("native_menu", "Menu"),
        ("native_share_capture", "Share / Capture"),
        ("native_l4", "L4"), ("native_r4", "R4"),
        ("native_lt", "LT"), ("native_rt", "RT"),
        # 0x1F/0x20 sit outside the 0x01-0x14 native-gamepad block above --
        # confirmed 2026-07-30 the same way as native_home/l4/r4 (written to
        # a scratch profile, read back via GameSir Nexus's own labels), not
        # a numbering mistake -- see PROTOCOL.md "Keycodes".
        ("native_l5", "L5"), ("native_r5", "R5"),
        # 0xE6/0xE7 sit in their own region far from the 0x01-0x14 native
        # block; the wire values are confirmed by write+read-diff but the
        # function each performs is only guessed from its picker icon, so
        # the labels say so rather than promising behaviour we can't back up.
        ("mic_mute", "Mic (unconfirmed)"),
        ("unknown_swap_0xe7", "Swap (unconfirmed)"),
    ]),
    # Operator keys come before the digits, matching the keycode order
    # (0x85-0x8A, then numpad0 at 0x8B) rather than a phone-pad layout.
    ("Num Pad", [
        ("numpad_slash", "/"), ("numpad_star", "*"), ("numpad_minus", "-"),
        ("numpad_plus", "+"), ("numpad_period", "."), ("numpad_enter", "Enter"),
    ] + [(f"numpad{n}", str(n)) for n in range(10)]),
]

# Every name in KNOWN_KEYCODES must be reachable from the picker, or a
# binding using it renders as "(Unbound)" and then gets dropped from the
# state dict by the next unrelated edit (ButtonsView._on_edit sweeps every
# combo, not just the one that changed). That is silent data loss on
# Export, and it is exactly what happened when the 0x85-0x8A, 0xCB/0xCC,
# 0x10 and 0xE6/0xE7 keycodes were added to the protocol layer without
# anyone updating this file. Anything deliberately withheld from the
# picker belongs in _NOT_SELECTABLE with a reason, so the drift can never
# be accidental again.
_NOT_SELECTABLE: dict[str, str] = {
    # (empty -- every known keycode is currently offered)
}


def _assert_keycode_coverage() -> None:
    listed = {name for _label, entries in KEYCODE_GROUPS for name, _short in entries}
    unreachable = sorted(set(KNOWN_KEYCODES) - listed - set(_NOT_SELECTABLE))
    if unreachable:
        raise RuntimeError(
            "keycodes missing from KEYCODE_GROUPS (they would render as "
            f"'(Unbound)' and be silently dropped): {unreachable}"
        )
    phantom = sorted(listed - set(KNOWN_KEYCODES))
    if phantom:
        raise RuntimeError(f"KEYCODE_GROUPS lists unknown keycodes: {phantom}")


_assert_keycode_coverage()


def make_keycode_combo() -> QComboBox:
    """QComboBox listing every KNOWN_KEYCODES name, grouped for readability.
    itemData is the keycode name (str), or None for "(Unbound)". Item text
    is "{group_label}: {short_label}" -- see KEYCODE_GROUPS above for why."""
    combo = QComboBox()
    combo.addItem("(Unbound)", None)
    for group_label, entries in KEYCODE_GROUPS:
        available = [(name, label) for name, label in entries if name in KNOWN_KEYCODES]
        if not available:
            continue
        combo.insertSeparator(combo.count())
        combo.addItem(f"— {group_label} —", "__header__")
        header_item = combo.model().item(combo.count() - 1)
        header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        for name, label in available:
            combo.addItem(f"{group_label}: {label}", name)
    return combo


def select_by_data(combo: QComboBox, value: Optional[str]) -> None:
    """Select the item whose itemData is `value`, preserving values the
    picker doesn't offer.

    decode_button_table() falls back to a raw hex string (e.g. "0x0d") for
    any keycode outside KNOWN_KEYCODES' still-incomplete coverage, and real
    hardware does return those -- e.g. a factory-default read of Profiles
    2-4 on the development controller used to come back with unnamed
    0x11/0x12 on the paddles and 0x1f/0x20 on L5/R5 (now native_l4/native_r4/
    native_l5/native_r5, resolved 2026-07-30 -- see PROTOCOL.md
    "Keycodes"), and KNOWN_KEYCODES' coverage is still not exhaustive in
    general.

    Falling back to index 0 ("(Unbound)") for those would misreport the
    device and then let ButtonsView._on_edit drop the binding from the
    state dict entirely on the next unrelated edit. So an unrecognised
    non-None value gets its own item appended instead: the combo shows it
    as raw hex, currentData() hands the identical string back, and the
    value round-trips through load -> edit -> export untouched.
    """
    idx = combo.findData(value)
    if idx < 0 and value is not None:
        combo.addItem(f"Raw: {value}", value)
        idx = combo.count() - 1
    combo.setCurrentIndex(idx if idx >= 0 else 0)
