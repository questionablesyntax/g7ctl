"""Shared Qt widget helpers used across category view tabs."""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

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
# binding using it renders as "(Default)" and then gets dropped from the
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
            f"'(Default)' and be silently dropped): {unreachable}"
        )
    phantom = sorted(listed - set(KNOWN_KEYCODES))
    if phantom:
        raise RuntimeError(f"KEYCODE_GROUPS lists unknown keycodes: {phantom}")


_assert_keycode_coverage()


def make_keycode_combo() -> QComboBox:
    """QComboBox listing every KNOWN_KEYCODES name, grouped for readability.
    itemData is the keycode name (str), or None for "(Default)". Item text
    is "{group_label}: {short_label}" -- see KEYCODE_GROUPS above for why.

    Index 0 reads "(Default)", not "(Unbound)". A slot with no explicit
    binding is not dead -- the button performs its factory function, and
    the device cannot even represent "explicitly dead" (unbinding returns a
    slot to byte-identical never-configured state). "(Unbound)" made
    Profiles 2-4, which are mostly unconfigured, look broken next to what
    GameSir Nexus shows. See PROTOCOL.md "An empty slot means factory
    default, not unbound"."""
    combo = QComboBox()
    combo.addItem("(Default)", None)
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

    Falling back to index 0 ("(Default)") for those would misreport the
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


class CurvePointsEditor(QWidget):
    """The three interior control points of a Custom curve.

    Numeric only, deliberately. The five handles Nexus draws cannot be
    rendered honestly yet: the interpolation between them is not
    established (Bezier and Catmull-Rom both reproduce the presets), so a
    drawn curve would be a guess about what the controller actually does.
    A graphical editor is the goal -- see the GUI roadmap -- but it needs
    that answered first.

    The units are the trap here and the labels say so out loud. These
    points are 0-255. The Deadzone and Anti-Deadzone fields sitting a few
    rows above are 0-100, and they are the *same curve's* two endpoints
    (their X and Y coordinates respectively -- see PROTOCOL.md "A curve is
    five handles"). Two scales, one axis, adjacent on screen.
    """
    changed = pyqtSignal()

    POINT_COUNT = 3
    LABELS = ("Point 1 (lower)", "Point 2 (middle)", "Point 3 (upper)")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._last_writable = True
        self._configured = True

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(14)

        self.rows: list[tuple[QSpinBox, QSpinBox]] = []
        for i in range(self.POINT_COUNT):
            x, y = QSpinBox(), QSpinBox()
            for sb in (x, y):
                sb.setRange(0, 255)
                sb.valueChanged.connect(self._on_value_changed)
            pair = QWidget()
            hbox = QHBoxLayout(pair)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(6)
            hbox.addWidget(QLabel("x"))
            hbox.addWidget(x)
            hbox.addWidget(QLabel("y"))
            hbox.addWidget(y)
            hbox.addStretch(1)
            layout.addRow(self.LABELS[i], pair)
            self.rows.append((x, y))
        self._row_widgets = [layout.itemAt(i, QFormLayout.ItemRole.LabelRole).widget()
                             for i in range(self.POINT_COUNT)]

    # --- monotonic ordering -------------------------------------------------
    #
    # Nexus clamps a dragged point to its neighbours, and this matches that.
    # The firmware does NOT enforce it -- P1=(0,0) with P3=(255,255) was
    # accepted on hardware -- so this is a deliberate UI choice to keep a
    # curve sensible, not a protocol requirement. Implemented by moving the
    # spinbox bounds rather than snapping values after the fact, so the user
    # simply cannot drag past a neighbour.

    def _reclamp(self) -> None:
        for axis in (0, 1):
            boxes = [row[axis] for row in self.rows]
            for i, sb in enumerate(boxes):
                lower = boxes[i - 1].value() if i > 0 else 0
                upper = boxes[i + 1].value() if i < len(boxes) - 1 else 255
                sb.blockSignals(True)
                sb.setRange(lower, upper)
                sb.blockSignals(False)

    def _on_value_changed(self, *_: object) -> None:
        self._reclamp()
        if not self._loading:
            self.changed.emit()

    # --- state --------------------------------------------------------------

    def is_configured(self) -> bool:
        """False when the last load() carried None -- the curve block has
        never been written on this profile."""
        return self._configured

    def load(self, points: Optional[list]) -> None:
        """`points` is [[x, y], ...] from a device read, or None when the
        profile's curve block has never been written."""
        self._configured = points is not None
        self._loading = True
        try:
            for i, (x, y) in enumerate(self.rows):
                for sb in (x, y):
                    sb.blockSignals(True)
                    sb.setRange(0, 255)      # widen first, or a stale clamp rejects the value
                if points and i < len(points):
                    x.setValue(int(points[i][0]))
                    y.setValue(int(points[i][1]))
                else:
                    x.setValue(0)
                    y.setValue(0)
                for sb in (x, y):
                    sb.blockSignals(False)
            self._reclamp()
        finally:
            self._loading = False

    def points(self) -> list[list[int]]:
        return [[x.value(), y.value()] for x, y in self.rows]

    def set_points_enabled(self, enabled: bool) -> None:
        """Points are only editable on a Custom curve -- Nexus exposes them
        nowhere else, and whether the firmware honours a point edit under a
        named preset is untested."""
        for i, (x, y) in enumerate(self.rows):
            last = i == len(self.rows) - 1
            on = enabled and (self._last_writable or not last)
            x.setEnabled(on)
            y.setEnabled(on)
            self._row_widgets[i].setEnabled(on)

    def set_last_point_writable(self, writable: bool, reason: str = "") -> None:
        """Right Trigger's third point cannot be written -- its address
        (0x100) crosses the one-byte SETTING_ID field and the encoding is
        unverified, so pyg7 refuses it. Disabling the field here keeps that
        refusal from surfacing as a failed sync halfway through a write."""
        self._last_writable = writable
        x, y = self.rows[-1]
        for sb in (x, y):
            sb.setToolTip(reason)
        self._row_widgets[-1].setToolTip(reason)
