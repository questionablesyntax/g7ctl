"""Buttons page: per-button Default/Shift-layer keycode assignment, A4/D2
of the redesign.

The controller diagram (`controller_diagram.py`) is the only remapping
surface -- the always-visible 21-row table this page used to show beside
it was cut entirely, owner decision, D2 rework (2026-10-22;
`IMPLEMENTATION-PLAN.md`'s D2 section has the full history of why a
table existed in the first place and why it's gone). `BindingRow` still
exists and is still built once per button, same wiring as before (Latch,
Shift reference, `_on_edit()`'s full sweep) -- only one row at a time is
now parented into the page's detail panel, whichever button the diagram
itself currently has focus on (`_show_detail_for`). `_order` groups
controls the way they're physically arranged on the controller (face
buttons, stick clicks, shoulder/paddle pairs, trigger/paddle pairs,
D-pad, misc) rather than KNOWN_BUTTON_IDS's declaration order, and
doubles as the diagram's own Tab order.

The Shift column is a read-only reference on this page (a real, editable
Shift column lives on the separate Shift page this same view also
serves, selected via set_layer("shift") -- see that method). save_into/
touched-guard contracts are unchanged from the pre-redesign version:
_on_edit() still sweeps every field on every edit and still stores an
explicit None rather than popping a key on a deliberate reset (2026-09-17's
real bug, see that method's own comment).
"""
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyg7.buttons import BUTTON_TABLE_SLOTS, KNOWN_BUTTON_IDS, KNOWN_KEYCODES

from ..binding_field import BindingField
from ..binding_row import LATCH_COL_WIDTH as _LATCH_COL_WIDTH
from ..binding_row import MAX_ROW_WIDTH as _MAX_ROW_WIDTH
from ..binding_row import NAME_COL_WIDTH as _NAME_COL_WIDTH
from ..binding_row import BindingRow
from ..checkbox import Checkbox
from ..controller_diagram import ControllerDiagram
from ..keycode_picker import KeycodePicker
from ..palette import DARK_PALETTE, Palette

_BUTTON_LABELS = {
    "share": "Share", "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "l3": "L3 (stick click)", "r3": "R3 (stick click)",
    "view": "View", "menu": "Menu", "l4": "L4", "r4": "R4",
    "l5": "L5", "r5": "R5",
    "dpad_up": "D-Pad Up", "dpad_down": "D-Pad Down",
    "dpad_left": "D-Pad Left", "dpad_right": "D-Pad Right",
}

_BUTTON_GROUPS = [
    ("a", "b", "x", "y"),
    ("r3", "l3"),
    ("rb", "lb", "r5", "l5"),
    ("rt", "lt", "l4", "r4"),
    ("dpad_up", "dpad_down", "dpad_left", "dpad_right"),
    ("view", "menu", "share"),
]

_LATCH_TOOLTIP = (
    "GameSir calls this Continuous Trigger. Press once and the button stays "
    "held until pressed again. It is not turbo/rapid-fire -- the button "
    "does not repeat, which is also why there is no rate setting.\n\n"
    "Independent of the binding: it doesn't change what the button sends, "
    "only how long it stays sent.\n\n"
    "Profile-scoped, and stored inside the button's own record, so it "
    "applies to the Base layer only."
)

# LT/RT are the exception: they have no record in the button table (their
# keycode is a lone byte inside the Triggers category's data), so there is
# no Continuous Trigger byte to derive for them -- see
# pyg7.buttons.continuous_trigger_offset(). They show this reason as
# visible text instead of a checkbox that would silently do nothing.
_LATCH_UNSUPPORTED_REASON = "Triggers have no latch setting"

log = logging.getLogger(__name__)

_SHARED_SHIFT_TOOLTIP = (
    "The controller has ONE Shift layer, shared by all four profiles -- "
    "editing it here changes it for every profile, not just this one. "
    "GameSir Nexus shows a Shift section under each profile tab, which makes "
    "it look per-profile, but the same bindings appear under all of them."
)


class ButtonsView(QWidget):
    changed = pyqtSignal()

    def __init__(self, palette: Palette = DARK_PALETTE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = None
        self._layer = "default"
        self._rows: dict[str, BindingRow] = {}
        self._continuous: dict[str, Checkbox] = {}
        self._continuous_spacers: list[QWidget] = []
        self._active_field: BindingField | None = None  # whichever field opened the picker

        self._picker = KeycodePicker(self)
        self._picker.codeChosen.connect(self._on_code_chosen)

        # D2 rework (2026-10-22, owner decision): the table is cut
        # entirely, not kept as a secondary list -- the diagram is the
        # only remapping surface now. `_order` mirrors _BUTTON_GROUPS'
        # physical layout so Tab through the diagram's hotspots follows
        # the page's established button grouping, not KNOWN_BUTTON_IDS'
        # declaration order; it also picks the button shown in the detail
        # panel before anything has been selected (see _show_detail_for).
        self._order = [b for group in _BUTTON_GROUPS for b in group]
        self._selected_button: str | None = None
        self.diagram = ControllerDiagram(
            palette, labels=_BUTTON_LABELS, order=self._order, parent=self)
        self.diagram.activated.connect(self._on_diagram_activated)
        self.diagram.focused.connect(self._show_detail_for)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.diagram, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Fixed rather than Expanding, and deliberately narrower than
        # BindingRow's own MAX_ROW_WIDTH cap (760 -- sized for the old
        # table, where 20 other rows needed the same width to stay
        # aligned as columns). A single row doesn't need that; the
        # diagram is the primary surface now and should get the window's
        # real estate, not a leftover sliver.
        _DETAIL_WIDTH = 520
        scroll.setFixedWidth(_DETAIL_WIDTH)
        outer.addWidget(scroll)

        content_widget = QWidget()
        content = QVBoxLayout(content_widget)
        content.setContentsMargins(10, 8, 10, 8)
        content.setSpacing(2)

        content.addWidget(self._build_header())

        # One row at a time lives here -- whichever button the diagram's
        # own focus is currently on (see _show_detail_for). Every row is
        # still built below regardless of whether it's ever shown, so
        # _on_edit()'s full sweep, Latch state and the Shift reference all
        # keep working exactly as before; only the always-visible list of
        # 21 is gone.
        self._detail_slot = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_slot)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        content.addWidget(self._detail_slot)

        # Defensive check: a button present in KNOWN_BUTTON_IDS but missing
        # from _BUTTON_GROUPS would silently vanish from the GUI, exactly
        # the L5/R5 bug from before this list existed.
        grouped = set(self._order)
        missing = [b for b in KNOWN_BUTTON_IDS if b not in grouped]
        assert not missing, f"buttons missing from _BUTTON_GROUPS: {missing}"

        for button_id in self._order:
            supports_latch = button_id in BUTTON_TABLE_SLOTS
            row = BindingRow(
                _BUTTON_LABELS.get(button_id, button_id),
                latch_reason=None if supports_latch else _LATCH_UNSUPPORTED_REASON,
            )
            row.default_field.clicked.connect(
                lambda _checked=False, b=button_id: self._open_picker(b, "default"))
            row.shift_field.clicked.connect(
                lambda _checked=False, b=button_id: self._open_picker(b, "shift"))
            # The one row the detail panel is currently showing can still
            # be focused/clicked directly (its fields are real widgets in
            # the layout) -- keep it in sync with the diagram the same way
            # a click or Tab onto the diagram's own hotspot does.
            row.default_field.clicked.connect(
                lambda _checked=False, b=button_id: self.diagram.set_highlighted(b))
            row.shift_field.clicked.connect(
                lambda _checked=False, b=button_id: self.diagram.set_highlighted(b))
            row.default_field.focused.connect(
                lambda b=button_id: self.diagram.set_highlighted(b))
            row.shift_field.focused.connect(
                lambda b=button_id: self.diagram.set_highlighted(b))
            row.shift_reference.setToolTip(_SHARED_SHIFT_TOOLTIP)
            if row.latch is not None:
                row.latch.setToolTip(_LATCH_TOOLTIP)
                row.latch.toggled.connect(self._on_edit)
                self._continuous[button_id] = row.latch
            else:
                row.latch_reason_label.setToolTip(
                    "The triggers have no Continuous Trigger setting -- they're "
                    "stored differently from the other buttons, and whether the "
                    "hardware supports it for them at all is unknown.")
                self._continuous_spacers.append(row.latch_reason_label)
            self._rows[button_id] = row

        self.options_separator = QFrame()
        self.options_separator.setFrameShape(QFrame.Shape.HLine)
        self.options_separator.setProperty("role", "separator")
        content.addWidget(self.options_separator)

        self.swap_stick_dpad = Checkbox("Swap Left Stick and D-pad")
        self.swap_stick_dpad.toggled.connect(self._on_edit)
        self.swap_stick_dpad.setToolTip(
            "Hardware-verified 2026-07-29: a full-blob diff of a real ON then "
            "OFF write changed exactly the two intended bytes each time, and "
            "the OFF blob came back byte-identical to the pre-write baseline. "
            "See pyg7/dpad_options.py."
        )
        content.addWidget(self.swap_stick_dpad)

        self.dpad_diagonal_lock = Checkbox("D-Pad Diagonal Lock")
        self.dpad_diagonal_lock.toggled.connect(self._on_edit)
        content.addWidget(self.dpad_diagonal_lock)

        content.addStretch(1)
        scroll.setWidget(content_widget)

        # Show the first button's row until the diagram says otherwise --
        # a fresh page with nothing selected would otherwise show an empty
        # detail panel for no reason, and this also keeps the Default/
        # Shift visibility invariants (`test_gui_bindings.py`) true of
        # "a" the same way they were on the old always-visible table.
        self._show_detail_for(self._order[0])

        # Apply the starting layer rather than trusting the caller to.
        # Both layers' fields are built above and are visible by default, so
        # without this the Shift column sits next to the Default one until
        # something calls set_layer() -- which MainWindow only does on a
        # profile *change*. That put a shared, device-global column inside
        # the per-profile screen on every fresh launch, showing exactly the
        # thing the Shift-as-its-own-screen change existed to stop showing.
        self.set_layer(self._layer)

    def _show_detail_for(self, button_id: str) -> None:
        """Swap which button's row is parented into the detail panel --
        the diagram's own `focused` signal is the only thing that calls
        this in practice, but it takes a plain button id rather than
        assuming that, so a test or a future caller can drive it directly."""
        if button_id not in self._rows or button_id == self._selected_button:
            return
        if self._selected_button is not None:
            old_row = self._rows[self._selected_button]
            self._detail_layout.removeWidget(old_row)
            old_row.setParent(None)
        self._selected_button = button_id
        row = self._rows[button_id]
        row.setParent(self._detail_slot)
        self._detail_layout.addWidget(row)
        row.show()
        self.diagram.set_highlighted(button_id)

    # -- the shared picker --------------------------------------------------

    def _field_for(self, button_id: str, layer: str) -> BindingField:
        row = self._rows[button_id]
        return row.default_field if layer == "default" else row.shift_field

    def _open_picker(self, button_id: str, layer: str, anchor: QWidget | None = None) -> None:
        field = self._field_for(button_id, layer)
        self._active_field = field
        self._picker.open_for(anchor or field, field.value(), known=field.is_known())

    def _on_diagram_activated(self, button_id: str) -> None:
        """A click or Enter/Space on a diagram hit region -- the diagram
        itself doesn't know about layers or pickers, just that this part
        was activated (see controller_diagram.py's module docstring)."""
        self.diagram.set_highlighted(button_id)
        self._open_picker(button_id, self._layer, anchor=self.diagram.hotspot_for(button_id))

    def _on_code_chosen(self, value) -> None:
        if self._active_field is None:
            return
        self._active_field.set_value(value, known=value is None or value in KNOWN_KEYCODES)
        self._active_field = None
        self._on_edit()

    def _build_header(self) -> QWidget:
        header_widget = QWidget()
        # Matches BindingRow's own cap so the header stays aligned with
        # every row beneath it -- see binding_row.py's MAX_ROW_WIDTH.
        header_widget.setMaximumWidth(_MAX_ROW_WIDTH)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(8, 4, 8, 8)
        header.setSpacing(8)

        name_header = QLabel("Button")
        name_header.setProperty("role", "secondary")
        name_header.setFixedWidth(_NAME_COL_WIDTH)
        header.addWidget(name_header)

        self.column_header = QLabel("Base Layer")
        self.column_header.setProperty("role", "secondary")
        header.addWidget(self.column_header, 1)

        self.shift_reference_header = QLabel("Shift (shared)")
        self.shift_reference_header.setProperty("role", "secondary")
        # Real gap, found in A6's code review (2026-10-22): the
        # pre-redesign combo boxes carried this explanation; the new
        # read-only reference column lost it with nothing in its place.
        self.shift_reference_header.setToolTip(_SHARED_SHIFT_TOOLTIP)
        header.addWidget(self.shift_reference_header, 1)

        self.continuous_header = QLabel("Latch")
        self.continuous_header.setProperty("role", "secondary")
        self.continuous_header.setFixedWidth(_LATCH_COL_WIDTH)
        self.continuous_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.continuous_header.setToolTip(_LATCH_TOOLTIP)
        header.addWidget(self.continuous_header)

        return header_widget

    # -- public API (unchanged contract) -------------------------------

    def set_palette(self, palette: Palette) -> None:
        self.diagram.set_palette(palette)

    def set_layer(self, layer: str) -> None:
        """Show the Base layer's bindings with the Shift layer as a
        read-only reference, or the shared Shift layer's own editable
        screen (DIRECTION-A.md section 3's "Shift layer page").

        Both layers' fields stay built and populated regardless of which
        is showing -- only visibility/editability changes -- so switching
        views never drops a value that _on_edit() would then sweep out of
        the state dict.
        """
        self._layer = layer
        shift = layer == "shift"
        self.column_header.setText(
            "Shift Layer (shared by all profiles)" if shift else "Base Layer")
        self.shift_reference_header.setVisible(not shift)
        self.continuous_header.setVisible(not shift)
        for row in self._rows.values():
            row.set_mode("shift" if shift else "default")
        # D-pad options are profile-scoped, so they have no meaning on the
        # Shift screen -- and no way to be written there either.
        self.swap_stick_dpad.setVisible(not shift)
        self.dpad_diagonal_lock.setVisible(not shift)
        self.options_separator.setVisible(not shift)
        self._refresh_diagram_bindings()

    def _refresh_diagram_bindings(self) -> None:
        """Feed the diagram's callouts from whichever layer is showing,
        reading each field's own already-formatted display text rather
        than recomputing it -- so a callout can never say something
        different from the row it mirrors (controller_diagram.py's
        `set_bindings` docstring)."""
        bindings = {}
        for button_id, row in self._rows.items():
            field = row.default_field if self._layer == "default" else row.shift_field
            if field.value() is not None:
                bindings[button_id] = field.text()
        self.diagram.set_bindings(bindings)

    def load_state(self, state: dict) -> None:
        self._state = state
        for button_id, row in self._rows.items():
            default_value = state["buttons"].get("default", {}).get(button_id)
            shift_value = state["buttons"].get("shift", {}).get(button_id)
            row.default_field.set_value(default_value)
            row.shift_field.set_value(shift_value)
            row.set_shift_reference(shift_value)
        self._refresh_diagram_bindings()
        continuous = state.get("continuous_trigger") or {}
        for button_id, check in self._continuous.items():
            check.blockSignals(True)
            check.setChecked(bool(continuous.get(button_id)))
            check.blockSignals(False)
        self.swap_stick_dpad.blockSignals(True)
        self.swap_stick_dpad.setChecked(bool(state.get("swap_stick_dpad")))
        self.swap_stick_dpad.blockSignals(False)
        self.dpad_diagonal_lock.blockSignals(True)
        self.dpad_diagonal_lock.setChecked(bool(state.get("dpad_diagonal_lock")))
        self.dpad_diagonal_lock.blockSignals(False)

    def _on_edit(self, *_: object) -> None:
        if self._state is None:
            return
        for button_id, row in self._rows.items():
            default_layer = self._state["buttons"].setdefault("default", {})
            shift_layer = self._state["buttons"].setdefault("shift", {})
            # value is a real keycode name, or None for "Not remapped" --
            # store it explicitly either way, never pop the key.
            #
            # REAL BUG, found 2026-09-17 (both Astra and Sol's bug-sweeps,
            # independently): this used to pop the key on Default, so
            # _build_steps() (which only visits keys that EXIST in the
            # dict) never saw the reset at all and scheduled no unbind() --
            # the old hardware binding stayed live even though the GUI
            # showed "(Default)" and Sync reported success. Storing an
            # explicit None instead works cleanly with _build_steps()'s
            # existing baseline-diff logic without any change there:
            # decode_button_table() (the read path that produces both a
            # fresh device read AND the sync baseline) already returns
            # None for every genuinely-unconfigured slot, not a missing
            # key -- so None-vs-None still skips via baseline diffing
            # (no wasted write for a button that was already Default), and
            # a real-value-to-None transition now correctly falls through
            # to _build_steps()'s "if keycode_name is None: unbind" branch.
            default_layer[button_id] = row.default_field.value()
            shift_layer[button_id] = row.shift_field.value()
            row.set_shift_reference(row.shift_field.value())
        continuous = self._state.setdefault("continuous_trigger", {})
        for button_id, check in self._continuous.items():
            continuous[button_id] = check.isChecked()
        self._state["dpad_diagonal_lock"] = self.dpad_diagonal_lock.isChecked()
        self._state["swap_stick_dpad"] = self.swap_stick_dpad.isChecked()
        self._refresh_diagram_bindings()
        self.changed.emit()

    # -- back-compat read path for tests/other code reaching into rows --

    @property
    def _combos(self) -> dict:
        """(button_id, layer) -> BindingField, mirroring the old (button_id,
        layer) -> QComboBox shape tests and MainWindow's Shift-screen tests
        read. Not a real dict -- built fresh each access so it can't drift
        from self._rows -- but supports the same `[key]`/`.items()` reads
        the pre-redesign code offered, since BindingField's set_value()/
        value() are a deliberate, documented difference from QComboBox's
        findData()/currentData(), not a compatibility shim to hide it."""
        result = {}
        for button_id, row in self._rows.items():
            result[(button_id, "default")] = row.default_field
            result[(button_id, "shift")] = row.shift_field
        return result
